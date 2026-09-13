import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live vector-search test",
)

CONTAINER = "oracle-ai-dev-db"
SEED_FILES = ["01-canonical.sql", "02-json-collection.sql", "03-duality.sql",
              "04-vector.sql", "05-graph.sql", "06-seed-data.sql"]
BOOTSTRAP = """
DECLARE n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM all_users WHERE username = 'DEMO';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER demo IDENTIFIED BY Demo_pw_12345 '
      || 'DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS';
    EXECUTE IMMEDIATE 'GRANT CONNECT, RESOURCE, CREATE VIEW, CREATE PROPERTY GRAPH TO demo';
  END IF;
END;
/
"""
# Similarity search against the seeded IVF index using a query vector.
SEARCH = """
SET PAGESIZE 0
SET HEADING OFF
SELECT 'HIT:' || r.review_id
FROM review r
ORDER BY VECTOR_DISTANCE(r.embedding, TO_VECTOR('[0.88, 0.12, 0.06]'), COSINE)
FETCH APPROX FIRST 2 ROWS ONLY;
"""


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
         f"{user}@localhost:1521/FREEPDB1"],
        input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


@pytest.mark.live
def test_ivf_similarity_search(repo_root: Path):
    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    env = {**os.environ, "DB_HOST_PORT": "1599"}
    subprocess.run(["docker", "compose", "-p", "oadvec", "-f", compose, "up", "-d"],
                   check=True, env=env)
    try:
        for _ in range(72):
            h = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
                               capture_output=True, text=True).stdout.strip()
            if h == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db not healthy")
        assert "ORA-" not in _sql(BOOTSTRAP, user="system/devpassword")
        for f in SEED_FILES:
            out = _sql((seed_dir / f).read_text())
            assert "ORA-" not in out, f"{f}:\n{out}"
        res = _sql(SEARCH)
        assert "ORA-" not in res, f"vector search error:\n{res}"
        assert res.count("HIT:") == 2, f"expected 2 nearest reviews:\n{res}"
    finally:
        subprocess.run(["docker", "compose", "-p", "oadvec", "-f", compose, "down", "-v"], env=env)

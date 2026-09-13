import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live ingestion round-trip",
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


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
                        f"{user}@localhost:1521/FREEPDB1"],
                       input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


@pytest.mark.live
def test_ddl_ingested_then_generated_query_runs(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.ingest import model_from_ddl
    from tooling.generate.sql import generate_relational

    # Ingest the canonical DDL the seed itself defines.
    ddl = (repo_root / "assets/seed/01-canonical.sql").read_text()
    model, _ann = model_from_ddl(ddl)
    assert "orders" in model["entities"] and "order_item" in model["entities"]

    # Generate a query joining orders -> order_item using the ingested model.
    query = {
        "root": "orders",
        "returns": ["orders.total", "order_item.quantity"],
        "predicates": [{"ref": "orders.order_id", "op": "=", "value": 1000}],
    }
    sql = generate_relational(model, query)

    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    env = {**os.environ, "DB_HOST_PORT": "1599"}
    subprocess.run(["docker", "compose", "-p", "oading", "-f", compose, "up", "-d"], check=True, env=env)
    try:
        for _ in range(72):
            if subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
                              capture_output=True, text=True).stdout.strip() == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db not healthy")
        assert "ORA-" not in _sql(BOOTSTRAP, user="system/devpassword")
        for f in SEED_FILES:
            assert "ORA-" not in _sql((seed_dir / f).read_text())

        out = _sql(f"SET PAGESIZE 50\n{sql};")
        assert "ORA-" not in out, f"ingested-model query failed:\n{sql}\n{out}"
        assert "no rows selected" not in out.lower(), f"returned nothing:\n{sql}\n{out}"
    finally:
        subprocess.run(["docker", "compose", "-p", "oading", "-f", compose, "down", "-v"], env=env)

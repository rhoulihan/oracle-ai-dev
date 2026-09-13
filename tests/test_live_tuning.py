import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live tuning test",
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
EXPLAIN = """
SET PAGESIZE 200
EXPLAIN PLAN FOR
  SELECT o.order_id, r.name FROM orders o
  JOIN restaurant r ON r.restaurant_id = o.restaurant_id
  WHERE o.order_id = 1000;
SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY);
"""
# The Tuning/Diagnostics packs are licensed on Free (gap-1): bracket-snapshot AWR.
AWR = """
SET SERVEROUTPUT ON
SET PAGESIZE 0
BEGIN DBMS_WORKLOAD_REPOSITORY.CREATE_SNAPSHOT; END;
/
BEGIN DBMS_WORKLOAD_REPOSITORY.CREATE_SNAPSHOT; END;
/
SELECT 'SNAPS:' || COUNT(*) FROM dba_hist_snapshot;
"""


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
         f"{user}@localhost:1521/FREEPDB1"],
        input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


@pytest.mark.live
def test_explain_plan_and_awr_snapshots(repo_root: Path):
    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    env = {**os.environ, "DB_HOST_PORT": "1599"}
    subprocess.run(["docker", "compose", "-p", "oadtune", "-f", compose, "up", "-d"],
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
            assert "ORA-" not in _sql((seed_dir / f).read_text())

        plan = _sql(EXPLAIN)
        assert "ORA-" not in plan, f"explain error:\n{plan}"
        assert "SELECT STATEMENT" in plan, f"no plan produced:\n{plan}"

        # AWR requires the Diagnostics/Tuning pack — verifies it's licensed on Free.
        awr = _sql(AWR, user="system/devpassword")
        assert "ORA-" not in awr, f"AWR snapshot error (pack licensing?):\n{awr}"
        assert "SNAPS:" in awr, f"no snapshot count:\n{awr}"
    finally:
        subprocess.run(["docker", "compose", "-p", "oadtune", "-f", compose, "down", "-v"], env=env)

import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live seed-load test",
)

DB_HOST_PORT = os.environ.get("DB_HOST_PORT", "1599")
CONTAINER = "oracle-ai-dev-db"
SEED_FILES = ["01-canonical.sql", "02-json-collection.sql", "03-duality.sql",
              "04-vector.sql", "05-graph.sql", "06-seed-data.sql"]

# The seed must load into an app schema on an ASSM tablespace (USERS) — the JSON
# type cannot live in the non-ASSM SYSTEM tablespace (ORA-43853). This mirrors
# how a developer would load it: as a least-privilege app user, never SYSTEM.
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


def _run_sql(sql_text: str, user: str = "demo/Demo_pw_12345") -> str:
    p = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
         f"{user}@localhost:1521/FREEPDB1"],
        input=sql_text, capture_output=True, text=True)
    return p.stdout + p.stderr


@pytest.mark.live
def test_full_seed_loads_and_verifies(repo_root: Path):
    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    proj = "oadseed"
    env = {**os.environ, "DB_HOST_PORT": DB_HOST_PORT}
    subprocess.run(["docker", "compose", "-p", proj, "-f", compose, "up", "-d"],
                   check=True, env=env)
    try:
        for _ in range(72):
            out = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
                capture_output=True, text=True).stdout.strip()
            if out == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db did not become healthy in time")

        boot = _run_sql(BOOTSTRAP, user="system/devpassword")
        assert "ORA-" not in boot, f"schema bootstrap error:\n{boot}"

        for f in SEED_FILES:
            out = _run_sql((seed_dir / f).read_text())
            assert "ORA-" not in out and "SP2-" not in out, f"{f} load error:\n{out}"

        verify = _run_sql((repo_root / "assets/verify/verify-seed.sql").read_text())
        for name in ("seed_restaurant", "seed_menu_item", "seed_customer",
                     "seed_address", "seed_orders", "seed_order_item", "seed_review",
                     "seed_order_docs", "seed_vector_index", "seed_graph"):
            assert f"ASSERT:{name}:PASS" in verify, f"{name} not PASS:\n{verify}"

        # Duality view must actually READ (assert success, not just absence of one
        # error code): count the two seeded orders with no ORA-/SP2- errors.
        dv = _run_sql("SET PAGESIZE 0\nSELECT COUNT(*) FROM order_dv;")
        assert "ORA-" not in dv and "SP2-" not in dv, f"duality read failed:\n{dv}"
        assert "2" in dv, f"expected 2 orders in duality view:\n{dv}"

        # Idempotency: re-running the data file must not error or duplicate.
        again = _run_sql((seed_dir / "06-seed-data.sql").read_text())
        assert "ORA-" not in again, f"06 re-run errored:\n{again}"
        verify2 = _run_sql((repo_root / "assets/verify/verify-seed.sql").read_text())
        assert "ASSERT:seed_order_docs:PASS" in verify2, f"re-run changed state:\n{verify2}"
    finally:
        subprocess.run(["docker", "compose", "-p", proj, "-f", compose, "down", "-v"], env=env)

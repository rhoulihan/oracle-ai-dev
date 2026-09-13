import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live generated-query test",
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
GET_ORDER = {
    "root": "Order",
    "returns": ["Order.total", "Restaurant.name", "OrderItem.quantity"],
    "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}],
}


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
         f"{user}@localhost:1521/FREEPDB1"],
        input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


@pytest.mark.live
def test_generated_queries_run_against_seed(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import generate_candidates
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())
    candidates = generate_candidates(model, GET_ORDER)

    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    env = {**os.environ, "DB_HOST_PORT": "1599"}
    subprocess.run(["docker", "compose", "-p", "oadgen", "-f", compose, "up", "-d"],
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

        # Every GENERATED shape query must run and return the order.
        for shape, sql in candidates.items():
            out = _sql(f"SET PAGESIZE 50\n{sql};")
            assert "ORA-" not in out, f"generated {shape} query failed:\n{sql}\n{out}"
            assert "no rows selected" not in out.lower(), f"generated {shape} returned nothing:\n{sql}\n{out}"

        # The SQL-view fallback (JSON_OBJECT-wrapped) must also run for a
        # duality-unsupported (COALESCE) query.
        from tooling.generate.sql import generate_sql_view, generate_relational
        coalesce_q = {**GET_ORDER, "requires_ops": ["coalesce"]}
        vsql = generate_sql_view(model, coalesce_q)
        vout = _sql(f"SET PAGESIZE 50\n{vsql};")
        assert "ORA-" not in vout, f"generated sql_view query failed:\n{vsql}\n{vout}"
        assert "no rows selected" not in vout.lower(), f"sql_view returned nothing:\n{vsql}\n{vout}"

        # A query with a RANGE predicate + a COALESCE computed field must run.
        rich = {
            "root": "Order",
            "returns": ["Order.total", "Restaurant.name"],
            "predicates": [{"ref": "Order.total", "op": ">=", "value": 10}],
            "computed": [{"name": "label",
                          "expr": "COALESCE(restaurant.name, 'Unknown')"}],
        }
        rsql = generate_relational(model, rich)
        rout = _sql(f"SET PAGESIZE 50\n{rsql};")
        assert "ORA-" not in rout, f"generated rich query failed:\n{rsql}\n{rout}"
        assert "no rows selected" not in rout.lower(), f"rich query returned nothing:\n{rsql}\n{rout}"
    finally:
        subprocess.run(["docker", "compose", "-p", "oadgen", "-f", compose, "down", "-v"], env=env)

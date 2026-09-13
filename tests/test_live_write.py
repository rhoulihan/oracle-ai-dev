import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live read+write benchmark",
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
    EXECUTE IMMEDIATE 'GRANT SELECT_CATALOG_ROLE TO demo';  -- V$MYSTAT redo/gets (P1)
  END IF;
END;
/
"""
QUERY = {"root": "Order", "returns": ["OrderItem.quantity"],
         "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}]}
_BENCH = re.compile(r"BENCH:(\w+):(\d+)")


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
         f"{user}@localhost:1521/FREEPDB1"],
        input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


def _time_dml(repo_root, label, dml, iters=200):
    harness = (repo_root / "assets/bench/time-dml.sql").read_text()
    one_line = " ".join(dml.split()).rstrip(";")
    script = f'DEFINE label = "{label}"\nDEFINE iters = {iters}\nDEFINE dml = "{one_line}"\n' + harness
    out = _sql(script)
    assert "ORA-" not in out, f"{label} DML error:\n{out}"
    from tooling.optimize.benchparse import parse_bench
    d = parse_bench(out)
    assert d, f"no BENCH line for {label}:\n{out}"
    return float(d["primary"])  # per-iter redo bytes (write amplification, P5)


@pytest.mark.live
def test_write_amplification_measured_and_seed_preserved(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import generate_update
    from tooling.optimize.analyze import recommend_design_options
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())

    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    env = {**os.environ, "DB_HOST_PORT": "1599"}
    subprocess.run(["docker", "compose", "-p", "oadwr2", "-f", compose, "up", "-d"], check=True, env=env)
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

        # Measure the child-field UPDATE per shape (write amplification).
        write_ms = {"get_order": {}}
        for shape in ("relational", "document"):
            dml = generate_update(model, QUERY, shape, set_ref="OrderItem.quantity", delta=1)
            write_ms["get_order"][shape] = _time_dml(repo_root, shape, dml)

        # Fabricate plausible read costs (document read-fast) and drive the options.
        read_ms = {"get_order": {"relational": 5.0, "document": 1.0}}
        opts = recommend_design_options(read_ms, write_ms, {"get_order": 10}, {"get_order": 100})
        assert opts and opts[0]["rank"] == 1
        print("\nWRITE_MS:", write_ms["get_order"], "-> top design:", opts[0]["design"])

        # The harness ROLLBACKs, so the seed must be unchanged.
        verify = _sql((repo_root / "assets/verify/verify-seed.sql").read_text())
        assert "ASSERT:seed_order_docs:PASS" in verify, f"seed changed after write bench:\n{verify}"
        assert "ASSERT:seed_order_item:PASS" in verify
    finally:
        subprocess.run(["docker", "compose", "-p", "oadwr2", "-f", compose, "down", "-v"], env=env)

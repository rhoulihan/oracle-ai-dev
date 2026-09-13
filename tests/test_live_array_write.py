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
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live array-append benchmark",
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
Q = {"root": "Order", "returns": ["OrderItem.quantity"],
     "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}]}
ELEM = {"menu_item_id": 20, "quantity": 1, "unit_price": 6.00}
_BENCH = re.compile(r"BENCH:(\w+):(\d+)")


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
                        f"{user}@localhost:1521/FREEPDB1"],
                       input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


def _time_dml(repo_root, label, dml, iters=100):
    harness = (repo_root / "assets/bench/time-dml.sql").read_text()
    one_line = " ".join(dml.split()).rstrip(";")
    # Inline the DML into the q'[...]' operator rather than a DEFINE — the document
    # append's JSON literal contains double quotes that would break DEFINE "...".
    body = harness.replace("&dml", one_line)
    script = f'DEFINE label = "{label}"\nDEFINE iters = {iters}\n' + body
    out = _sql(script)
    assert "ORA-" not in out, f"{label} DML error:\n{out}"
    from tooling.optimize.benchparse import parse_bench
    d = parse_bench(out)
    assert d, f"no BENCH for {label}:\n{out}"
    return float(d["primary"])  # per-iter redo bytes (write amplification, P5)


@pytest.mark.live
def test_array_append_amplification_measured(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import generate_array_append
    from tooling.optimize.analyze import recommend_design_options
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())

    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    env = {**os.environ, "DB_HOST_PORT": "1599"}
    subprocess.run(["docker", "compose", "-p", "oadarr", "-f", compose, "up", "-d"], check=True, env=env)
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

        write_ms = {"append": {}}
        for shape in ("relational", "document"):
            dml = generate_array_append(model, Q, shape, "$.items", ELEM)
            write_ms["append"][shape] = _time_dml(repo_root, shape, dml)

        read_ms = {"append": {"relational": 5.0, "document": 1.0}}
        opts = recommend_design_options(read_ms, write_ms, {"append": 10}, {"append": 100})
        assert opts and opts[0]["rank"] == 1
        print("\nAPPEND_MS:", write_ms["append"], "-> top:", opts[0]["design"])

        # seed unchanged (harness rolls back)
        verify = _sql((repo_root / "assets/verify/verify-seed.sql").read_text())
        assert "ASSERT:seed_order_docs:PASS" in verify and "ASSERT:seed_order_item:PASS" in verify
    finally:
        subprocess.run(["docker", "compose", "-p", "oadarr", "-f", compose, "down", "-v"], env=env)

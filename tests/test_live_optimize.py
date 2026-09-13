import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live benchmark",
)

DB_HOST_PORT = os.environ.get("DB_HOST_PORT", "1599")
CONTAINER = "oracle-ai-dev-db"
SEED_FILES = ["01-canonical.sql", "02-json-collection.sql", "03-duality.sql",
              "04-vector.sql", "05-graph.sql", "06-seed-data.sql"]
SHAPES = ["relational", "duality", "document"]
BOOTSTRAP = """
DECLARE n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM all_users WHERE username = 'DEMO';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER demo IDENTIFIED BY Demo_pw_12345 '
      || 'DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS';
    EXECUTE IMMEDIATE 'GRANT CONNECT, RESOURCE, CREATE VIEW, CREATE PROPERTY GRAPH TO demo';
    -- so the bench harness can read V$MYSTAT logical-reads / redo (P1)
    EXECUTE IMMEDIATE 'GRANT SELECT_CATALOG_ROLE TO demo';
  END IF;
END;
/
"""
# Gather stats so the CBO plans on real cardinality before we measure (P6).
GATHER_STATS = """
BEGIN
  DBMS_STATS.GATHER_SCHEMA_STATS(USER, options => 'GATHER',
    cascade => TRUE, degree => 2,
    method_opt => 'FOR ALL COLUMNS SIZE AUTO');
END;
/
"""


def _sql(text, user="demo/Demo_pw_12345"):
    p = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sqlplus", "-S",
         f"{user}@localhost:1521/FREEPDB1"],
        input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


def _bench(repo_root: Path, shape, iters=200):
    harness = (repo_root / "assets/bench/time-query.sql").read_text()
    # DEFINE values are single-line; collapse the query to one line.
    raw = (repo_root / f"assets/bench/get_order.{shape}.sql").read_text()
    query = " ".join(raw.split()).rstrip(";")
    script = (f'DEFINE label = "{shape}"\n'
              f'DEFINE iters = {iters}\n'
              f'DEFINE query_text = "{query}"\n' + harness)
    out = _sql(script)
    assert "ORA-" not in out, f"{shape} bench error:\n{out}"
    from tooling.optimize.benchparse import parse_bench
    d = parse_bench(out)
    assert d, f"no BENCH line for {shape}:\n{out}"
    return float(d["primary"])  # per-exec logical reads (deterministic)


def _plan(repo_root: Path, shape):
    """Capture the actual execution plan for a shape (the 'why' behind the cost)."""
    harness = (repo_root / "assets/bench/explain-query.sql").read_text()
    raw = (repo_root / f"assets/bench/get_order.{shape}.sql").read_text()
    query = " ".join(raw.split()).rstrip(";")
    script = f'DEFINE label = "{shape}"\n' + harness.replace("&query_text", query)
    return _sql(script)


@pytest.mark.live
def test_measure_shapes_and_recommend(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.optimize.analyze import optimal_shape_per_query, recommend_global_design

    compose = str(repo_root / "assets/compose/db.compose.yml")
    seed_dir = repo_root / "assets/seed"
    proj = "oadopt"
    env = {**os.environ, "DB_HOST_PORT": DB_HOST_PORT}
    subprocess.run(["docker", "compose", "-p", proj, "-f", compose, "up", "-d"],
                   check=True, env=env)
    try:
        for _ in range(72):
            h = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
                capture_output=True, text=True).stdout.strip()
            if h == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db did not become healthy in time")

        assert "ORA-" not in _sql(BOOTSTRAP, user="system/devpassword")
        for f in SEED_FILES:
            out = _sql((seed_dir / f).read_text())
            assert "ORA-" not in out, f"{f}:\n{out}"
        assert "ORA-" not in _sql(GATHER_STATS)  # plan on real cardinality (P6)

        measurements = {"get_order": {s: _bench(repo_root, s) for s in SHAPES}}
        opt = optimal_shape_per_query(measurements)
        assert opt["get_order"]["shape"] in SHAPES
        assert all(v >= 0 for v in measurements["get_order"].values())

        design = recommend_global_design(measurements, {"get_order": 100})
        assert design["savings"] >= 0
        assert design["per_query_optimal"]["get_order"]["shape"] in SHAPES
        print("\nMEASURED:", measurements["get_order"], "->", opt["get_order"]["shape"])

        # The 'why': capture each shape's actual plan (A-Rows/Buffers per op).
        for s in SHAPES:
            plan = _plan(repo_root, s)
            assert "PLAN_TABLE_OUTPUT" in plan or "Operation" in plan, \
                f"no plan captured for {s}:\n{plan}"
            print(f"\nPLAN[{s}]:\n{plan}")
    finally:
        subprocess.run(["docker", "compose", "-p", proj, "-f", compose, "down", "-v"], env=env)

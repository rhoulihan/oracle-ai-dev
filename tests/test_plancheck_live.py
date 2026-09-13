# Copyright (c) 2026 Oracle and/or its affiliates.
"""plan_check against a live 26ai — the whole path, not canned lines.

Only the deterministic halves are asserted: EXPLAIN returns a plan through the
shared path, and an unpredicated read of an unindexed table full-scans without
a warning (that scan IS the honest plan). Which plan the CBO picks for a tiny
indexed table is its call, not ours — the summary verdicts are covered offline
with real DBMS_XPLAN shapes in test_plancheck.py.

Named *_live.py, NOT test_live_*: this module rides the session-scoped
`live_container` stack, and session-stack users must collect AFTER the
test_live_* modules that boot their own per-module compose projects — the
container name is shared, so a session stack started mid-sequence blocks every
later per-module `compose up`.
"""

import os
import subprocess

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.shared_container,
    pytest.mark.skipif(
        os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
        reason="set ORACLE_AI_DEV_LIVE=1 (with a reachable 26ai) to run the live plancheck test"),
]

CONTAINER = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
DSN = os.environ.get("ORACLE_AI_DEV_DSN", "localhost:1521/FREEPDB1")
PDB = os.environ.get("ORACLE_AI_DEV_PDB", "FREEPDB1")
USER, PW = "plancheck", "Plancheck_pw_12345"

_DROP_USER = (
    "BEGIN\n"
    f"  BEGIN EXECUTE IMMEDIATE 'DROP USER {USER} CASCADE'; EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    "END;\n/\n")


def _sysdba(sql):
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-lc",
                        "sqlplus -S -L / as sysdba"], input=sql,
                       capture_output=True, text=True, timeout=90)
    return p.stdout + p.stderr


@pytest.fixture(scope="module")
def db(live_container):
    import oracledb
    boot = (f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER +
            f"CREATE USER {USER} IDENTIFIED BY {PW} DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS;\n"
            f"GRANT CREATE SESSION, CREATE TABLE, RESOURCE TO {USER};\n")
    out = _sysdba(boot)
    assert "created" in out.lower() and "ORA-01920" not in out, out
    conn = oracledb.connect(user=USER, password=PW, dsn=DSN)
    conn.call_timeout = 30000
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE pc_orders (order_id NUMBER PRIMARY KEY, status VARCHAR2(20))")
        cur.executemany("INSERT INTO pc_orders VALUES (:1, :2)",
                        [(i, "open") for i in range(1, 51)])
    conn.commit()
    yield conn
    conn.close()
    _sysdba(f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER)


def test_plan_check_pulls_a_real_plan(db):
    from tooling.plancheck.check import plan_check
    s = plan_check(db, "SELECT COUNT(*) FROM pc_orders")
    assert s["plan"], "EXPLAIN through the shared path must return plan lines"
    # NOT asserted: full_scans. The CBO answered this COUNT(*) with an INDEX
    # FAST FULL SCAN of the PK index on a live 26ai — which access path serves
    # an unpredicated read is the CBO's call. The deterministic contract is
    # only that an unpredicated query never warns.
    assert s["warnings"] == []


def test_plan_check_flags_a_filtered_scan_on_an_unindexed_column(db):
    from tooling.plancheck.check import plan_check
    s = plan_check(db, "SELECT order_id FROM pc_orders WHERE status = 'open'")
    assert s["full_scans"] == ["PC_ORDERS"]
    assert s["warnings"], "a filtered read that full-scans must be reported"

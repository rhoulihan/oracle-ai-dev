# Copyright (c) 2026 Oracle and/or its affiliates.
"""Phase-2 live verification — the `summary` design (materialized aggregates)
against a real 26ai Free (spec §7).

Proves on the live engine what the unit tier can only assert as strings: the
emitted MV log + `REFRESH FAST ON COMMIT` aggregate MV are ACCEPTED DDL at all
(the statement-fresh route is closed — ORA-32428, spec §2); a COMMITTED seed
maintains the MV with no refresh call anywhere in this file; the MV read
answers the same question as the relational GROUP BY (equivalence before
speed); the commit-inclusive write protocol round-trips exactly, so measuring a
summary write leaves no residue (the §2 P3 probe as a regression test); an
UNcommitted write leaves the MV untouched — precisely why the write cell must
commit (§4); and the precompute inequality is PRICED by the election on real
measured numbers — rejected under a write flood, elected under a read flood.

Gated: ORACLE_AI_DEV_LIVE=1 with a reachable 26ai (env ORACLE_AI_DEV_CONTAINER
/ ORACLE_AI_DEV_DSN / ORACLE_AI_DEV_PDB; defaults oracle-ai-dev-db /
localhost:1521/FREEPDB1 / FREEPDB1).
"""
import os
import subprocess
import time

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.shared_container,
    pytest.mark.skipif(
        os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
        reason="set ORACLE_AI_DEV_LIVE=1 (with a reachable 26ai) to run the "
               "summary/materialized-view live tests"),
]

CONTAINER = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
DSN = os.environ.get("ORACLE_AI_DEV_DSN", "localhost:1521/FREEPDB1")
PDB = os.environ.get("ORACLE_AI_DEV_PDB", "FREEPDB1")
USER, PW = "sumval", "Sumval_pw_12345"

# One aggregation signature, declared once: the MV's definition and the query
# measured against it must be the SAME question or nothing below means anything.
AGG_Q = {"root": "Order", "group_by": ["Order.status"],
         "aggregates": [{"name": "n", "fn": "COUNT", "ref": "*"},
                        {"name": "t", "fn": "SUM", "ref": "Order.total"}]}

MODEL = {
    "entities": {
        "Customer": {"table": "sm_customers", "pk": "customer_id",
                     "columns": {"name": "name"}},
        "Order": {"table": "sm_orders", "pk": "order_id",
                  "columns": {"customer_id": "customer_id",
                              "status": "status", "total": "total"},
                  "column_types": {"total": "NUMBER"}},
    },
    "relationships": [{"from": "Customer", "to": "Order", "cardinality": "1:N",
                       "from_key": "customer_id", "to_key": "customer_id"}],
    "projections": {"summary": {"mvs": [{"name": "sm_mv_by_status",
                                         "query": AGG_Q}]}},
}

# The measured write pattern — shared by the round-trip proof and the election
# smoke so both price the SAME statement (spec §4 compensation derivation).
WRITE_PATTERN = {
    "name": "bump", "kind": "write", "rate": 1,
    "query": {"root": "Order", "returns": ["Order.total"],
              "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]},
    "write": {"op": "update", "set_ref": "Order.total", "delta": 1},
}

_DROP_USER = (
    "BEGIN\n"
    f"  BEGIN EXECUTE IMMEDIATE 'ALTER USER {USER} ACCOUNT LOCK'; EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    f"  FOR s IN (SELECT sid, serial# sn FROM v$session WHERE username='{USER.upper()}') LOOP\n"
    "    BEGIN EXECUTE IMMEDIATE 'ALTER SYSTEM DISCONNECT SESSION '''||s.sid||','||s.sn||''' IMMEDIATE';\n"
    "    EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    "  END LOOP;\n"
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
    # CREATE MATERIALIZED VIEW is NOT in RESOURCE — without it every MV in this
    # file dies on ORA-01031 and the whole design looks unsupported.
    boot = (f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER +
            f"CREATE USER {USER} IDENTIFIED BY {PW} DEFAULT TABLESPACE USERS "
            f"QUOTA UNLIMITED ON USERS;\n"
            f"GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, "
            f"CREATE MATERIALIZED VIEW, RESOURCE, SELECT_CATALOG_ROLE TO {USER};\n")
    out = _sysdba(boot)
    assert "created" in out.lower() and "ORA-01920" not in out, out
    conn = oracledb.connect(user=USER, password=PW, dsn=DSN)
    conn.call_timeout = 60000   # an ON COMMIT refresh rides inside a COMMIT
    yield conn
    conn.close()
    _sysdba(f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER)


def _exec(conn, ddl):
    for stmt in (s.strip() for s in ddl.split(";")):
        if not stmt:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
        except Exception as exc:
            code = getattr(exc.args[0], "code", None) if exc.args else None
            # 12006 (MV name exists) / 12007 (MV redefinition): the §2 P4/P5 pair.
            if code not in (955, 1430, 2260, 2264, 2275, 942, 1418, 2261, 1408,
                            12000, 12006, 12007):
                raise
    conn.commit()


def _rows(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def _mv(conn, status):
    """(n, t) straight out of the materialized view — never the base tables."""
    return _rows(conn, "SELECT n, t FROM sm_mv_by_status "
                       f"WHERE status = '{status}'")[0]


@pytest.fixture(scope="module")
def deployed(db):
    """Relational lane + `_s` lane + MV log + MV, seeded and committed — once."""
    from tooling.generate.ddl import generate_ddl, generate_indexes
    from tooling.optimize.runner import summary_populate_sql

    queries = [AGG_Q, {"root": "Order", "returns": ["Order.status"],
                       "predicates": [{"ref": "Order.order_id", "op": "=",
                                       "value": 1}]}]
    _exec(db, generate_ddl(MODEL, "relational"))
    _exec(db, generate_ddl(MODEL, "summary"))
    _exec(db, generate_indexes(MODEL, queries, shape="relational"))
    _exec(db, generate_indexes(MODEL, queries, shape="summary"))

    with db.cursor() as cur:
        cur.execute("DELETE FROM sm_orders")
        cur.execute("DELETE FROM sm_customers")
        for cid, nm in [(1, "Ada"), (2, "Grace")]:
            cur.execute("INSERT INTO sm_customers (customer_id, name) "
                        "VALUES (:1, :2)", (cid, nm))
        for oid, cid, st, tot in [(1, 1, "OPEN", 10), (2, 1, "OPEN", 20),
                                  (3, 2, "SHIPPED", 30), (4, 2, "OPEN", 40)]:
            cur.execute("INSERT INTO sm_orders (order_id, customer_id, status, "
                        "total) VALUES (:1, :2, :3, :4)", (oid, cid, st, tot))
    db.commit()
    for stmt in summary_populate_sql(MODEL):
        with db.cursor() as cur:
            cur.execute(stmt)
    db.commit()   # THE commit that maintains the MV — no refresh call follows
    return True


def test_mv_and_log_deploy_and_answer(db, deployed):
    """Spec §2/§3 clause 3: the FAST ON COMMIT MV deploys and answers what relational answers."""
    from tooling.generate.sql import generate_relational, generate_summary
    from tooling.optimize.equivalence import answers_match, canonical_answer

    mvs = dict(_rows(db, "SELECT mview_name, refresh_mode FROM user_mviews"))
    assert "SM_MV_BY_STATUS" in mvs, mvs
    assert mvs["SM_MV_BY_STATUS"] == "COMMIT", mvs   # ON STATEMENT = ORA-32428

    cols = ([g.split(".", 1)[1] for g in AGG_Q["group_by"]]
            + [a["name"] for a in AGG_Q["aggregates"]])
    rel = _rows(db, generate_relational(MODEL, AGG_Q))
    smy = _rows(db, generate_summary(MODEL, AGG_Q))
    ref = canonical_answer(AGG_Q, [dict(zip(cols, r)) for r in rel], "order_id")
    got = canonical_answer(AGG_Q, [dict(zip(cols, r)) for r in smy], "order_id")
    assert answers_match(ref, got), (rel, smy)


def test_committed_seed_maintained_the_mv(db, deployed):
    """Spec §3 clause 5: the populate COMMIT maintains the MV — no refresh step exists."""
    assert _mv(db, "OPEN") == (3, 70), _mv(db, "OPEN")


def test_commit_inclusive_write_protocol_round_trips(db, deployed):
    """Spec §4 (probe P3): execute+commit moves the MV, compensation restores it exactly."""
    from tooling.generate.sql import generate_update
    from tooling.optimize.runner import summary_compensation_sql

    before = _mv(db, "OPEN")
    with db.cursor() as cur:
        cur.execute(generate_update(MODEL, WRITE_PATTERN["query"], "summary",
                                    "Order.total", 1))
    db.commit()
    assert _mv(db, "OPEN") == (before[0], before[1] + 1), (before, _mv(db, "OPEN"))

    with db.cursor() as cur:
        cur.execute(summary_compensation_sql(MODEL, WRITE_PATTERN))
    db.commit()
    assert _mv(db, "OPEN") == before, (before, _mv(db, "OPEN"))


def test_uncommitted_write_leaves_mv_untouched(db, deployed):
    """Spec §2 (probe P3) / §4: commit-time maintenance is invisible to a rolled-back cell."""
    from tooling.generate.sql import generate_update
    before = _mv(db, "OPEN")
    with db.cursor() as cur:
        cur.execute(generate_update(MODEL, WRITE_PATTERN["query"], "summary",
                                    "Order.total", 1))
    assert _mv(db, "OPEN") == before, "the MV moved before COMMIT"
    db.rollback()
    assert _mv(db, "OPEN") == before


def _median_us(fn, after=None, n=5):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1e6)
        if after:
            after()   # compensation runs OUTSIDE the timed region (spec §4)
    return sorted(xs)[n // 2]


def test_negative_election_rejects_summary_under_write_flood(db, deployed):
    """Spec §1/§8: the precompute inequality is priced by the election, not by prose."""
    from tooling.generate.sql import generate_relational, generate_summary, generate_update
    from tooling.optimize.decide import decide_model
    from tooling.optimize.runner import summary_compensation_sql

    # Volume is what makes the READ cell measurable: the MV holds two group rows
    # however large the base grows. Runs after the exactness tests by file order.
    with db.cursor() as cur:
        cur.execute("INSERT INTO sm_orders (order_id, customer_id, status, total) "
                    "SELECT 1000 + LEVEL, 1, CASE MOD(LEVEL, 2) WHEN 0 THEN 'OPEN' "
                    "ELSE 'SHIPPED' END, 10 FROM dual CONNECT BY LEVEL <= 10000")
    db.commit()
    with db.cursor() as cur:
        cur.execute("INSERT INTO sm_orders_s (order_id, customer_id, status, total) "
                    "SELECT order_id, customer_id, status, total FROM sm_orders "
                    "WHERE order_id > 1000")
    db.commit()   # one fast refresh folds 10,000 base rows into two MV groups

    rel_read = generate_relational(MODEL, AGG_Q)
    smy_read = generate_summary(MODEL, AGG_Q)
    rel_w = generate_update(MODEL, WRITE_PATTERN["query"], "relational", "Order.total", 1)
    smy_w = generate_update(MODEL, WRITE_PATTERN["query"], "summary", "Order.total", 1)
    comp = summary_compensation_sql(MODEL, WRITE_PATTERN)

    def _run(sql, finish):
        def go():
            with db.cursor() as cur:
                cur.execute(sql)
            finish()
        return go

    cost = {
        "agg": {"summary": _median_us(lambda: _rows(db, smy_read)),
                "relational": _median_us(lambda: _rows(db, rel_read))},
        "bump": {"summary": _median_us(_run(smy_w, db.commit),
                                       after=_run(comp, db.commit)),
                 "relational": _median_us(_run(rel_w, db.rollback))},
    }
    # Both halves of the inequality, named separately so a noisy box says which.
    assert cost["bump"]["summary"] > cost["bump"]["relational"], cost
    assert cost["agg"]["summary"] < cost["agg"]["relational"], cost

    hospital = {"agg": {"kind": "read", "rate": 24},
                "bump": {"kind": "write", "rate": 12000}}
    airline = {"agg": {"kind": "read", "rate": 5000},
               "bump": {"kind": "write", "rate": 10}}
    assert decide_model(hospital, cost)["chosen"] != "summary", cost
    assert decide_model(airline, cost)["ranked"][0][0] == "summary", cost


def test_rerun_is_idempotent(db, deployed):
    """Spec §2 probes P4/P5: IF NOT EXISTS redeploys; a duplicate create is tolerated."""
    from tooling.generate.ddl import generate_ddl
    _exec(db, generate_ddl(MODEL, "summary"))   # ORA-12006/12007 tolerated, nothing else
    assert _rows(db, "SELECT COUNT(*) FROM sm_mv_by_status")[0][0] >= 2

# Copyright (c) 2026 Oracle and/or its affiliates.
"""Phase-1 live verification — the hybrid shape and the partition dimension
against a real 26ai Free (spec §7).

Proves on the live engine what the unit tier can only assert as strings:
`JSON (OBJECT) LIMIT` is accepted DDL; MULTIVALUE indexes over the flex
column build; the derived hybrid lane answers the same questions as the
relational lane (equivalence before speed); flex writes round-trip; interval
partitioning lands in the dictionary for BOTH lanes; and the doc-unstated
duality-over-partitioned-base combination is pinned to its ACTUAL behavior —
if Oracle rejects it, this test fails and v1 gains a blocker instead of a
disclosure.

Gated: ORACLE_AI_DEV_LIVE=1 with a reachable 26ai (env ORACLE_AI_DEV_CONTAINER
/ ORACLE_AI_DEV_DSN / ORACLE_AI_DEV_PDB; defaults oracle-ai-dev-db /
localhost:1521/FREEPDB1 / FREEPDB1).
"""
import os
import subprocess

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.shared_container,
    pytest.mark.skipif(
        os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
        reason="set ORACLE_AI_DEV_LIVE=1 (with a reachable 26ai) to run the "
               "hybrid/partition live tests"),
]

CONTAINER = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
DSN = os.environ.get("ORACLE_AI_DEV_DSN", "localhost:1521/FREEPDB1")
PDB = os.environ.get("ORACLE_AI_DEV_PDB", "FREEPDB1")
USER, PW = "hybval", "Hybval_pw_12345"

MODEL = {
    "entities": {
        "Customer": {"table": "hp_customers", "pk": "customer_id",
                     "columns": {"name": "name"}},
        "Order": {"table": "hp_orders", "pk": "order_id",
                  "columns": {"customer_id": "customer_id",
                              "status": "status",
                              "total": "total",
                              "placed_at": "placed_at",
                              "gift_note": "gift_note",
                              "loyalty_points": "loyalty_points"},
                  "column_types": {"total": "NUMBER",
                                   "loyalty_points": "NUMBER"},
                  "partition": {"by": "interval", "column": "placed_at",
                                "interval": "NUMTOYMINTERVAL(1,'MONTH')"}},
    },
    "relationships": [{"from": "Customer", "to": "Order", "cardinality": "1:N",
                       "from_key": "customer_id", "to_key": "customer_id"}],
    "projections": {
        "hybrid": {"entities": {"Order": {"flex": ["gift_note",
                                                   "loyalty_points"]}}},
        "duality": {"Order": "hp_order_dv"},
    },
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
    boot = (f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER +
            f"CREATE USER {USER} IDENTIFIED BY {PW} DEFAULT TABLESPACE USERS "
            f"QUOTA UNLIMITED ON USERS;\n"
            f"GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, RESOURCE, "
            f"SELECT_CATALOG_ROLE TO {USER};\n")
    out = _sysdba(boot)
    assert "created" in out.lower() and "ORA-01920" not in out, out
    conn = oracledb.connect(user=USER, password=PW, dsn=DSN)
    conn.call_timeout = 30000
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
            if code not in (955, 1430, 2260, 2264, 2275, 942, 1418, 2261, 1408):
                raise
    conn.commit()


def _rows(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


@pytest.fixture(scope="module")
def deployed(db):
    """Both lanes deployed, seeded relationally, hybrid derived — once."""
    from tooling.generate.ddl import generate_ddl, generate_indexes
    from tooling.optimize.runner import hybrid_populate_sql

    q_flex = {"root": "Order", "returns": ["Order.status", "Order.gift_note"],
              "predicates": [{"ref": "Order.gift_note", "op": "=", "value": "wrap"}]}
    q_core = {"root": "Order", "returns": ["Order.status"],
              "predicates": [{"ref": "Order.status", "op": "=", "value": "OPEN"}]}
    q_agg = {"root": "Order", "group_by": ["Order.status"],
             "aggregates": [{"name": "pts", "fn": "SUM",
                             "ref": "Order.loyalty_points"}]}
    queries = [q_flex, q_core, q_agg]

    _exec(db, generate_ddl(MODEL, "relational"))
    _exec(db, generate_ddl(MODEL, "hybrid"))
    # the index DDL is part of the claim: MULTIVALUE over flex, the LOCAL
    # B-trees on the partitioned lane, and the mixed agg index must all BUILD
    _exec(db, generate_indexes(MODEL, queries, shape="relational"))
    _exec(db, generate_indexes(MODEL, queries, shape="hybrid"))

    with db.cursor() as cur:
        cur.execute("DELETE FROM hp_orders")
        cur.execute("DELETE FROM hp_customers")
        for cid, nm in [(1, "Ada"), (2, "Grace")]:
            cur.execute("INSERT INTO hp_customers (customer_id, name) "
                        "VALUES (:1, :2)", (cid, nm))
        rows = [(1, 1, "OPEN", 10, "2026-01-15", "wrap", 5),
                (2, 1, "OPEN", 20, "2026-02-15", None, 3),
                (3, 2, "SHIPPED", 30, "2026-03-15", "wrap", None),
                (4, 2, "OPEN", 40, "2026-03-20", "plain", 7)]
        for oid, cid, st, tot, day, note, pts in rows:
            cur.execute(
                "INSERT INTO hp_orders (order_id, customer_id, status, total, "
                "placed_at, gift_note, loyalty_points) VALUES "
                "(:1, :2, :3, :4, TO_TIMESTAMP(:5, 'YYYY-MM-DD'), :6, :7)",
                (oid, cid, st, tot, day, note, pts))
    db.commit()
    for stmt in hybrid_populate_sql(MODEL):
        with db.cursor() as cur:
            cur.execute(stmt)
    db.commit()
    return {"q_flex": q_flex, "q_core": q_core, "q_agg": q_agg}


def test_partition_lands_in_the_dictionary_for_both_lanes(db, deployed):
    got = dict(_rows(db, "SELECT table_name, partitioning_type "
                         "FROM user_part_tables"))
    assert got.get("HP_ORDERS") == "RANGE", got
    assert got.get("HP_ORDERS_H") == "RANGE", got
    ivl = dict(_rows(db, "SELECT table_name, interval FROM user_part_tables"))
    assert "NUMTOYMINTERVAL" in (ivl.get("HP_ORDERS") or ""), ivl


def test_hybrid_lane_answers_match_relational(db, deployed):
    from tooling.generate.sql import generate_hybrid, generate_relational
    from tooling.optimize.equivalence import answers_match, canonical_answer

    for q in (deployed["q_flex"], deployed["q_core"], deployed["q_agg"]):
        rel = _rows(db, generate_relational(MODEL, q))
        hyb = _rows(db, generate_hybrid(MODEL, q))
        cols = ([r.split(".", 1)[1] for r in q.get("returns") or []]
                or [g.split(".", 1)[1] for g in q.get("group_by") or []]
                + [a["name"] for a in q.get("aggregates") or []])
        ref = canonical_answer(q, [dict(zip(cols, r)) for r in rel], "order_id")
        got = canonical_answer(q, [dict(zip(cols, r)) for r in hyb], "order_id")
        assert answers_match(ref, got), (q, rel, hyb)


def test_flex_write_round_trips(db, deployed):
    from tooling.generate.sql import generate_update
    q = {"root": "Order", "returns": ["Order.loyalty_points"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}
    upd = generate_update(MODEL, q, "hybrid", "Order.loyalty_points", delta=2)
    with db.cursor() as cur:
        cur.execute(upd)
    val = _rows(db, "SELECT o.flex.loyalty_points.numberOnly() "
                    "FROM hp_orders_h o WHERE order_id = 1")[0][0]
    db.rollback()
    assert val == 7, val


def test_sparse_flex_attributes_stay_absent_not_null(db, deployed):
    # ABSENT ON NULL is load-bearing: a null-carrying key changes the
    # document's size and its key-presence semantics (IS NULL vs missing).
    n = _rows(db, "SELECT COUNT(*) FROM hp_orders_h o "
                  "WHERE JSON_EXISTS(o.flex, '$.gift_note')")[0][0]
    assert n == 3, n   # order 2's gift_note is NULL -> key absent


def test_duality_view_over_a_partitioned_base_actual_behavior(db, deployed):
    # Doc-unstated composition (research: system-partitioned and partitioned-
    # extended bases are read-only participants; plain partitioned heaps are
    # unlisted). Pin the REAL behavior: if this create or read fails, v1's
    # disclosure becomes a blocker — change the code, not this test's spirit.
    from tooling.generate.ddl import generate_ddl
    ddl = generate_ddl(MODEL, "duality")
    view_ddl = ddl[ddl.index("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW"):]
    _exec(db, view_ddl)
    doc = _rows(db, "SELECT d.data FROM hp_order_dv d "
                    "WHERE JSON_VALUE(d.data, '$._id' RETURNING NUMBER) = 1")
    assert doc, "the duality view over a partitioned base returned no document"

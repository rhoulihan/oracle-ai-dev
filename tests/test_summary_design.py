# Copyright (c) 2026 Oracle and/or its affiliates.
"""The summary design: materialized aggregates over a relational core.

Spec: docs/specs/2026-07-31-phase2-summary-spec.md (approved 2026-08-01).
Probe-verified mechanics (26ai Free 23.26.2): aggregate ON STATEMENT MVs do
not exist (ORA-32428 — join-shape only), so the design ships REFRESH FAST ON
COMMIT MVs + logs, and the write cells charge maintenance via the
commit-inclusive protocol (M2). The summary owns its `_s` lane — an MV on
the shared base tables would silently tax relational's write cells.
"""

import json

from tooling.datalayer.generate import bound_sql
from tooling.generate.ddl import generate_ddl, generate_indexes
from tooling.generate.model import summary_mv_for, validate_model
from tooling.generate.sql import (generate_candidates, generate_insert,
                                  generate_summary, generate_update)

MODEL = {
    "entities": {
        "Customer": {"table": "customers", "pk": "customer_id",
                     "columns": {"name": "name"}},
        "Order": {"table": "orders", "pk": "order_id",
                  "columns": {"customer_id": "customer_id",
                              "status": "status",
                              "total": "total"},
                  "column_types": {"total": "NUMBER"}},
    },
    "relationships": [{"from": "Customer", "to": "Order", "cardinality": "1:N",
                       "from_key": "customer_id", "to_key": "customer_id"}],
    "projections": {"summary": {"mvs": [
        {"name": "mv_by_status",
         "query": {"root": "Order", "group_by": ["Order.status"],
                   "aggregates": [{"name": "n", "fn": "COUNT", "ref": "*"},
                                  {"name": "t", "fn": "SUM",
                                   "ref": "Order.total"}]}}]}},
}

AGG_Q = {"root": "Order", "group_by": ["Order.status"],
         "aggregates": [{"name": "n", "fn": "COUNT", "ref": "*"},
                        {"name": "t", "fn": "SUM", "ref": "Order.total"}]}


def _m():
    return json.loads(json.dumps(MODEL))


# ------------------------------------------------------------- validation

def test_mv_needs_a_name_and_an_aggregation_query():
    m = _m()
    m["projections"]["summary"]["mvs"][0].pop("name")
    assert validate_model(m), "an unnamed MV must be a violation"
    m2 = _m()
    m2["projections"]["summary"]["mvs"][0]["query"] = {
        "root": "Order", "returns": ["Order.status"]}
    assert any("aggregation" in v for v in validate_model(m2)), validate_model(m2)


def test_mv_query_must_be_single_root():
    m = _m()
    m["projections"]["summary"]["mvs"][0]["query"]["group_by"] = ["Customer.name"]
    assert validate_model(m), "a cross-entity MV query must be a violation in v1"


def test_mv_names_must_be_unique():
    m = _m()
    m["projections"]["summary"]["mvs"].append(m["projections"]["summary"]["mvs"][0])
    assert any("mv_by_status" in v for v in validate_model(m)), validate_model(m)


# -------------------------------------------------------------------- DDL

def test_summary_ddl_owns_its_own_lane():
    ddl = generate_ddl(MODEL, "summary")
    assert "CREATE TABLE IF NOT EXISTS orders_s" in ddl, ddl
    assert "CREATE TABLE IF NOT EXISTS customers_s" in ddl, ddl
    assert "REFERENCES customers_s" in ddl, ddl


def test_mv_log_merges_columns_and_carries_the_eligibility_clauses():
    ddl = generate_ddl(MODEL, "summary")
    assert ("CREATE MATERIALIZED VIEW LOG ON orders_s WITH ROWID, "
            "SEQUENCE (status, total) INCLUDING NEW VALUES;") in ddl, ddl


def test_mv_ddl_is_on_commit_with_count_companions():
    ddl = generate_ddl(MODEL, "summary")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS mv_by_status" in ddl, ddl
    assert "REFRESH FAST ON COMMIT" in ddl, ddl
    # fast-refresh eligibility: COUNT(<arg>) companion for every SUM/AVG arg;
    # the declared COUNT(*) already satisfies the row-count requirement, so
    # no duplicate COUNT(*) companion is emitted
    assert "COUNT(total)" in ddl, ddl
    mv = ddl[ddl.index("CREATE MATERIALIZED VIEW IF NOT EXISTS"):]
    assert mv.count("COUNT(*)") == 1, mv


def test_count_star_companion_added_when_not_declared():
    m = _m()
    m["projections"]["summary"]["mvs"][0]["query"]["aggregates"] = [
        {"name": "t", "fn": "SUM", "ref": "Order.total"}]
    ddl = generate_ddl(m, "summary")
    mv = ddl[ddl.index("CREATE MATERIALIZED VIEW IF NOT EXISTS"):]
    assert "COUNT(*)" in mv and "COUNT(total)" in mv, mv


def test_partition_dimension_composes_with_the_summary_lane():
    m = _m()
    m["entities"]["Order"]["columns"]["placed_at"] = "placed_at"
    m["entities"]["Order"]["partition"] = {
        "by": "interval", "column": "placed_at",
        "interval": "NUMTOYMINTERVAL(1,'MONTH')"}
    ddl = generate_ddl(m, "summary")
    orders = ddl[ddl.index("CREATE TABLE IF NOT EXISTS orders_s"):]
    assert "PARTITION BY RANGE (placed_at)" in orders.split(";")[0], ddl


# ---------------------------------------------------------------- matching

def test_matching_aggregation_finds_its_mv():
    mv = summary_mv_for(MODEL, AGG_Q)
    assert mv and mv["name"] == "mv_by_status"


def test_aggregate_subset_still_matches():
    q = {"root": "Order", "group_by": ["Order.status"],
         "aggregates": [{"name": "n", "fn": "COUNT", "ref": "*"}]}
    assert summary_mv_for(MODEL, q)


def test_different_group_by_or_offgroup_predicate_does_not_match():
    q = {"root": "Order", "group_by": ["Order.customer_id"],
         "aggregates": [{"name": "n", "fn": "COUNT", "ref": "*"}]}
    assert summary_mv_for(MODEL, q) is None
    q2 = dict(AGG_Q, predicates=[{"ref": "Order.total", "op": ">", "value": 5}])
    assert summary_mv_for(MODEL, q2) is None, \
        "a predicate off the group-by refs cannot be answered by the MV"


def test_group_ref_predicate_keeps_the_match():
    q = dict(AGG_Q, predicates=[{"ref": "Order.status", "op": "=", "value": "OPEN"}])
    assert summary_mv_for(MODEL, q)


# ------------------------------------------------------------- query gen

def test_matched_aggregation_reads_the_mv_directly():
    sql = generate_summary(MODEL, AGG_Q)
    assert "FROM mv_by_status" in sql, sql
    assert "GROUP BY" not in sql and "orders_s" not in sql, sql
    assert "status" in sql and "n" in sql and "t" in sql, sql


def test_group_ref_predicate_filters_the_mv():
    q = dict(AGG_Q, predicates=[{"ref": "Order.status", "op": "=", "value": "OPEN"}])
    sql = generate_summary(MODEL, q)
    assert "FROM mv_by_status" in sql and "WHERE status = 'OPEN'" in sql, sql


def test_unmatched_aggregation_falls_back_to_the_lane():
    q = {"root": "Order", "group_by": ["Order.customer_id"],
         "aggregates": [{"name": "n", "fn": "COUNT", "ref": "*"}]}
    sql = generate_summary(MODEL, q)
    assert "FROM orders_s" in sql and "GROUP BY" in sql, sql


def test_point_reads_ride_the_lane_tables():
    q = {"root": "Order", "returns": ["Order.status", "Customer.name"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 5}]}
    sql = generate_summary(MODEL, q)
    assert "FROM orders_s order_t" in sql, sql
    assert "JOIN customers_s customer" in sql, sql


def test_candidates_include_summary_when_projected():
    cands = generate_candidates(MODEL, AGG_Q)
    assert "summary" in cands, sorted(cands)
    assert "mv_by_status" in cands["summary"]


# ------------------------------------------------------------------ writes

def test_writes_target_the_lane_tables():
    q = {"root": "Order", "returns": ["Order.total"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 5}]}
    sql = generate_update(MODEL, q, "summary", "Order.total")
    assert sql == "UPDATE orders_s SET total = total + 1 WHERE order_id = 5", sql
    assert generate_insert(MODEL, q, "summary") == \
        "INSERT INTO orders_s (order_id) VALUES (9999)"


def test_bound_reads_bind_against_the_mv():
    q = dict(AGG_Q, predicates=[{"ref": "Order.status", "op": "=", "value": "OPEN"}])
    sql, binds = bound_sql(MODEL, q, "summary")
    assert "FROM mv_by_status" in sql and ":b0" in sql, sql
    assert [b["name"] for b in binds] == ["b0"]


# ---------------------------------------------------------------- indexes

def test_lane_gets_relational_indexes_and_matched_aggs_get_none():
    q_pred = {"root": "Order", "returns": ["Order.status"],
              "predicates": [{"ref": "Order.status", "op": "=", "value": "OPEN"}]}
    idx = generate_indexes(MODEL, [q_pred, AGG_Q], shape="summary")
    assert "CREATE INDEX orders_s_status_ix ON orders_s (status);" in idx, idx
    assert "_agg_" not in idx, \
        f"a matched aggregation's covering structure IS the MV:\n{idx}"


def test_unmatched_aggregation_still_derives_its_index():
    q = {"root": "Order", "group_by": ["Order.customer_id"],
         "aggregates": [{"name": "n", "fn": "COUNT", "ref": "*"}]}
    idx = generate_indexes(MODEL, [q], shape="summary")
    assert "_agg_" in idx and "ON orders_s" in idx, idx


# ------------------------------------------------------- seed derivation

def test_populate_derives_the_lane_from_relational():
    from tooling.optimize.runner import summary_populate_sql
    stmts = summary_populate_sql(MODEL)
    joined = "\n".join(stmts)
    assert "INSERT INTO orders_s" in joined and "FROM orders" in joined
    assert "INSERT INTO customers_s" in joined
    assert (joined.index("INSERT INTO customers_s")
            < joined.index("INSERT INTO orders_s"))


# --------------------------------------------------------------- election

def test_summary_is_a_default_design_station():
    from tooling.optimize.runner import DEFAULT_DESIGNS
    assert DEFAULT_DESIGNS == ("document", "single_table", "hybrid",
                               "duality", "summary", "relational")


def test_candidate_shapes_gates_on_the_projection():
    from tooling.optimize.runner import candidate_shapes
    assert "summary" in candidate_shapes(MODEL, [])
    bare = _m()
    bare["projections"] = {}
    assert "summary" not in candidate_shapes(bare, [])


def test_propose_summary_nominates_per_aggregation_signature():
    from tooling.optimize.runner import propose_summary
    patterns = [
        {"name": "count_by_status", "kind": "read", "rate": 10, "query": AGG_Q},
        {"name": "same_signature", "kind": "read", "rate": 1, "query": AGG_Q},
        {"name": "point", "kind": "read", "rate": 100,
         "query": {"root": "Order", "returns": ["Order.status"],
                   "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}},
    ]
    m = _m()
    m["projections"] = {}
    prop = propose_summary(m, patterns)
    assert prop and len(prop["mvs"]) == 1, prop
    assert prop["mvs"][0]["name"] == "mv_count_by_status"
    assert propose_summary(m, [patterns[2]]) is None, \
        "no aggregation patterns -> no summary candidate"


def test_pattern_name_gives_summary_a_catalog_identity():
    from tooling.optimize.patterns import PATTERNS, pattern_name
    name = pattern_name("summary", AGG_Q)
    assert name in {x["name"] for x in PATTERNS}, name
    entry = next(x for x in PATTERNS if x["name"] == name)
    assert "summary" in entry["shapes"]


# ===================== M2 — the commit-inclusive write cell + report =====

WRITE_PAT = {"name": "bump", "kind": "write", "rate": 10.0,
             "query": {"root": "Order", "returns": ["Order.total"],
                       "predicates": [{"ref": "Order.order_id", "op": "=",
                                       "value": 5}]},
             "write": {"op": "update", "set_ref": "Order.total", "delta": 1}}


def test_compensation_derives_from_the_write_spec():
    from tooling.optimize.runner import summary_compensation_sql
    comp = summary_compensation_sql(MODEL, WRITE_PAT)
    assert comp == ("UPDATE orders_s SET total = total + -1 "
                    "WHERE order_id = 5"), comp
    ins = {"name": "mk", "kind": "write", "rate": 1.0,
           "query": WRITE_PAT["query"], "write": {"op": "insert"}}
    assert summary_compensation_sql(MODEL, ins) == \
        "DELETE FROM orders_s WHERE order_id = 9999"


def test_underivable_compensation_is_loud_not_silent():
    # the planted defect: a write whose effect cannot be undone must raise —
    # measuring it commit-inclusive would leave the lane mutated, and
    # skipping it silently would exclude the design from the decision
    from tooling.optimize.runner import summary_compensation_sql
    bad = {"name": "mystery", "kind": "write", "rate": 1.0,
           "query": WRITE_PAT["query"], "write": {"op": "slot_update"}}
    try:
        summary_compensation_sql(MODEL, bad)
        raise AssertionError("expected a loud ValueError")
    except ValueError as exc:
        assert "compensation" in str(exc), exc


def test_explicit_compensation_hatch_wins():
    from tooling.optimize.runner import summary_compensation_sql
    p = dict(WRITE_PAT, sql={"summary_compensate": "UPDATE x SET y = 0"})
    assert summary_compensation_sql(MODEL, p) == "UPDATE x SET y = 0"


class _FakeCursor:
    def __init__(self, log):
        self.log = log
        self.rowcount = 1
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def execute(self, sql, *a, **kw):
        self.log.append(("execute", " ".join(str(sql).split())[:60]))
    def fetchall(self):
        return []
    def fetchone(self):
        return None


class _FakeConn:
    def __init__(self):
        self.log = []
    def cursor(self):
        return _FakeCursor(self.log)
    def commit(self):
        self.log.append(("commit", ""))
    def rollback(self):
        self.log.append(("rollback", ""))


def test_summary_write_cell_commits_and_compensates():
    from tooling.optimize.runner import measure_cell
    conn = _FakeConn()
    cell = measure_cell(conn, MODEL, WRITE_PAT, "summary", trials=2, warmup=1)
    kinds = [k for k, _ in conn.log]
    # the zero-row gate rolls back its probe; every measured iteration
    # commits the write (maintenance inside the timed region) and commits
    # the untimed compensation — never a rollback in the measured loop
    assert kinds.count("rollback") == 1, conn.log
    assert kinds.count("commit") == 2 * (2 + 1), conn.log
    comp_execs = [s for k, s in conn.log if k == "execute" and "+ -1" in s]
    assert len(comp_execs) == 3, conn.log
    assert cell["us"] >= 0


def test_relational_write_cell_still_rolls_back():
    from tooling.optimize.runner import measure_cell
    conn = _FakeConn()
    measure_cell(conn, MODEL, WRITE_PAT, "relational", trials=2, warmup=1)
    kinds = [k for k, _ in conn.log]
    assert kinds.count("commit") == 0, conn.log
    assert kinds.count("rollback") == 1 + 2 + 1, conn.log


def test_summary_maintenance_block_disclosed_in_the_report():
    from tooling.optimize.runner import build_result, format_report
    pats = [WRITE_PAT,
            {"name": "kpi", "kind": "read", "rate": 100.0, "query": AGG_Q}]
    meas = {"bump": {"summary": 900.0, "relational": 400.0},
            "kpi": {"summary": 50.0, "relational": 800.0}}
    res = build_result(MODEL, pats, meas)
    sm = res["summary_maintenance"]
    assert sm and sm[0]["pattern"] == "bump" and sm[0]["delta_us"] == 500.0
    report = format_report(res)
    assert "SUMMARY MAINTENANCE" in report, report
    assert "bump" in report and "bias runs against" in report, report


def test_no_summary_candidate_means_no_block():
    from tooling.optimize.runner import build_result, format_report
    pats = [WRITE_PAT]
    meas = {"bump": {"relational": 400.0, "document": 900.0}}
    res = build_result(MODEL, pats, meas)
    assert not res.get("summary_maintenance")
    assert "SUMMARY MAINTENANCE" not in format_report(res)

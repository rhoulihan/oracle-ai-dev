# Copyright (c) 2026 Oracle and/or its affiliates.
"""Check the PLAN, not just the clock.

The runner captured `consistent gets` per cell and never once looked at it. A full scan of
3,000 rows is ~50+ logical reads against ~4 for an indexed probe — the signal was sitting in
the diagnostics the whole time. And the docs claimed an "index-first methodology" while the
relational design full-scanned two of its filtered reads in every run, because the document's
index had silently taken its name.

A number without its access path is not evidence. So: every filtered read gets its plan
pulled, and a TABLE ACCESS FULL on a query that HAS predicates is reported. An aggregation
with no predicate legitimately scans — that is not a warning, it is the design.
"""
import sys
from pathlib import Path


def _r(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    return r


def test_a_full_scan_on_a_filtered_read_is_a_warning(repo_root: Path):
    r = _r(repo_root)
    pattern = {"name": "by_passenger", "kind": "read",
               "query": {"root": "Res", "returns": ["Res.status"],
                         "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}}
    plan = ["SELECT STATEMENT", "TABLE ACCESS FULL| RESERVATIONS"]
    assert r.plan_warning(pattern, plan) is not None


def test_an_indexed_read_is_no_warning(repo_root: Path):
    r = _r(repo_root)
    pattern = {"name": "by_passenger", "kind": "read",
               "query": {"root": "Res", "returns": ["Res.status"],
                         "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}}
    plan = ["SELECT STATEMENT", "INDEX RANGE SCAN| RESERVATIONS_PASSENGER_ID_IX",
            "TABLE ACCESS BY INDEX ROWID| RESERVATIONS"]
    assert r.plan_warning(pattern, plan) is None


def test_an_unfiltered_aggregation_may_scan(repo_root: Path):
    """`SELECT status, COUNT(*) ... GROUP BY status` has no predicate. Scanning is not a
    defect there — it is what the query is. Warn about it and the report cries wolf."""
    r = _r(repo_root)
    agg = {"name": "count_by_status", "kind": "read",
           "query": {"root": "Res", "group_by": ["Res.status"],
                     "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"}]}}
    assert r.plan_warning(agg, ["HASH GROUP BY", "TABLE ACCESS FULL| RESERVATIONS"]) is None


ORD_MODEL = {
    "entities": {"Res": {"table": "reservations", "pk": "res_id",
                         "columns": {"status": "status", "passenger_id": "passenger_id"}}},
    "relationships": [],
    "projections": {"document": {"Res": {"collection": "res_docs", "id_path": "$._id"}},
                    "duality": {"Res": [{"view": "reservations_dv", "includes": [],
                                                 "columns": None}]}},
}
ORD_Q = {"root": "Res", "returns": ["Res.status"],
         "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}],
         "order_by": [{"ref": "Res.res_id", "dir": "DESC"}],
         "limit": 10}


def test_json_shapes_must_honour_order_by_and_limit(repo_root: Path):
    """A duality view supports ORDER BY perfectly well — you sort on a JSON_VALUE expression.
    We simply were not emitting it. So the relational query sorted and the JSON queries did
    not: duality and the document were "winning" a row by doing less work, and the equivalence
    gate compares SETS of values, so it could not see the difference."""
    import sys
    sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import generate_duality, generate_document
    for name, sql in (("duality", generate_duality(ORD_MODEL, ORD_Q)),
                      ("document", generate_document(ORD_MODEL, ORD_Q))):
        up = sql.upper()
        assert "ORDER BY" in up, f"{name} silently drops the ORDER BY:\n{sql}"
        assert "DESC" in up, f"{name} loses the sort direction:\n{sql}"
        assert "FETCH FIRST 10 ROWS ONLY" in up, f"{name} silently drops the LIMIT:\n{sql}"


def test_the_access_path_is_summarised_per_cell(repo_root: Path):
    """The optimizer must ANALYSE the plans, not just time the queries — that is how the
    capstone analysis was done by hand, and it is what turns a stopwatch into a design tool.
    Every cell reports HOW the design served the pattern."""
    r = _r(repo_root)
    assert r.plan_access(["SELECT STATEMENT", "INDEX UNIQUE SCAN| SYS_C001"]) == "IDX UNIQUE"
    assert r.plan_access(["INDEX RANGE SCAN| RES_PAX_IX",
                          "TABLE ACCESS BY INDEX ROWID| RESERVATIONS"]) == "IDX RANGE"
    assert r.plan_access(["HASH GROUP BY", "TABLE ACCESS FULL| RESERVATIONS"]) == "FULL SCAN"
    # a full scan ANYWHERE dominates the summary — it is the thing that will hurt
    assert r.plan_access(["NESTED LOOPS", "INDEX RANGE SCAN| X",
                          "TABLE ACCESS FULL| LEGS"]) == "FULL SCAN"
    assert r.plan_access([]) == "?"


def test_the_warning_names_the_table_being_scanned(repo_root: Path):
    """`DBMS_XPLAN`'s BASIC output is a pipe table; the object is the field AFTER the
    operation, not the last one (which is empty). Get it wrong and the warning reads
    'FULL SCAN of ()' — true, useless, and impossible to act on."""
    r = _r(repo_root)
    pattern = {"name": "x", "kind": "read",
               "query": {"root": "Res", "returns": ["Res.status"],
                         "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}}
    plan = ["|   1 |  TABLE ACCESS FULL| ITINERARY_RESERVATIONS |"]
    w = r.plan_warning(pattern, plan)
    assert "ITINERARY_RESERVATIONS" in w, w

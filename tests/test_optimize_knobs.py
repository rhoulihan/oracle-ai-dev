# Copyright (c) 2026 Oracle and/or its affiliates.
"""The engine's tuning knobs must be reachable, not merely exist.

write_scale existed on build_result while optimize() never passed it, and the
skills claimed sparse/partition-by-type "can be disabled" when no CLI could do
it — a parameter that exists, is documented, and cannot be reached is the same
honesty defect as prose pretending to be mechanism. These tests pin the whole
path: flag -> optimize() -> the function that consumes it.
"""

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

MODEL = {
    "entities": {
        "Order": {"table": "orders", "pk": "order_id", "columns": {"total": "total"}},
    },
    "relationships": [],
    "projections": {"document": {"Order": {"collection": "order_docs"}}},
}
PATTERNS = [
    {"name": "read_order", "kind": "read", "rate": 1.0,
     "query": {"root": "Order", "returns": ["Order.total"]}},
    {"name": "write_order", "kind": "write", "rate": 1.0,
     "query": {"root": "Order", "returns": ["Order.total"]}},
]
# relational reads dearly but writes cheaply; document the reverse — so the
# election flips as the write mix scales up.
MEAS = {"read_order": {"relational": 100.0, "document": 1.0},
        "write_order": {"relational": 1.0, "document": 50.0}}


def test_cli_help_lists_the_tuning_knobs():
    r = subprocess.run([sys.executable, "-m", "tooling.optimize", "--help"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0
    for flag in ("--write-scale", "--walk-scales", "--no-sparse", "--no-partition-by-type"):
        assert flag in r.stdout, f"missing CLI knob: {flag}"


def test_build_result_threads_write_scale_into_the_election():
    from tooling.optimize.runner import build_result
    balanced = build_result(MODEL, PATTERNS, MEAS)
    write_heavy = build_result(MODEL, PATTERNS, MEAS, write_scale=100.0)
    assert balanced["chosen"] == "document"
    assert write_heavy["chosen"] == "relational", \
        "a 100x write mix must walk the choice to the write-cheap design"


def test_build_result_threads_walk_scales_and_reports_the_walk():
    from tooling.optimize.runner import build_result
    result = build_result(MODEL, PATTERNS, MEAS, walk_scales=(0.5, 200.0))
    assert [s for s, _ in result["walk"]] == [0.5, 200.0]
    assert dict(result["walk"])[200.0] == "relational"


def test_winning_ddl_honors_sparse_and_partition_knobs():
    from tooling.optimize.runner import winning_ddl
    m = {"entities": {"Fare": {"table": "fares", "pk": "fare_id",
                               "columns": {"origin": "origin"}}},
         "relationships": [],
         "projections": {"single_table": {
             "table": "converged_items",
             "types": {"fare": {"key": ["origin"]}}}}}
    on = winning_ddl(m, "single_table")
    off = winning_ddl(m, "single_table", sparse=False, partition_by_type=False)
    assert "PARTITION BY LIST" in on and "CASE WHEN" in on
    assert "PARTITION BY LIST" not in off and "CASE WHEN" not in off


def test_optimize_threads_the_knobs_end_to_end(monkeypatch):
    """The regression this file exists for: optimize() must PASS the knobs on.
    The database boundary is stubbed; everything from spec to election is real."""
    import tooling.optimize.runner as r
    seen = {}
    monkeypatch.setattr(r, "candidate_shapes", lambda m, p, only=None: ["relational", "document"])
    monkeypatch.setattr(r, "deploy", lambda conn, m, p, s, **kw: seen.setdefault("deploy_kw", kw))
    monkeypatch.setattr(r, "gather_stats", lambda conn: None)
    monkeypatch.setattr(r, "validate_answers", lambda conn, m, p, c, progress=None: ({}, []))
    monkeypatch.setattr(r, "measure",
                        lambda conn, m, p, c, trials=7, warmup=2, invalid=None: (MEAS, {}))
    monkeypatch.setattr(r, "flip_sweep", lambda m, p, meas: [])
    monkeypatch.setattr(r, "winning_ddl",
                        lambda m, chosen, **kw: seen.setdefault("ddl_kw", kw) or "")

    spec = {"model": MODEL, "patterns": PATTERNS}
    result = r.optimize(None, spec, do_seed=False, write_scale=100.0,
                        sparse=False, partition_by_type=False)
    assert result["chosen"] == "relational", "write_scale must reach the election"
    assert seen["deploy_kw"] == {"sparse": False, "partition_by_type": False,
                                 "partition": True, "flex_limit": 8192,
                                 "iot": True, "compress": True}
    assert seen["ddl_kw"] == {"sparse": False, "partition_by_type": False,
                              "partition": True, "flex_limit": 8192,
                              "iot": True, "compress": True}, \
        "the emitted winner must be built exactly as the measured one was"

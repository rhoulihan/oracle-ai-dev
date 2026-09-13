# Copyright (c) 2026 Oracle and/or its affiliates.
"""The measured-optimization runner — `python -m tooling.optimize`.

Codifies the six steps the agent used to hand-assemble: derive indexes -> deploy every
candidate shape -> seed -> measure every pattern x every shape on the live DB -> build
the full cost matrix -> decide, and emit the winning DDL.
"""
import json
import sys
from pathlib import Path

import pytest


def _r(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    return r


WORKLOAD = {
    "model": {
        "entities": {"Order": {"table": "orders", "pk": "order_id",
                               "columns": {"total": "total", "status": "status"}}},
        "relationships": [],
        "projections": {"document": {"Order": {"collection": "order_docs", "id_path": "$._id"}}},
    },
    "patterns": [
        {"name": "get_order", "kind": "read", "rate": 5000,
         "query": {"root": "Order", "returns": ["Order.total"],
                   "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}},
        {"name": "by_status", "kind": "read", "rate": 120,
         "query": {"root": "Order", "returns": ["Order.total"],
                   "predicates": [{"ref": "Order.status", "op": "=", "value": "OPEN"}]}},
        {"name": "update_total", "kind": "write", "rate": 800,
         "query": {"root": "Order", "returns": ["Order.total"],
                   "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]},
         "write": {"op": "update", "set_ref": "Order.total", "delta": 1}},
    ],
}


def test_candidate_shapes_come_from_the_model(repo_root: Path):
    """The agent proposes candidate models (projections); the runner measures whatever
    the model declares. relational is always a candidate."""
    r = _r(repo_root)
    shapes = r.candidate_shapes(WORKLOAD["model"], WORKLOAD["patterns"])
    assert "relational" in shapes
    assert "document" in shapes          # the model declares a document projection


def test_read_and_write_patterns_are_split_by_kind(repo_root: Path):
    r = _r(repo_root)
    reads, writes = r.split_patterns(WORKLOAD["patterns"])
    assert [p["name"] for p in reads] == ["get_order", "by_status"]
    assert [p["name"] for p in writes] == ["update_total"]


def test_build_matrix_puts_reads_and_writes_in_one_consistent_unit(repo_root: Path):
    """Reads (logical reads) and writes (redo) are NOT the same unit — the matrix must be
    built in one unit (elapsed us) so a write row can be compared against a read row."""
    r = _r(repo_root)
    meas = {                              # {pattern: {shape: elapsed_us}}
        "get_order":    {"relational": 11, "document": 5},
        "by_status":    {"relational": 23, "document": 1048},
        "update_total": {"relational": 4,  "document": 53},
    }
    result = r.build_result(WORKLOAD["model"], WORKLOAD["patterns"], meas)

    # the full matrix: every pattern a row, every design a column, every cell measured
    rows = {row["pattern"]: row for row in result["matrix"]}
    assert set(rows) == {"get_order", "by_status", "update_total"}
    assert rows["update_total"]["kind"] == "write"          # writes are first-class rows
    assert rows["get_order"]["rate"] == 5000
    assert rows["by_status"]["costs"]["document"] == 1048

    # the decision is driven by the rate-weighted matrix
    assert result["chosen"] == "relational", result["ranked"]
    assert result["ranked"][0][0] == "relational"


def test_the_winner_flips_with_the_mix(repo_root: Path):
    """Collapse the workload toward the id point-read and the document must win — that
    crossover is the whole thesis, so the runner reports it."""
    r = _r(repo_root)
    meas = {
        "get_order":    {"relational": 11, "document": 5},
        "by_status":    {"relational": 23, "document": 1048},
        "update_total": {"relational": 4,  "document": 53},
    }
    sweep = r.flip_sweep(WORKLOAD["model"], WORKLOAD["patterns"], meas,
                         scales=(1.0, 0.1, 0.01, 0.0))
    winners = [row["winner"] for row in sweep]
    assert winners[0] == "relational"          # the real mix
    assert winners[-1] == "document"           # a near-pure point-read workload
    assert any(row["scale"] < 1.0 for row in sweep)


def test_report_renders_the_matrix_and_the_decision(repo_root: Path):
    r = _r(repo_root)
    meas = {
        "get_order":    {"relational": 11, "document": 5},
        "by_status":    {"relational": 23, "document": 1048},
        "update_total": {"relational": 4,  "document": 53},
    }
    result = r.build_result(WORKLOAD["model"], WORKLOAD["patterns"], meas)
    text = r.format_report(result)
    for want in ("get_order", "by_status", "update_total", "relational", "document",
                 "CHOSEN", "rate"):
        assert want in text, f"report is missing {want!r}"


def test_cli_is_runnable_and_documents_the_connection(repo_root: Path):
    """`python -m tooling.optimize` must exist. The DB is already deployed, so the
    connection comes from the environment (DB_USER/DB_PASSWORD/DB_DSN) — the caller
    should not have to restate it."""
    main = (repo_root / "tooling/optimize/__main__.py")
    assert main.is_file(), "the optimizer needs a runnable entry point, like tooling.datalayer"
    src = main.read_text()
    assert "DB_DSN" in src and "DB_USER" in src


def test_default_candidates_include_duality_and_drop_sql_view(repo_root: Path):
    """The matrix compares STORAGE designs. `sql_view` is not a storage design — it is a
    read-only JSON projection over relational storage, so listing it beside `relational`
    is redundant. Duality IS a distinct design (same storage, updatable document API, and
    a different read cost), and it belongs in the default set."""
    r = _r(repo_root)
    model = r.propose_projections(WORKLOAD["model"], WORKLOAD["patterns"])
    shapes = r.candidate_shapes(model, WORKLOAD["patterns"])
    assert "duality" in shapes, "duality is a default candidate design"
    assert "sql_view" not in shapes, "sql_view is relational storage, not a design column"
    assert "relational" in shapes and "document" in shapes


def test_duality_falls_back_to_sql_view_for_what_it_cannot_express(repo_root: Path):
    """A duality view must stay updatable, so it cannot serve a GROUP BY. That must NOT
    exclude the duality design — same storage — it just reads that pattern through a
    read-only JSON view instead."""
    r = _r(repo_root)
    model = r.propose_projections(WORKLOAD["model"], WORKLOAD["patterns"])
    agg = {"name": "count_by_status", "kind": "read", "rate": 120,
           "query": {"root": "Order", "group_by": ["Order.status"],
                     "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"}]}}
    sql = r.pattern_sql(model, agg, "duality")
    assert "GROUP BY" in sql.upper()
    assert "JSON_OBJECT" in sql.upper()      # the read-only sql_view projection


def test_a_photo_finish_is_reported_as_a_photo_finish(repo_root: Path):
    """A 3% gap between two designs is measurement noise, not a decision. Printing
    `CHOSEN: duality` and nothing else invites a team to rebuild a schema on a coin flip.
    When the top two are within the noise floor, the report must say so out loud."""
    r = _r(repo_root)
    meas = {                                    # relational and document ~2% apart
        "get_order":    {"relational": 100, "document": 102},
        "by_status":    {"relational": 100, "document": 102},
        "update_total": {"relational": 100, "document": 102},
    }
    result = r.build_result(WORKLOAD["model"], WORKLOAD["patterns"], meas)
    text = r.format_report(result)
    assert "TOO CLOSE TO CALL" in text, f"a 2% margin must be flagged, not asserted:\n{text}"
    assert result["margin"] < 0.05


def test_scenario_sweep_reweights_the_same_measurements(repo_root: Path):
    """The knob is the MIX. The cells are a property of the schema and the data, not of the
    rates — so a scenario re-weights measurements already taken rather than re-running the
    database. Shift the mix and a different design separates; that is the whole thesis, and
    it must cost one measurement pass, not one per scenario."""
    r = _r(repo_root)
    meas = {
        "get_order":    {"relational": 11, "document": 5},
        "by_status":    {"relational": 23, "document": 1048},
        "update_total": {"relational": 4,  "document": 53},
    }
    scenarios = [
        {"name": "write-heavy", "rates": {"get_order": 100, "update_total": 5000}},
        {"name": "point-read only", "rates": {"get_order": 5000}},
    ]
    rows = r.scenario_sweep(WORKLOAD["model"], WORKLOAD["patterns"], meas, scenarios)
    by = {row["name"]: row for row in rows}
    assert by["write-heavy"]["winner"] == "relational"
    assert by["point-read only"]["winner"] == "document"      # the mix flipped the winner
    assert by["point-read only"]["margin"] > 0
    # a scenario reports its own read:write ratio, so "reads dominate" is visible, not implied
    assert by["point-read only"]["read_write_ratio"] is None or \
        by["point-read only"]["read_write_ratio"] > 100

    text = r.format_report(r.build_result(WORKLOAD["model"], WORKLOAD["patterns"], meas),
                           scenarios=rows)
    assert "SHIFT THE MIX" in text and "write-heavy" in text


def test_report_renders_a_no_winner_scenario_as_too_close_to_call(repo_root: Path):
    """A scenario can honestly decide NOTHING (winner None — inside the noise
    floor, or no viable design). That verdict crashed format_report with a
    TypeError AFTER the measurement had been paid for (hotel capstone). The
    honest outcome must render, not raise."""
    r = _r(repo_root)
    meas = {
        "get_order": {"relational": 100.0, "document": 100.0},
        "by_status": {"relational": 100.0, "document": 100.0},
        "update_total": {"relational": 100.0, "document": 100.0},
    }
    result = r.build_result(WORKLOAD["model"], WORKLOAD["patterns"], meas)
    scenarios = [{"name": "dead_heat", "note": "", "ranked": result["ranked"],
                  "winner": None, "margin": None, "separates": False,
                  "read_write_ratio": 3.0}]
    text = r.format_report(result, scenarios=scenarios)
    assert "TOO CLOSE TO CALL" in text, text


def test_excluded_designs_are_disclosed_with_the_pattern_that_disqualified_them(repo_root: Path):
    """A missing cell excludes the DESIGN from the entire decision — which
    silently turned a 4-design benchmark into a 3-design one on the hotel
    capstone. No silent caps: the decision must name what was excluded and
    which pattern disqualified it."""
    r = _r(repo_root)
    meas = {
        "get_order": {"relational": 100.0, "document": 90.0},
        "by_status": {"relational": 100.0, "document": 90.0},
        "update_total": {"relational": 100.0},          # document cell MISSING
    }
    result = r.build_result(WORKLOAD["model"], WORKLOAD["patterns"], meas)
    assert result["excluded"] == {"document": ["update_total"]}, result["excluded"]
    text = r.format_report(result)
    assert "EXCLUDED FROM THE DECISION" in text, text
    assert "document" in text and "update_total" in text

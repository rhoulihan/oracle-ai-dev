# Copyright (c) 2026 Oracle and/or its affiliates.
"""The cost matrix FUELS the model decision. decide_model consumes the matrix —
reads and writes as first-class rows — and mechanically elects the design. Three
scenarios, each tipping to a different design purely from its matrix."""
from tooling.optimize.decide import decide_model

# Cost matrix cells measured live on 26ai (logical reads; writes as block work).
# design -> cost per (pattern, design). A missing cell = the design can't serve the
# pattern (e.g. a document store can't GROUP BY) -> that design is not viable.

def test_scenario_A_reads_only_elects_document():
    patterns = {"point_read":      {"kind": "read", "rate": 900},
                "item_collection": {"kind": "read", "rate": 100}}
    cost = {"point_read":      {"single_table": 3, "relational": 3, "document": 3},
            "item_collection": {"single_table": 4, "relational": 6, "document": 3}}
    d = decide_model(patterns, cost)
    assert d["chosen"] == "document"       # pre-assembled aggregate, no writes to amplify


def test_scenario_B_aggregation_and_writes_elects_relational():
    patterns = {"aggregation": {"kind": "read", "rate": 300},
                "write_item":  {"kind": "write", "rate": 400},
                "point_read":  {"kind": "read", "rate": 300}}
    # document has NO aggregation cell -> not viable for this workload
    cost = {"aggregation": {"single_table": 42, "relational": 40},
            "write_item":  {"single_table": 12, "relational": 12, "document": 12},
            "point_read":  {"single_table": 3, "relational": 3, "document": 3}}
    d = decide_model(patterns, cost)
    assert d["chosen"] == "relational"
    assert "document" not in [x[0] for x in d["ranked"]]   # excluded: can't aggregate


def test_scenario_C_multi_anchor_writes_elect_single_table():
    patterns = {"multi_anchor_read": {"kind": "read", "rate": 700},
                "write_multianchor": {"kind": "write", "rate": 300}}
    # a write touches every collection the datum is duplicated into: document = 3 copies
    cost = {"multi_anchor_read": {"single_table": 4, "relational": 6, "document": 3},
            "write_multianchor": {"single_table": 12, "relational": 12, "document": 36}}
    d = decide_model(patterns, cost)
    assert d["chosen"] == "single_table"   # doc amplifies writes 3x; relational joins reads


def test_reports_read_write_split_and_drivers():
    patterns = {"r": {"kind": "read", "rate": 100}, "w": {"kind": "write", "rate": 50}}
    cost = {"r": {"relational": 3, "document": 2}, "w": {"relational": 10, "document": 40}}
    d = decide_model(patterns, cost)
    assert set(d["read_cost"]) >= set()   # keys exist
    assert d["read_cost"][d["chosen"]] >= 0 and d["write_cost"][d["chosen"]] >= 0
    assert d["drivers"]                    # which patterns drive the pick


def test_consolidation_walk_moves_with_write_frequency():
    # as writes get heavier, the winner walks from the denormalized doc toward the
    # write-cheap design — the measured knob.
    patterns = {"read": {"kind": "read", "rate": 100}, "write": {"kind": "write", "rate": 1}}
    cost = {"read":  {"document": 2, "relational": 6},
            "write": {"document": 40, "relational": 10}}
    d = decide_model(patterns, cost)
    walk = d["walk"]   # [(write_scale, chosen), ...]
    winners = {chosen for _, chosen in walk}
    assert "document" in winners and "relational" in winners   # flips across the sweep

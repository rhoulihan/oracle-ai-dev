# Copyright (c) 2026 Oracle and/or its affiliates.
"""A re-runnable shape comparison: change the model (add a shape/index/projection),
re-run, see the updated per-pattern winners and union optimum."""
from tooling.optimize.compare import compare

MODEL = {
    "entities": {"Order": {"table": "orders", "pk": "order_id",
                 "columns": {"total": "total", "status": "status"}}},
    "relationships": [],
    "projections": {"document": {"Order": {"collection": "order_docs"}},
                    "duality": {"Order": "order_dv"}},
}
PATTERNS = {
    "get_order": {"read_rate": 1000, "write_rate": 0,
        "query": {"root": "Order", "returns": ["Order.total"],
                  "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}},
    "update_order": {"read_rate": 0, "write_rate": 200,
        "query": {"root": "Order", "returns": ["Order.total"],
                  "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}},
}
READ = {"get_order": {"relational": 10, "document": 3, "duality": 10},
        "update_order": {"relational": 10, "document": 3, "duality": 10}}
WRITE = {"get_order": {"relational": 5, "document": 40, "duality": 5},
         "update_order": {"relational": 5, "document": 40, "duality": 5}}


def test_per_pattern_winners_and_union():
    r = compare(MODEL, PATTERNS, READ, WRITE)
    assert r["per_pattern"]["get_order"]["winner"] == "document"   # read-heavy -> doc
    assert r["per_pattern"]["update_order"]["winner"] in ("relational", "duality")  # write -> cheap write
    assert r["union"]["chosen"]["model"] in ("relational", "duality", "document")


def test_available_shapes_reflect_the_model():
    r = compare(MODEL, PATTERNS, READ, WRITE)
    avail = r["per_pattern"]["get_order"]["available_shapes"]
    assert "relational" in avail and "document" in avail and "duality" in avail
    assert "single_table" not in avail   # model has no single_table projection


def test_adding_a_projection_changes_the_candidate_set_on_rerun():
    # user "implements a model change": add a single_table projection, re-run
    changed = {**MODEL, "projections": {**MODEL["projections"],
               "single_table": {"table": "t", "discriminator": "type",
                                "types": {"order": {"key": ["order_id"]}}, "indexes": []}}}
    r = compare(changed, PATTERNS, READ, WRITE)
    assert "single_table" in r["per_pattern"]["get_order"]["available_shapes"]


def test_an_unmeasured_shape_never_wins_the_per_pattern_ranking():
    """A missing measurement cell is 'this design was never measured', not 'this
    design is free'. A shape with no read cell must not win a read-heavy pattern."""
    patterns = {"get_order": {"read_rate": 1000, "write_rate": 0,
                              "query": PATTERNS["get_order"]["query"]}}
    read = {"get_order": {"relational": 10}}                       # document never read-measured
    write = {"get_order": {"relational": 5, "document": 40}}
    r = compare(MODEL, patterns, read, write)
    pp = r["per_pattern"]["get_order"]
    assert pp["winner"] == "relational", pp
    assert "document" not in pp["costs"]           # incomparable, not zero-cost
    assert "document" in pp.get("unmeasured", []), pp


def test_union_never_fabricates_a_write_cost_from_a_read_cost():
    """A write-amplified shape whose write was never measured must not win the union
    priced at its (cheap) READ cost — it is incomparable for that pattern, and the
    result must say so."""
    patterns = {"upd": {"read_rate": 1, "write_rate": 1000,
                        "query": PATTERNS["update_order"]["query"]}}
    read = {"upd": {"relational": 10, "document": 3}}
    write = {"upd": {"relational": 5}}                 # document write never measured
    r = compare(MODEL, patterns, read, write)
    assert r["union"] is not None
    assert r["union"]["chosen"]["model"] == "relational", r["union"]
    ranked = {d["model"] for d in r["union"]["ranked"]}
    assert "document" not in ranked
    assert any("document" in n for n in r["notes"]), r["notes"]


def test_writes_are_first_class_rows():
    r = compare(MODEL, PATTERNS, READ, WRITE)
    kinds = {(row["pattern"], row["kind"]) for row in r["rows"]}
    # get_order is read-only -> a read row; update_order is write-only -> a write row
    assert ("get_order#read", "read") in kinds
    assert ("update_order#write", "write") in kinds
    # the matrix drives a decision
    assert r["decision"] is not None and r["decision"]["chosen"] in ("relational", "duality", "document")

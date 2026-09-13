import sys
from pathlib import Path


def _rec(repo_root: Path, ap, entities):
    sys.path.insert(0, str(repo_root))
    from tooling.recommend.shapes import recommend_shape
    return recommend_shape(ap, entities)


def test_write_hot_pattern_avoids_duality(repo_root: Path):
    ap = {"name": "add_to_cart", "returns": ["Cart.items"], "frequency": 5000,
          "cardinality": "1:N", "latency_budget_ms": 20, "write": "high"}
    r = _rec(repo_root, ap, ["Cart"])
    assert r["strategy"] == "single_collection_multivalue"
    assert "write" in r["rationale"].lower()


def test_dual_consumer_readmostly_gets_duality(repo_root: Path):
    ap = {"name": "order_report", "returns": ["Order.total", "Customer.name"],
          "frequency": 200, "cardinality": "N:1", "latency_budget_ms": 200, "write": "low"}
    r = _rec(repo_root, ap, ["Order", "Customer"])
    assert r["strategy"] == "relational_duality"


def test_single_entity_bounded_gets_json_collection(repo_root: Path):
    ap = {"name": "get_profile", "returns": ["User.prefs"], "frequency": 800,
          "cardinality": "1:1", "latency_budget_ms": 30, "write": "medium"}
    r = _rec(repo_root, ap, ["User"])
    assert r["strategy"] == "json_collection"


def test_result_cites_a_umt_rule(repo_root: Path):
    ap = {"name": "x", "returns": ["A.b"], "frequency": 1, "cardinality": "1:1",
          "latency_budget_ms": 100, "write": "low"}
    assert _rec(repo_root, ap, ["A"])["umt_rule"]


def test_write_hot_multi_entity_flags_ownership_ambiguity(repo_root: Path):
    # write-hot + two independent entities: single-collection is only right if the
    # extra entity is an owned/bounded child. UMT says shared/independent entities
    # must be REFERENCED. The recommendation must flag this, not silently collapse.
    ap = {"name": "order_and_stock", "returns": ["Order.total", "InventoryStock.qty"],
          "frequency": 3000, "cardinality": "N:M", "latency_budget_ms": 20, "write": "high"}
    r = _rec(repo_root, ap, ["Order", "InventoryStock"])
    text = (r["rationale"] + " " + r["umt_rule"]).lower()
    assert "owned" in text or "confirm" in text or "hybrid" in text, \
        "multi-entity write-hot must flag the ownership/hybrid caveat"

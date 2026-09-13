import sys
from pathlib import Path


def _mod(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.model as m
    return m


MODEL = {
    "entities": {
        "Order": {"table": "orders", "pk": "order_id",
                  "columns": {"total": "total", "orderId": "order_id"}},
        "OrderItem": {"table": "order_item", "pk": "order_item_id",
                      "columns": {"quantity": "quantity"}},
        "Restaurant": {"table": "restaurant", "pk": "restaurant_id",
                       "columns": {"name": "name"}},
    },
    "relationships": [
        {"from": "Order", "to": "OrderItem", "from_key": "order_id", "to_key": "order_id", "cardinality": "1:N"},
        {"from": "Order", "to": "Restaurant", "from_key": "restaurant_id", "to_key": "restaurant_id", "cardinality": "N:1"},
    ],
    "projections": {
        "duality": {"Order": "order_dv"},
        "document": {"Order": {"collection": "order_docs", "id_path": "$._id"}},
    },
}

QUERY = {
    "root": "Order",
    "returns": ["Order.total", "Restaurant.name", "OrderItem.quantity"],
    "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}],
}


def test_valid_model_and_query_pass(repo_root: Path):
    m = _mod(repo_root)
    assert m.validate_model(MODEL) == []
    assert m.validate_query(QUERY, MODEL) == []


def test_relationship_to_unknown_entity_flagged(repo_root: Path):
    m = _mod(repo_root)
    bad = {**MODEL, "relationships": MODEL["relationships"] + [
        {"from": "Order", "to": "Ghost", "from_key": "x", "to_key": "y", "cardinality": "1:N"}]}
    assert any("Ghost" in msg for msg in m.validate_model(bad))


def test_return_referencing_unknown_property_flagged(repo_root: Path):
    m = _mod(repo_root)
    bad = {**QUERY, "returns": ["Order.total", "Restaurant.zipcode"]}
    assert any("Restaurant.zipcode" in msg for msg in m.validate_query(bad, MODEL))


def test_predicate_ref_not_in_model_flagged(repo_root: Path):
    m = _mod(repo_root)
    bad = {**QUERY, "predicates": [{"ref": "Ghost.id", "op": "=", "value": 1}]}
    assert any("Ghost.id" in msg for msg in m.validate_query(bad, MODEL))


def test_unknown_root_flagged(repo_root: Path):
    m = _mod(repo_root)
    bad = {**QUERY, "root": "Ghost"}
    assert any("root" in msg.lower() for msg in m.validate_query(bad, MODEL))


def test_duality_supports_true_by_default(repo_root: Path):
    m = _mod(repo_root)
    assert m.duality_supports(QUERY) is True


def test_duality_unsupported_when_query_needs_coalesce(repo_root: Path):
    m = _mod(repo_root)
    q = {**QUERY, "requires_ops": ["coalesce"]}
    assert m.duality_supports(q) is False


def test_duality_unsupported_for_aggregation(repo_root: Path):
    m = _mod(repo_root)
    q = {**QUERY, "requires_ops": ["group_by"]}
    assert m.duality_supports(q) is False

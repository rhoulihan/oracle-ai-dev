import sys
from pathlib import Path

from test_generate_model import MODEL, QUERY  # reuse the restaurant fixtures


def _sql(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    return s


def test_relational_generates_joins_and_projection(repo_root: Path):
    out = _sql(repo_root).generate_relational(MODEL, QUERY).lower()
    assert "from orders" in out
    assert "join restaurant" in out
    assert "join order_item" in out
    # projected columns (mapped from entity.property)
    assert "total" in out and "name" in out and "quantity" in out
    # predicate
    assert "where" in out and "order_id" in out and "1000" in out


def test_relational_join_uses_declared_keys(repo_root: Path):
    out = _sql(repo_root).generate_relational(MODEL, QUERY).lower()
    # Order.restaurant_id = Restaurant.restaurant_id
    assert "restaurant_id" in out
    # Order.order_id = OrderItem.order_id
    assert out.count("order_id") >= 2


def test_unreachable_entity_raises(repo_root: Path):
    s = _sql(repo_root)
    import pytest
    # A model with no relationship to Restaurant makes it unreachable from root.
    m = {**MODEL, "relationships": [r for r in MODEL["relationships"] if r["to"] != "Restaurant"]}
    with pytest.raises(ValueError):
        s.generate_relational(m, QUERY)


def test_invalid_spec_raises_value_error(repo_root: Path):
    s = _sql(repo_root)
    import pytest
    with pytest.raises(ValueError):
        s.generate_relational(MODEL, {**QUERY, "root": "Ghost"})


def test_multi_hop_joins_intermediate_entities(repo_root: Path):
    # Customer -> Order -> OrderItem; root=Customer, returns Customer.name +
    # OrderItem.quantity. Order is an intermediate NOT in the returns, but must
    # still be JOINed or the SQL references an unjoined alias.
    s = _sql(repo_root)
    m = {
        "entities": {
            "Customer": {"table": "customer", "pk": "customer_id", "columns": {"name": "name"}},
            "Order": {"table": "orders", "pk": "order_id", "columns": {}},
            "OrderItem": {"table": "order_item", "pk": "order_item_id", "columns": {"quantity": "quantity"}},
        },
        "relationships": [
            {"from": "Customer", "to": "Order", "from_key": "customer_id", "to_key": "customer_id", "cardinality": "1:N"},
            {"from": "Order", "to": "OrderItem", "from_key": "order_id", "to_key": "order_id", "cardinality": "1:N"},
        ],
    }
    q = {"root": "Customer", "returns": ["Customer.name", "OrderItem.quantity"], "predicates": []}
    out = s.generate_relational(m, q).lower()
    assert "join orders" in out, "intermediate Order table must be joined"
    # no alias is referenced without being introduced
    assert "from customer" in out and "join order_item" in out

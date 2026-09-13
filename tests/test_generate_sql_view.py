import json
import sys
from pathlib import Path

import pytest


def _load(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())
    return s, model


GET_ORDER = {
    "root": "Order",
    "returns": ["Order.total", "Restaurant.name", "OrderItem.quantity"],
    "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}],
}
GET_ORDER_COALESCE = {**GET_ORDER, "requires_ops": ["coalesce"]}


def test_sql_view_wraps_projection_in_json_object(repo_root: Path):
    s, model = _load(repo_root)
    out = s.generate_sql_view(model, GET_ORDER).lower()
    assert "json_object" in out  # returns a document shape
    assert "from orders" in out


def test_candidates_include_sql_view_and_drop_duality_when_unsupported(repo_root: Path):
    s, model = _load(repo_root)
    cands = s.generate_candidates(model, GET_ORDER_COALESCE)
    assert "sql_view" in cands
    assert "duality" not in cands  # duality can't express COALESCE


def test_candidates_include_duality_not_sql_view_for_normal_query(repo_root: Path):
    s, model = _load(repo_root)
    cands = s.generate_candidates(model, GET_ORDER)
    assert "duality" in cands
    assert "sql_view" not in cands


def test_update_via_sql_view_is_rejected(repo_root: Path):
    s, model = _load(repo_root)
    with pytest.raises(ValueError):
        s.generate_update(model, GET_ORDER, "sql_view", set_ref="OrderItem.quantity", delta=1)

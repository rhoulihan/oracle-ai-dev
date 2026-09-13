import json
import sys
from pathlib import Path

import pytest


def _load(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())
    return s, model


Q = {"root": "Order", "returns": ["OrderItem.quantity"],
     "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}]}
ELEM = {"menu_item_id": 20, "quantity": 1}


def test_relational_array_append_inserts_child_row(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_array_append(m, Q, "relational", "$.items", ELEM).lower()
    assert "insert into order_item" in out


def test_document_array_append_uses_json_transform_append(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_array_append(m, Q, "document", "$.items", ELEM).lower()
    assert "json_transform" in out and "append '$.items'" in out


def test_duality_array_append_targets_view(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_array_append(m, Q, "duality", "$.items", ELEM).lower()
    assert "update order_dv" in out


def test_sql_view_append_rejected(repo_root: Path):
    s, m = _load(repo_root)
    with pytest.raises(ValueError):
        s.generate_array_append(m, Q, "sql_view", "$.items", ELEM)


def test_multi_field_update_sets_multiple_columns(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_multi_field_update(
        m, Q, "relational",
        [{"ref": "Order.total", "expr": "total + 1"}, {"ref": "Order.orderedAt", "expr": "SYSTIMESTAMP"}]).lower()
    assert "set total = total + 1" in out and "ordered_at = systimestamp" in out


def test_multi_field_update_document_single_transform(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_multi_field_update(
        m, Q, "document",
        [{"path": "$.total", "expr": "42"}, {"path": "$.tip", "expr": "5"}]).lower()
    assert out.count("json_transform") == 1
    assert "set '$.total'" in out and "set '$.tip'" in out

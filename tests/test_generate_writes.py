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
    "returns": ["Order.total", "OrderItem.quantity"],
    "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}],
}


def test_relational_update_touches_child_row(repo_root: Path):
    s, model = _load(repo_root)
    out = s.generate_update(model, GET_ORDER, "relational",
                            set_ref="OrderItem.quantity", delta=1).lower()
    assert "update order_item" in out
    assert "quantity" in out
    assert "order_id" in out  # scoped to the order (one row)


def test_document_update_rewrites_whole_doc(repo_root: Path):
    s, model = _load(repo_root)
    out = s.generate_update(model, GET_ORDER, "document",
                            set_ref="OrderItem.quantity", delta=1).lower()
    assert "update order_docs" in out
    assert "json_transform" in out  # whole-document rewrite = amplification


def test_document_update_path_derives_from_set_ref(repo_root: Path):
    """The JSON_TRANSFORM path must come from set_ref. Hardcode it and the document
    write silently mutates the wrong field for every other set_ref while relational
    and duality update the right one."""
    s, model = _load(repo_root)
    qty = s.generate_update(model, GET_ORDER, "document", set_ref="OrderItem.quantity", delta=1)
    price = s.generate_update(model, GET_ORDER, "document", set_ref="OrderItem.unitPrice", delta=1)
    total = s.generate_update(model, GET_ORDER, "document", set_ref="Order.total", delta=1)
    assert "'$.orderitems[0].quantity'" in qty, qty
    assert "'$.orderitems[0].unitPrice'" in price, price
    assert "'$.total'" in total, total
    assert len({qty, price, total}) == 3, "different set_refs must write different fields"


def test_duality_update_targets_view(repo_root: Path):
    s, model = _load(repo_root)
    out = s.generate_update(model, GET_ORDER, "duality",
                            set_ref="OrderItem.quantity", delta=1).lower()
    assert "update order_dv" in out


def test_unknown_shape_raises(repo_root: Path):
    s, model = _load(repo_root)
    with pytest.raises(ValueError):
        s.generate_update(model, GET_ORDER, "columnar", set_ref="OrderItem.quantity", delta=1)


def test_update_a_column_on_the_root_entity(repo_root):
    """A counter/status update on the root itself (not a child) — generate_update assumed
    the target was a 1:N child, so it raised. Scope by the root PK instead."""
    import sys; sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import generate_update
    model = {"entities": {"Order": {"table": "orders", "pk": "order_id",
                                    "columns": {"views": "views"}}},
             "relationships": [], "projections": {}}
    q = {"root": "Order", "returns": ["Order.views"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 7}]}
    sql = generate_update(model, q, "relational", "Order.views", delta=1).lower()
    assert "update orders" in sql
    assert "views = views + 1" in sql
    assert "order_id = 7" in sql          # scoped by the ROOT pk, not a child fk

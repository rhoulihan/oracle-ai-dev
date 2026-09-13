import sys
from pathlib import Path

import pytest

from test_generate_model import MODEL


def _sql(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    return s


def _rel(repo_root, preds):
    q = {"root": "Order", "returns": ["Order.total"], "predicates": preds}
    return _sql(repo_root).generate_relational(MODEL, q).lower()


def test_comparison_operators(repo_root: Path):
    out = _rel(repo_root, [{"ref": "Order.total", "op": ">=", "value": 20}])
    assert "total >= 20" in out


def test_not_equal(repo_root: Path):
    out = _rel(repo_root, [{"ref": "Order.total", "op": "!=", "value": 0}])
    assert "total != 0" in out or "total <> 0" in out


def test_in_list(repo_root: Path):
    out = _rel(repo_root, [{"ref": "Order.orderId", "op": "IN", "value": [1000, 1001]}])
    assert "order_id in (1000, 1001)" in out


def test_between(repo_root: Path):
    out = _rel(repo_root, [{"ref": "Order.total", "op": "BETWEEN", "value": [10, 40]}])
    assert "total between 10 and 40" in out


def test_is_null(repo_root: Path):
    out = _rel(repo_root, [{"ref": "Order.total", "op": "IS NULL", "value": None}])
    assert "total is null" in out


def test_like(repo_root: Path):
    out = _rel(repo_root, [{"ref": "Restaurant.name", "op": "LIKE", "value": "Trat%"}])
    assert "like 'trat%'" in out


def test_unknown_operator_raises(repo_root: Path):
    with pytest.raises(ValueError):
        _rel(repo_root, [{"ref": "Order.total", "op": "SOUNDSLIKE", "value": 1}])


def test_document_scalar_filter_uses_the_indexable_form(repo_root: Path):
    """Was `assert "json_exists" in out` — which encoded a bug: a JSON_EXISTS
    path predicate cannot use an index and every filtered read full-scanned.
    The indexable scalar form is now PLAIN DOT (dot-notation-first): served by
    the typed multivalue index — the same one the Mongo lane uses."""
    s = _sql(repo_root)
    q = {"root": "Order", "returns": ["Order.total"],
         "predicates": [{"ref": "Order.total", "op": ">=", "value": 20}]}
    out = s.generate_document(MODEL, q).lower()
    assert "d.data.total >= 20" in out, out
    assert "json_exists" not in out and "json_value" not in out


def test_json_exists_is_still_right_for_key_presence(repo_root: Path):
    """IS [NOT] NULL asks whether the KEY exists, not what the value compares to — there
    JSON_EXISTS is the correct tool, and there is no index to miss."""
    s = _sql(repo_root)
    q = {"root": "Order", "returns": ["Order.total"],
         "predicates": [{"ref": "Order.total", "op": "IS NULL"}]}
    assert "not json_exists" in s.generate_document(MODEL, q).lower()

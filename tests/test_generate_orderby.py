import json
import sys
from pathlib import Path


def _load(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    return s, json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())


BASE = {"root": "Order", "returns": ["Order.total"],
        "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}]}


def test_order_by_desc_before_fetch(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_relational(m, {**BASE, "order_by": [{"ref": "Order.total", "dir": "DESC"}], "limit": 5}).lower()
    assert "order by order_t.total desc" in out
    assert out.index("order by") < out.index("fetch first")


def test_order_by_default_asc(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_relational(m, {**BASE, "order_by": [{"ref": "Order.total"}]}).lower()
    assert "order by order_t.total asc" in out


def test_order_by_in_sql_view(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_sql_view(m, {**BASE, "order_by": [{"ref": "Order.total", "dir": "DESC"}]}).lower()
    assert "order by order_t.total desc" in out

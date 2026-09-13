import json
import sys
from pathlib import Path

import pytest


def _load(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())
    return s, model


BASE = {"root": "Order", "returns": ["Order.total"],
        "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}]}
COMPUTED = {**BASE, "computed": [{"name": "label", "expr": "COALESCE(restaurant.name, 'Unknown')"}]}


def test_computed_appears_in_relational_select(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_relational(m, COMPUTED).lower()
    assert "coalesce(restaurant.name" in out
    assert "as label" in out
    # The expression references the `restaurant` alias, so Restaurant must be JOINed —
    # appended to the SELECT without the join, the alias is undeclared and the query
    # dies with ORA-00904 at execution (the substring asserts above passed over it).
    assert "join restaurant restaurant on order_t.restaurant_id = restaurant.restaurant_id" \
        in out, out


def test_computed_forces_the_join_in_sql_view_too(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_sql_view(m, COMPUTED).lower()
    assert "join restaurant restaurant" in out, out


def test_computed_on_the_root_alone_adds_no_join(repo_root: Path):
    s, m = _load(repo_root)
    q = {**BASE, "computed": [{"name": "t2", "expr": "order_t.total * 2"}]}
    out = s.generate_relational(m, q).lower()
    assert "join" not in out, out


def test_computed_forces_sql_view_not_duality(repo_root: Path):
    s, m = _load(repo_root)
    cands = s.generate_candidates(m, COMPUTED)
    assert "sql_view" in cands and "duality" not in cands


def test_computed_wrapped_in_json_object_in_sql_view(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_sql_view(m, COMPUTED).lower()
    assert "json_object" in out
    assert "'label' value coalesce(restaurant.name" in out


def test_limit_emits_fetch_first(repo_root: Path):
    s, m = _load(repo_root)
    out = s.generate_relational(m, {**BASE, "limit": 5}).lower()
    assert "fetch first 5 rows only" in out


def test_computed_expr_with_semicolon_rejected(repo_root: Path):
    s, m = _load(repo_root)
    bad = {**BASE, "computed": [{"name": "x", "expr": "1; DROP TABLE orders"}]}
    with pytest.raises(ValueError):
        s.generate_relational(m, bad)

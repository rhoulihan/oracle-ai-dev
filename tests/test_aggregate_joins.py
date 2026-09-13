# Copyright (c) 2026 Oracle and/or its affiliates.
"""A GROUP BY key, an aggregate argument, or an ORDER BY can live on a NON-ROOT entity.

The canonical KPI — "revenue by restaurant" rooted at Order — groups by Restaurant.name.
Join derivation used to look only at returns + predicates, so the generated SQL referenced
the `restaurant` alias without ever introducing it: ORA-00904 at execution, for both the
relational candidate and the sql_view candidate aggregations are routed to. The covering
index derivation had the same blind spot the other way round: it built the parent's column
into an index ON the root's table, where that column does not exist.
"""
import json
import sys
from pathlib import Path


def _load(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    from tooling.generate.ddl import generate_indexes
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())
    return s, generate_indexes, model


KPI = {"root": "Order", "group_by": ["Restaurant.name"],
       "aggregates": [{"fn": "SUM", "ref": "Order.total", "name": "revenue"}]}


def test_group_by_on_a_parent_entity_joins_it(repo_root: Path):
    s, _, m = _load(repo_root)
    sql = s.generate_relational(m, KPI).lower()
    assert "join restaurant" in sql, f"GROUP BY references an alias never joined:\n{sql}"


def test_sql_view_aggregate_joins_the_group_by_entity(repo_root: Path):
    """generate_candidates routes aggregations to sql_view, so this is the shape that runs."""
    s, _, m = _load(repo_root)
    sql = s.generate_sql_view(m, KPI).lower()
    assert "join restaurant" in sql, f"GROUP BY references an alias never joined:\n{sql}"


def test_aggregate_argument_on_a_non_root_entity_joins_it(repo_root: Path):
    s, _, m = _load(repo_root)
    q = {"root": "Order", "group_by": ["Order.total"],
         "aggregates": [{"fn": "SUM", "ref": "OrderItem.quantity", "name": "qty"}]}
    sql = s.generate_relational(m, q).lower()
    assert "join order_item" in sql, f"aggregate argument's entity never joined:\n{sql}"


def test_order_by_on_a_non_returned_entity_joins_it(repo_root: Path):
    s, _, m = _load(repo_root)
    q = {"root": "Order", "returns": ["Order.total"],
         "order_by": [{"ref": "Restaurant.name", "dir": "DESC"}]}
    sql = s.generate_relational(m, q).lower()
    assert "join restaurant" in sql, f"ORDER BY references an alias never joined:\n{sql}"
    assert "order by restaurant.name desc" in sql


def test_agg_index_skips_columns_from_other_tables(repo_root: Path):
    """The covering index is built ON the root's table; a non-root GROUP BY key's column
    does not exist there, so the CREATE would raise ORA-00904. Cover what is coverable."""
    _, gi, m = _load(repo_root)
    idx = gi(m, [KPI], shape="relational")
    assert "ON orders (name" not in idx, f"parent's column indexed on the root's table:\n{idx}"
    assert "(total, 0)" in idx, idx

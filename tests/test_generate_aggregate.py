# Copyright (c) 2026 Oracle and/or its affiliates.
"""GROUP BY / aggregation as a first-class access-pattern class.

The KPI + reporting patterns are aggregations, and they are exactly what anchors the
converged model: a document CAN aggregate on Oracle (SQL/JSON over the collection) but
must full-scan to do it, while a duality view cannot express it at all. If the generator
can't emit these, the optimizer can't reason about the pattern class that decides the
architecture.
"""
import sys
from pathlib import Path

import pytest

MODEL = {
    "entities": {"Order": {"table": "orders", "pk": "order_id",
                           "columns": {"status": "status", "total": "total"}}},
    "relationships": [],
    "projections": {"document": {"Order": {"collection": "order_docs", "id_path": "$._id"}},
                    "duality": {"Order": "order_dv"}},
}
AGG = {
    "root": "Order",
    "group_by": ["Order.status"],
    "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"},
                   {"fn": "SUM", "ref": "Order.total", "name": "revenue"}],
}


def _s(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    return s


def test_relational_group_by(repo_root: Path):
    sql = _s(repo_root).generate_relational(MODEL, AGG).lower()
    assert "count(*) as n" in sql
    assert "sum(" in sql and "as revenue" in sql
    assert "group by" in sql and "status" in sql


def test_document_aggregates_over_the_collection(repo_root: Path):
    """A document CAN aggregate, and — contrary to what this test used to assert — it can do
    it ON AN ACCESS PATH. It full-scanned because we never derived an index from the GROUP BY
    key, not because no such path exists. With one: 15,479us/3,359 reads -> 1,789us/102 reads,
    fewer logical reads than the relational table itself."""
    sql = _s(repo_root).generate_document(MODEL, AGG)
    up = sql.upper()
    assert "GROUP BY" in up and "COUNT(*)" in up
    assert "d.data.status.string()" in sql      # the form the derived index carries
    assert "order_docs" in sql


def test_duality_cannot_aggregate_so_candidates_route_to_sql_view(repo_root: Path):
    """A duality view can't express an aggregation — it must stay updatable. The
    candidate set must offer sql_view instead, not a duality view that would be wrong."""
    cands = _s(repo_root).generate_candidates(MODEL, AGG)
    assert "duality" not in cands, "a duality view cannot serve a GROUP BY"
    assert "sql_view" in cands
    assert "relational" in cands and "document" in cands


def test_aggregate_function_is_whitelisted(repo_root: Path):
    s = _s(repo_root)
    bad = dict(AGG, aggregates=[{"fn": "COUNT(*) FROM dual; DROP TABLE x --", "ref": "*", "name": "n"}])
    with pytest.raises(ValueError):
        s.generate_relational(MODEL, bad)


def test_validate_query_checks_group_by_refs(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.model import validate_query
    bad = dict(AGG, group_by=["Order.nope"])
    assert any("nope" in v for v in validate_query(bad, MODEL))


def test_document_aggregate_is_typed_AND_indexable(repo_root: Path):
    """Typed item-method dot: `.numberOnly()` gives SUM a SQL NUMBER (preserving
    the JSON type without JSON_VALUE RETURNING — the last resort) AND is the
    exact expression the derived index carries. Type preservation was never the
    whole requirement: the expression must ALSO be the one the index is built
    on, character for character, or the index is built, valid, and ignored."""
    sql = _s(repo_root).generate_document(MODEL, AGG)
    assert "SUM(d.data.total.numberOnly())" in sql, \
        "the numeric aggregate argument must keep its type AND match the index"
    assert "d.data.status.string()" in sql, "the group key must match the index"

# Copyright (c) 2026 Oracle and/or its affiliates.
"""Parameterized (bound) SQL per shape — the basis of the generated data layer:
one query, reusable with different inputs, no inlined literals."""
import copy
import json
from pathlib import Path

from tooling.datalayer.generate import bound_sql

MODEL = json.loads(Path("tests/fixtures/restaurant_model.json").read_text())


def _q(**kw):
    base = {"root": "Order", "returns": ["Order.total"]}
    base.update(kw)
    return base


def test_relational_scalar_bind():
    sql, binds = bound_sql(MODEL, _q(predicates=[
        {"ref": "Order.order_id", "op": "=", "value": 1000}]), "relational")
    assert ":b0" in sql and "1000" not in sql
    assert [b["name"] for b in binds] == ["b0"]
    assert binds[0]["ref"] == "Order.order_id"


def test_relational_in_makes_one_bind_per_element():
    sql, binds = bound_sql(MODEL, _q(predicates=[
        {"ref": "Order.order_id", "op": "IN", "value": [1, 2, 3]}]), "relational")
    assert ":b0" in sql and ":b1" in sql and ":b2" in sql
    assert len(binds) == 3


def test_relational_between_two_binds():
    sql, binds = bound_sql(MODEL, _q(predicates=[
        {"ref": "Order.total", "op": "BETWEEN", "value": [10, 20]}]), "relational")
    assert ":b0" in sql and ":b1" in sql and "BETWEEN" in sql.upper()
    assert len(binds) == 2


def test_document_id_predicate_binds_inline():
    sql, binds = bound_sql(MODEL, _q(returns=["Order.order_id"], predicates=[
        {"ref": "Order.order_id", "op": "=", "value": 1000}]), "document")
    assert "JSON_VALUE" in sql and ":b0" in sql
    assert len(binds) == 1


def test_duality_from_target_resolves_view_from_list():
    # The optimizer writes projections.duality[root] as a LIST of views — the FROM
    # target must be the selected view's NAME, never the raw entry (a Python repr).
    m = copy.deepcopy(MODEL)
    m["projections"]["duality"]["Order"] = [
        {"view": "order_lean_dv", "includes": []},
        {"view": "order_full_dv", "includes": ["Restaurant", "OrderItem"]},
    ]
    sql, binds = bound_sql(m, _q(predicates=[
        {"ref": "Order.order_id", "op": "=", "value": 1000}]), "duality")
    assert "FROM order_lean_dv d" in sql
    assert "[{" not in sql and "'view'" not in sql
    assert [b["name"] for b in binds] == ["b0"]


def test_duality_from_target_string_projection_still_works():
    sql, _ = bound_sql(MODEL, _q(predicates=[
        {"ref": "Order.order_id", "op": "=", "value": 1000}]), "duality")
    assert "FROM order_dv d" in sql


def test_document_id_IN_binds_one_placeholder_per_element():
    """The pk fast path handed the whole Bind list to the scalar renderer, inlining a
    Python repr (`IN '[<Bind object ...>]'`) straight into the SQL."""
    sql, binds = bound_sql(MODEL, _q(returns=["Order.order_id"], predicates=[
        {"ref": "Order.order_id", "op": "IN", "value": [1, 2]}]), "document")
    assert "IN (:b0, :b1)" in sql, sql
    assert "object at" not in sql and "[" not in sql.split("IN", 1)[1].split(")")[0]
    assert len(binds) == 2


def test_document_string_pk_bind_is_not_forced_to_number():
    """RETURNING NUMBER on a VARCHAR2 pk is NULL under NULL ON ERROR — the bound point
    read matches nothing. The declared pk type decides the RETURNING clause."""
    m = {"entities": {"Airport": {"table": "airports", "pk": "code",
                                  "pk_type": "VARCHAR2(10)", "columns": {"city": "city"}}},
         "relationships": [],
         "projections": {"document": {"Airport": {"collection": "airport_docs"}}}}
    q = {"root": "Airport", "returns": ["Airport.city"],
         "predicates": [{"ref": "Airport.code", "op": "=", "value": "LAX"}]}
    sql, binds = bound_sql(m, q, "document")
    assert "JSON_VALUE(d.data, '$._id') = :b0" in sql, sql
    assert "RETURNING NUMBER" not in sql, sql


def test_document_flat_scalar_binds_on_the_dot_expression():
    # Dot notation first: a flat scalar takes a PLAIN bind on the RHS of the
    # dot expression — the form the multivalue index serves. The old
    # JSON_EXISTS(...PASSING) rendering could use none of our indexes, so the
    # bound app query full-scanned where the optimizer's literal query indexed.
    sql, binds = bound_sql(MODEL, _q(returns=["Order.order_id"], predicates=[
        {"ref": "Order.total", "op": ">", "value": 50}]), "document")
    assert "d.data.total > :b0" in sql, sql
    assert "JSON_EXISTS" not in sql and "PASSING" not in sql, sql
    assert "50" not in sql


def test_document_aggregate_emits_group_by_and_sum():
    sql, binds = bound_sql(MODEL, {
        "root": "Order",
        "group_by": ["Order.orderId"],
        "aggregates": [{"fn": "SUM", "ref": "Order.total", "name": "rev"}],
    }, "document")
    assert "GROUP BY" in sql
    assert "SUM(d.data.total.numberOnly()) AS rev" in sql, sql
    assert "SELECT d.data\n" not in sql   # a KPI must not return raw documents


def test_document_order_by_and_limit_emitted():
    sql, binds = bound_sql(MODEL, _q(order_by=[{"ref": "Order.total", "dir": "DESC"}],
                                     limit=5), "document")
    assert "ORDER BY" in sql and "DESC" in sql
    assert "FETCH FIRST 5 ROWS ONLY" in sql


def test_duality_predicate_uses_relocated_parent_path():
    # order_dv nests the N:1 Restaurant, so ORA-40609 relocates the FK from
    # $.restaurantId to $.restaurant.restaurant_id — filtering the flat path
    # silently matches zero rows.
    m = copy.deepcopy(MODEL)
    m["entities"]["Order"]["columns"]["restaurantId"] = "restaurant_id"
    sql, binds = bound_sql(m, _q(predicates=[
        {"ref": "Order.restaurantId", "op": "=", "value": 7}]), "duality")
    assert "'$.restaurant?(@.restaurant_id == $B0)'" in sql
    assert 'PASSING :b0 AS "B0"' in sql
    assert "$.restaurantId" not in sql


def test_duality_nested_path_between_uses_passing():
    m = copy.deepcopy(MODEL)
    m["entities"]["Order"]["columns"]["restaurantId"] = "restaurant_id"
    sql, binds = bound_sql(m, _q(predicates=[
        {"ref": "Order.restaurantId", "op": "BETWEEN", "value": [3, 9]}]), "duality")
    assert ("'$.restaurant?(@.restaurant_id >= $B0 && @.restaurant_id <= $B1)'"
            in sql)
    assert len(binds) == 2 and 'PASSING :b0 AS "B0", :b1 AS "B1"' in sql


def test_duality_aggregate_with_bound_predicate():
    sql, binds = bound_sql(MODEL, {
        "root": "Order",
        "group_by": ["Order.orderId"],
        "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"}],
        "predicates": [{"ref": "Order.total", "op": ">", "value": 50}],
    }, "duality")
    assert "GROUP BY" in sql and "COUNT(*) AS n" in sql
    assert "PASSING :b0" in sql and "50" not in sql

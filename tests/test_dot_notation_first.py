# Copyright (c) 2026 Oracle and/or its affiliates.
"""Dot notation first; JSON_VALUE RETURNING is a last resort.

Field-verified on 26ai + ORDS (2026-07): simple dot notation compiles to a
JSON_VALUE(... TYPE(STRICT)) recheck over the multivalue index access — the
same semantics the Mongo API uses — so a plain-dot SQL predicate and a Mongo
`find()` SHARE one multivalue index. A scalar JSON_VALUE predicate is a
different expression (full-scans against multivalue), a scalar JSON_VALUE
functional index serves only the SQL lane, and an item method ON THE PREDICATE
(`.string() =`) loses the match. So the document lane emits: plain-dot
predicates, typed-item-method MULTIVALUE indexes, and typed item methods for
aggregation/ORDER BY (which need a SQL type — preserve it without RETURNING).

The documented last resorts: `_id` point reads keep the typed JSON_VALUE + its
functional index (scalar ids, live-measured 321us; the shared-lane `_id`
evidence covers ObjectIds, not ours), and duality predicates keep their
measured forms (the base-column rewrite evidence is JSON_VALUE/JSON_EXISTS).
"""

import json
from pathlib import Path

from tooling.datalayer.generate import bound_sql
from tooling.generate.ddl import generate_indexes
from tooling.generate.sql import generate_document

MODEL = {
    "entities": {
        "Passenger": {"table": "passengers", "pk": "passenger_id",
                      "columns": {"name": "name"}},
        "Res": {"table": "reservations", "pk": "res_id",
                "columns": {"passenger_id": "passenger_id",   # FK -> NUMBER
                            "status": "status",               # VARCHAR2
                            "total": "total"}},               # NUMBER (name-inferred)
    },
    "relationships": [{"from": "Passenger", "to": "Res", "cardinality": "1:N",
                       "from_key": "passenger_id", "to_key": "passenger_id"}],
    "projections": {"document": {"Res": {"collection": "res_docs", "id_path": "$._id"}}},
}


def _q(**kw):
    base = {"root": "Res", "returns": ["Res.status"]}
    base.update(kw)
    return base


# ------------------------------------------------------------- predicates

def test_scalar_string_predicate_is_plain_dot():
    sql = generate_document(MODEL, _q(predicates=[
        {"ref": "Res.status", "op": "=", "value": "OPEN"}]))
    assert "d.data.status = 'OPEN'" in sql, sql
    assert "JSON_VALUE" not in sql and "JSON_EXISTS" not in sql, sql


def test_scalar_number_predicate_is_plain_dot():
    sql = generate_document(MODEL, _q(predicates=[
        {"ref": "Res.passenger_id", "op": "=", "value": 7}]))
    assert "d.data.passenger_id = 7" in sql, sql


def test_predicate_side_never_carries_an_item_method():
    # `.string() =` coerces with different semantics and LOSES the index match
    # — measured. Plain dot is the sweet spot on the predicate side.
    sql = generate_document(MODEL, _q(predicates=[
        {"ref": "Res.status", "op": "=", "value": "OPEN"},
        {"ref": "Res.total", "op": ">", "value": 10}]))
    assert ".string()" not in sql and ".numberOnly()" not in sql, sql
    assert "d.data.total > 10" in sql, sql


def test_in_and_between_render_lists_over_the_dot_expression():
    sql = generate_document(MODEL, _q(predicates=[
        {"ref": "Res.status", "op": "IN", "value": ["A", "B"]}]))
    assert "d.data.status IN ('A', 'B')" in sql, sql
    sql = generate_document(MODEL, _q(predicates=[
        {"ref": "Res.total", "op": "BETWEEN", "value": [1, 9]}]))
    assert "d.data.total BETWEEN 1 AND 9" in sql, sql


def test_id_point_read_stays_typed_json_value():
    # Documented last resort: scalar ids ride the typed JSON_VALUE + its
    # functional index (live-measured); the shared-lane _id evidence is
    # ObjectId-specific.
    sql = generate_document(MODEL, _q(predicates=[
        {"ref": "Res.res_id", "op": "=", "value": 7}]))
    assert "JSON_VALUE(d.data, '$._id' RETURNING NUMBER) = 7" in sql, sql


# ---------------------------------------------------------------- indexes

def test_scalar_index_is_typed_multivalue():
    idx = generate_indexes(MODEL, [_q(predicates=[
        {"ref": "Res.passenger_id", "op": "=", "value": 7}])], shape="document")
    assert "CREATE MULTIVALUE INDEX" in idx, idx
    assert "t.data.passenger_id.numberOnly()" in idx, idx
    assert "JSON_VALUE" not in idx, f"a scalar JSON_VALUE index serves only the SQL lane:\n{idx}"


def test_string_scalar_index_uses_string_item_method():
    idx = generate_indexes(MODEL, [_q(predicates=[
        {"ref": "Res.status", "op": "=", "value": "OPEN"}])], shape="document")
    assert "t.data.status.string()" in idx, idx


def test_multi_predicate_queries_make_one_multivalue_index_PER_FIELD():
    # A composite MULTIVALUE index over scalars is INVALID SQL — ORA-44981:
    # composite multivalue columns must come from a JSON_TABLE expression
    # (field-verified on the hotel capstone; it blocked the whole run). One
    # single-field index per predicate field is legal AND is the form a Mongo
    # createIndex produces, so it also serves the shared-lane story.
    idx = generate_indexes(MODEL, [_q(predicates=[
        {"ref": "Res.status", "op": "=", "value": "OPEN"},
        {"ref": "Res.total", "op": ">", "value": 10}])], shape="document")
    assert idx.count("CREATE MULTIVALUE INDEX") == 2, idx
    assert "ON res_docs t (t.data.status.string());" in idx, idx
    assert "ON res_docs t (t.data.total.numberOnly());" in idx, idx


def test_per_field_indexes_deduplicate_across_queries():
    # The same field filtered by several patterns (alone or beside others)
    # must yield ONE index: a duplicate CREATE raises ORA-01408, the runner
    # tolerates it as "already exists", and verify_indexes then reports the
    # index as never landed and aborts the run — the cascade measured live.
    qs = [_q(predicates=[{"ref": "Res.status", "op": "=", "value": "OPEN"}]),
          _q(predicates=[{"ref": "Res.status", "op": "=", "value": "VOID"},
                         {"ref": "Res.total", "op": ">", "value": 10}])]
    idx = generate_indexes(MODEL, qs, shape="document")
    assert idx.count("t.data.status.string()") == 1, idx
    assert idx.count("CREATE MULTIVALUE INDEX") == 2, idx


def test_id_index_stays_the_typed_functional_index():
    idx = generate_indexes(MODEL, [_q(predicates=[
        {"ref": "Res.res_id", "op": "=", "value": 7}])], shape="document")
    assert "JSON_VALUE(data, '$._id' RETURNING NUMBER)" in idx, idx


# ------------------------------------------------- aggregation / order by

def test_aggregation_and_its_index_share_the_item_method_expression():
    q = {"root": "Res", "group_by": ["Res.status"],
         "aggregates": [{"name": "t", "fn": "SUM", "ref": "Res.total"}]}
    sql = generate_document(MODEL, q)
    idx = generate_indexes(MODEL, [q], shape="document")
    assert "d.data.total.numberOnly()" in sql, sql
    assert "data.total.numberOnly()" in idx, idx
    assert "d.data.status.string()" in sql, sql
    assert "RETURNING" not in idx, f"JSON_VALUE RETURNING is a last resort:\n{idx}"


def test_order_by_uses_the_typed_item_method():
    sql = generate_document(MODEL, _q(order_by=[{"ref": "Res.total", "dir": "DESC"}]))
    assert "ORDER BY d.data.total.numberOnly() DESC" in sql, sql


# ------------------------------------------------------- datalayer binds

def test_bound_flat_scalar_is_dot_with_a_plain_bind():
    # The old JSON_EXISTS(...PASSING) form for a FLAT scalar could use none of
    # our indexes — the bound app query full-scanned where the optimizer's
    # literal query was indexed.
    sql, binds = bound_sql(MODEL, _q(predicates=[
        {"ref": "Res.status", "op": "=", "value": "OPEN"}]), "document")
    assert "d.data.status = :b0" in sql, sql
    assert "JSON_EXISTS" not in sql, sql
    assert [b["name"] for b in binds] == ["b0"]


def test_bound_array_containment_stays_json_exists():
    m = json.loads(json.dumps(MODEL))
    m["entities"]["Res"]["columns"]["tags"] = "tags"
    m["entities"]["Res"]["arrays"] = ["tags"]
    sql, _ = bound_sql(m, _q(predicates=[
        {"ref": "Res.tags", "op": "=", "value": "red"}]), "document")
    assert "JSON_EXISTS" in sql, sql

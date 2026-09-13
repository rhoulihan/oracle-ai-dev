# Copyright (c) 2026 Oracle and/or its affiliates.
"""The hybrid shape: a relational core + one JSON flex column per entity.

Spec: docs/specs (Phase-1, approved 2026-07-31). Verified doctrine carried
over: dot-notation-first on the flex column (plain-dot predicates, typed
item-method indexes/aggregations), one-expression-one-function through the
shared helpers, per-field MULTIVALUE only (ORA-44981), and the `JSON ...
LIMIT n` inline guarantee on the flex column so the OSON inline-to-LOB decay
hazard cannot occur by construction. Hybrid owns its own `<table>_h` lane —
sharing the entity tables would let the flex column perturb relational's row
width mid-measurement (decision D2).
"""

import json

from tooling.datalayer.generate import bound_sql
from tooling.generate.ddl import generate_ddl, generate_indexes
from tooling.generate.model import validate_model
from tooling.generate.sql import (generate_candidates, generate_hybrid,
                                  generate_insert, generate_update)

MODEL = {
    "entities": {
        "Customer": {"table": "customers", "pk": "customer_id",
                     "columns": {"name": "name"}},
        "Order": {"table": "orders", "pk": "order_id",
                  "columns": {"customer_id": "customer_id",
                              "status": "status",
                              "total": "total",
                              "gift_note": "gift_note",
                              "loyalty_points": "loyalty_points",
                              "promo_tags": "promo_tags"},
                  "column_types": {"loyalty_points": "NUMBER"},
                  "arrays": ["promo_tags"]},
    },
    "relationships": [{"from": "Customer", "to": "Order", "cardinality": "1:N",
                       "from_key": "customer_id", "to_key": "customer_id"}],
    "projections": {"hybrid": {"entities": {
        "Order": {"flex": ["gift_note", "loyalty_points", "promo_tags"]}}}},
}


def _q(**kw):
    base = {"root": "Order", "returns": ["Order.status"]}
    base.update(kw)
    return base


def _m(**overrides):
    m = json.loads(json.dumps(MODEL))
    m.update(overrides)
    return m


# ------------------------------------------------------------- validation

def test_flex_props_must_be_known_properties():
    m = _m()
    m["projections"]["hybrid"]["entities"]["Order"]["flex"] = ["nope"]
    assert any("nope" in v for v in validate_model(m)), validate_model(m)


def test_flex_may_not_take_the_pk_or_a_relationship_key():
    # The PK and the join keys serve point reads, FKs and JOINs — they must
    # stay typed columns, or the hybrid lane loses the very access paths the
    # relational core exists to keep cheap.
    m = _m()
    m["projections"]["hybrid"]["entities"]["Order"]["flex"] = ["customer_id"]
    assert validate_model(m), "a relationship key in flex must be a violation"
    m2 = _m()
    m2["projections"]["hybrid"]["entities"]["Order"]["flex"] = ["order_id"]
    assert validate_model(m2), "the pk in flex must be a violation"


def test_empty_flex_list_is_a_violation():
    m = _m()
    m["projections"]["hybrid"]["entities"]["Order"]["flex"] = []
    assert validate_model(m), "declare nothing instead of an empty flex list"


def test_unknown_entity_in_hybrid_projection_is_a_violation():
    m = _m()
    m["projections"]["hybrid"]["entities"]["Ghost"] = {"flex": ["x"]}
    assert any("Ghost" in v for v in validate_model(m))


# -------------------------------------------------------------------- DDL

def test_hybrid_ddl_owns_its_own_tables():
    ddl = generate_ddl(MODEL, "hybrid")
    assert "CREATE TABLE IF NOT EXISTS orders_h" in ddl, ddl
    assert "CREATE TABLE IF NOT EXISTS customers_h" in ddl, ddl
    # FKs stay inside the hybrid lane
    assert "REFERENCES customers_h" in ddl, ddl


def test_flex_column_carries_the_inline_limit_guarantee():
    ddl = generate_ddl(MODEL, "hybrid")
    assert "flex JSON (OBJECT LIMIT 8192)" in ddl, ddl


def test_flex_props_are_not_typed_columns():
    ddl = generate_ddl(MODEL, "hybrid")
    start = ddl.index("CREATE TABLE IF NOT EXISTS orders_h")
    orders = ddl[start:ddl.index(");", start)]
    assert "gift_note" not in orders, orders
    assert "loyalty_points" not in orders, orders
    # the core keeps its typed columns
    assert "status" in orders and "total" in orders and "customer_id" in orders


def test_entity_without_flex_gets_no_flex_column():
    ddl = generate_ddl(MODEL, "hybrid")
    start = ddl.index("customers_h")
    end = ddl.index(";", start)
    assert "flex" not in ddl[start:end], ddl[start:end]


def test_flex_limit_is_a_knob():
    assert "LIMIT 16384" in generate_ddl(MODEL, "hybrid", flex_limit=16384)
    no_limit = generate_ddl(MODEL, "hybrid", flex_limit=None)
    assert "flex JSON (OBJECT)" in no_limit and "LIMIT" not in no_limit


# ---------------------------------------------------------------- queries

def test_core_predicate_is_a_plain_column_condition():
    sql = generate_hybrid(MODEL, _q(predicates=[
        {"ref": "Order.status", "op": "=", "value": "OPEN"}]))
    assert "order_t.status = 'OPEN'" in sql, sql
    assert "FROM orders_h order_t" in sql, sql


def test_flex_scalar_predicate_is_plain_dot_on_the_flex_column():
    sql = generate_hybrid(MODEL, _q(predicates=[
        {"ref": "Order.gift_note", "op": "=", "value": "wrap"}]))
    assert "order_t.flex.gift_note = 'wrap'" in sql, sql
    assert "JSON_VALUE" not in sql and ".string()" not in sql, sql


def test_flex_array_predicate_is_json_exists_containment():
    sql = generate_hybrid(MODEL, _q(predicates=[
        {"ref": "Order.promo_tags", "op": "=", "value": "red"}]))
    assert "JSON_EXISTS(order_t.flex, '$.promo_tags?(@ == \"red\")')" in sql, sql


def test_returns_mix_columns_and_typed_flex():
    sql = generate_hybrid(MODEL, _q(returns=["Order.status", "Order.gift_note"]))
    assert "order_t.status" in sql, sql
    # SELECTed flex scalars are typed so the driver gets a SQL type, and the
    # emitted JSON key stays the property name (the equivalence invariant).
    assert "order_t.flex.gift_note.string() AS gift_note" in sql, sql


def test_join_reaches_the_hybrid_parent_table():
    sql = generate_hybrid(MODEL, _q(returns=["Order.status", "Customer.name"]))
    assert "JOIN customers_h customer" in sql, sql


def test_aggregation_uses_columns_for_core_and_item_methods_for_flex():
    q = {"root": "Order", "group_by": ["Order.status"],
         "aggregates": [{"name": "pts", "fn": "SUM", "ref": "Order.loyalty_points"}]}
    sql = generate_hybrid(MODEL, q)
    assert "SUM(order_t.flex.loyalty_points.numberOnly())" in sql, sql
    assert "GROUP BY order_t.status" in sql, sql


def test_order_by_flex_uses_the_typed_item_method():
    sql = generate_hybrid(MODEL, _q(order_by=[
        {"ref": "Order.loyalty_points", "dir": "DESC"}]))
    assert "ORDER BY order_t.flex.loyalty_points.numberOnly() DESC" in sql, sql


def test_candidates_include_hybrid_when_projected():
    cands = generate_candidates(MODEL, _q(predicates=[
        {"ref": "Order.status", "op": "=", "value": "OPEN"}]))
    assert "hybrid" in cands, sorted(cands)
    assert "orders_h" in cands["hybrid"]


# ---------------------------------------------------------------- indexes

def test_core_predicates_get_btree_indexes_on_the_hybrid_table():
    idx = generate_indexes(MODEL, [_q(predicates=[
        {"ref": "Order.status", "op": "=", "value": "OPEN"}])], shape="hybrid")
    assert "CREATE INDEX orders_h_status_ix ON orders_h (status);" in idx, idx


def test_flex_predicates_get_per_field_multivalue_indexes():
    idx = generate_indexes(MODEL, [_q(predicates=[
        {"ref": "Order.gift_note", "op": "=", "value": "wrap"}])], shape="hybrid")
    assert ("CREATE MULTIVALUE INDEX orders_h_gift_note_ix ON orders_h t "
            "(t.flex.gift_note.string());") in idx, idx


def test_flex_array_gets_a_multivalue_index_over_elements():
    idx = generate_indexes(MODEL, [_q(predicates=[
        {"ref": "Order.promo_tags", "op": "=", "value": "red"}])], shape="hybrid")
    assert "t.flex.promo_tags[*].string()" in idx, idx


def test_aggregation_index_shares_the_query_expressions():
    q = {"root": "Order", "group_by": ["Order.status"],
         "aggregates": [{"name": "pts", "fn": "SUM", "ref": "Order.loyalty_points"}]}
    idx = generate_indexes(MODEL, [q], shape="hybrid")
    assert "ON orders_h (status, flex.loyalty_points.numberOnly(), 0);" in idx, idx


def test_join_keys_derive_child_fk_indexes_in_the_hybrid_lane():
    q = {"root": "Customer", "returns": ["Customer.name", "Order.status"]}
    idx = generate_indexes(MODEL, [q], shape="hybrid")
    assert "CREATE INDEX orders_h_customer_id_ix ON orders_h (customer_id);" in idx, idx


# ------------------------------------------------------------------ writes

def test_core_write_is_a_plain_update_on_the_hybrid_table():
    sql = generate_update(MODEL, _q(predicates=[
        {"ref": "Order.order_id", "op": "=", "value": 5}]), "hybrid", "Order.total")
    assert sql == ("UPDATE orders_h SET total = total + 1 "
                   "WHERE order_id = 5"), sql


def test_flex_write_is_json_transform_on_the_flex_column():
    sql = generate_update(MODEL, _q(predicates=[
        {"ref": "Order.order_id", "op": "=", "value": 5}]), "hybrid",
        "Order.loyalty_points")
    assert "JSON_TRANSFORM(flex" in sql and "orders_h" in sql, sql
    assert "'$.loyalty_points'" in sql, sql
    assert "WHERE order_id = 5" in sql, sql


def test_insert_targets_the_hybrid_table():
    sql = generate_insert(MODEL, _q(), "hybrid")
    assert sql == "INSERT INTO orders_h (order_id) VALUES (9999)", sql


# -------------------------------------------------------- datalayer binds

def test_bound_flex_scalar_is_dot_with_a_plain_bind():
    sql, binds = bound_sql(MODEL, _q(predicates=[
        {"ref": "Order.gift_note", "op": "=", "value": "wrap"}]), "hybrid")
    assert "order_t.flex.gift_note = :b0" in sql, sql
    assert [b["name"] for b in binds] == ["b0"]


# ------------------------------------------------------- seed derivation

def test_populate_sql_derives_flex_from_the_relational_lane():
    from tooling.optimize.runner import hybrid_populate_sql
    stmts = hybrid_populate_sql(MODEL)
    joined = "\n".join(stmts)
    # derive, don't re-generate: one INSERT..SELECT per entity, flex built
    # with JSON_OBJECT keyed by the PROPERTY NAMES (the equivalence invariant)
    # and ABSENT ON NULL so sparse attributes stay absent, not null.
    assert "INSERT INTO customers_h" in joined and "FROM customers" in joined
    assert "INSERT INTO orders_h" in joined and "FROM orders" in joined
    assert "'gift_note' VALUE gift_note" in joined, joined
    assert "ABSENT ON NULL" in joined, joined
    # INSERTs parents-first, DELETEs children-first — the FK constraints are
    # live during the copy
    assert (joined.index("INSERT INTO customers_h")
            < joined.index("INSERT INTO orders_h"))
    assert (joined.index("DELETE FROM orders_h")
            < joined.index("DELETE FROM customers_h"))


# --------------------------------------------------------------- election

def test_hybrid_is_a_default_design_station():
    from tooling.optimize.runner import DEFAULT_DESIGNS
    assert DEFAULT_DESIGNS == ("document", "single_table", "hybrid",
                               "duality", "summary", "relational")


def test_candidate_shapes_gates_on_the_projection():
    from tooling.optimize.runner import candidate_shapes
    assert "hybrid" in candidate_shapes(MODEL, [])
    bare = _m(projections={})
    assert "hybrid" not in candidate_shapes(bare, [])


def test_propose_projections_nominates_hybrid_by_heuristic():
    # D1: attributes no pattern filters/aggregates/orders on move to flex;
    # the PK, relationship keys, and every filtered/aggregated prop stay
    # typed columns. Entities with nothing to move propose no flex.
    from tooling.optimize.runner import propose_projections
    m = _m(projections={})
    patterns = [{"name": "by_status", "rate": 10,
                 "query": _q(predicates=[
                     {"ref": "Order.status", "op": "=", "value": "OPEN"}],
                     returns=["Order.status", "Order.gift_note"])}]
    prop = (propose_projections(m, patterns).get("projections") or {}).get("hybrid")
    assert prop, "hybrid must compete by default"
    flex = prop["entities"]["Order"]["flex"]
    assert "gift_note" in flex, flex
    assert "status" not in flex and "customer_id" not in flex, flex


def test_pattern_name_gives_hybrid_a_catalog_identity():
    from tooling.optimize.patterns import PATTERNS, pattern_name
    name = pattern_name("hybrid", _q())
    assert name in {x["name"] for x in PATTERNS}, name
    entry = next(x for x in PATTERNS if x["name"] == name)
    assert "hybrid" in entry["shapes"]

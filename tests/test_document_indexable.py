# Copyright (c) 2026 Oracle and/or its affiliates.
"""A document's filtered read must be able to USE the index the patterns imply.

The invariant is EXPRESSION COUPLING: the query's filter form and the index's
definition must be the pair Oracle actually matches, or the collection
full-scans while an index sits there unused — the document then loses every
filtered read, the matrix concludes "documents are slow", and the conclusion
is a generator bug rather than a property of the design. (Measured live when
this pairing first broke: 1,451us full-scan -> 321us indexed.)

The canonical pair is now DOT NOTATION FIRST (field-verified 2026-07 on 26ai +
ORDS): a plain-dot scalar predicate is served by a typed-item-method MULTIVALUE
index — the same index a Mongo-lane createIndex/find uses, so both lanes share
one. JSON_VALUE RETURNING remains the documented last resort where its evidence
lives: the `_id` point read against its typed functional index.
"""
import sys
from pathlib import Path

import pytest


# `passenger_id` is a NUMBER because it REFERENCES passengers.passenger_id — a fact that
# lives in the relationships, not in the name. Guess the type from the name alone and you
# type it VARCHAR2, the index no longer matches the predicate, and the collection full-scans.
MODEL = {
    "entities": {
        "Passenger": {"table": "passengers", "pk": "passenger_id", "columns": {"name": "name"}},
        "Res": {"table": "reservations", "pk": "res_id",
                "columns": {"passenger_id": "passenger_id",   # FK -> NUMBER
                            "status": "status"}},             # VARCHAR2
    },
    "relationships": [{"from": "Passenger", "to": "Res", "cardinality": "1:N",
                       "from_key": "passenger_id", "to_key": "passenger_id"}],
    "projections": {"document": {"Res": {"collection": "res_docs", "id_path": "$._id"}}},
}
QUERY = {"root": "Res", "returns": ["Res.status"],
         "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}


def _mods(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import generate_document
    from tooling.generate.ddl import generate_indexes
    return generate_document, generate_indexes


def test_document_predicate_uses_the_indexable_form(repo_root: Path):
    """The scalar equality/range form is PLAIN DOT — served by the multivalue
    index (and by nothing else: a JSON_EXISTS path predicate can't use a
    functional index, and a JSON_VALUE predicate full-scans against multivalue)."""
    generate_document, _ = _mods(repo_root)
    sql = generate_document(MODEL, QUERY)
    assert "d.data.passenger_id = 7" in sql, sql
    assert "JSON_EXISTS" not in sql and "JSON_VALUE" not in sql, \
        f"an equality filter must be the plain-dot indexable form:\n{sql}"


def test_the_document_index_is_typed_from_the_column(repo_root: Path):
    """The multivalue index carries the typed item method — .numberOnly() for a
    numeric property. Typed .string() while the values are numbers, the strict
    typing no longer matches and the index is dead weight."""
    _, generate_indexes = _mods(repo_root)
    idx = generate_indexes(MODEL, [QUERY], shape="document")
    assert "CREATE MULTIVALUE INDEX" in idx, idx
    assert "t.data.passenger_id.numberOnly()" in idx, idx


def test_query_and_index_expressions_are_the_matching_pair(repo_root: Path):
    """The property that actually matters, asserted directly: the plain-dot
    predicate and the typed-item-method multivalue index are the pair Oracle
    matches (the dot predicate compiles to a TYPE(STRICT) recheck over the
    multivalue access — field-verified)."""
    generate_document, generate_indexes = _mods(repo_root)
    sql = generate_document(MODEL, QUERY)
    idx = generate_indexes(MODEL, [QUERY], shape="document")
    assert "d.data.passenger_id = 7" in sql, sql
    assert "t.data.passenger_id.numberOnly()" in idx, idx


def test_a_string_property_stays_a_string(repo_root: Path):
    """Do not swing the other way: a VARCHAR2 column must not be indexed numeric."""
    generate_document, generate_indexes = _mods(repo_root)
    q = {"root": "Res", "returns": ["Res.status"],
         "predicates": [{"ref": "Res.status", "op": "=", "value": "OPEN"}]}
    sql, idx = generate_document(MODEL, q), generate_indexes(MODEL, [q], shape="document")
    assert "numberOnly" not in idx
    assert "t.data.status.string()" in idx, idx
    assert "d.data.status = 'OPEN'" in sql, sql


STR_PK_MODEL = {
    "entities": {"Airport": {"table": "airports", "pk": "code", "pk_type": "VARCHAR2(10)",
                             "columns": {"city": "city"}}},
    "relationships": [],
    "projections": {"document": {"Airport": {"collection": "airport_docs",
                                             "id_path": "$._id"}}},
}


def test_a_string_pk_point_read_is_not_forced_to_number(repo_root: Path):
    """RETURNING NUMBER on 'LAX' yields NULL under the default NULL ON ERROR, so every id
    read silently returns zero rows. The PK's DECLARED type decides the RETURNING clause —
    and the id index must carry the identical expression or it is never used."""
    generate_document, generate_indexes = _mods(repo_root)
    q = {"root": "Airport", "returns": ["Airport.city"],
         "predicates": [{"ref": "Airport.code", "op": "=", "value": "LAX"}]}
    sql = generate_document(STR_PK_MODEL, q)
    assert "JSON_VALUE(d.data, '$._id') = 'LAX'" in sql, sql
    assert "RETURNING NUMBER" not in sql, sql
    idx = generate_indexes(STR_PK_MODEL, [q], shape="document")
    assert "JSON_VALUE(data, '$._id')" in idx, idx
    assert "RETURNING NUMBER" not in idx, f"index typed NUMBER for a VARCHAR2 pk:\n{idx}"


def test_pk_IN_and_BETWEEN_render_real_lists(repo_root: Path):
    """The PK fast path passed the whole list to the scalar renderer: IN '[1, 2]' is
    invalid SQL and BETWEEN '[1, 9]' has no AND — a hard syntax error either way."""
    generate_document, _ = _mods(repo_root)
    q_in = {"root": "Res", "returns": ["Res.status"],
            "predicates": [{"ref": "Res.res_id", "op": "IN", "value": [1, 2]}]}
    sql = generate_document(MODEL, q_in)
    assert "IN (1, 2)" in sql, sql
    q_bt = {"root": "Res", "returns": ["Res.status"],
            "predicates": [{"ref": "Res.res_id", "op": "BETWEEN", "value": [1, 9]}]}
    sql = generate_document(MODEL, q_bt)
    assert "BETWEEN 1 AND 9" in sql, sql


ARR_MODEL = {
    "entities": {
        "Product": {"table": "products", "pk": "product_id",
                    "columns": {"name": "name", "price": "price", "tags": "tags"},
                    "arrays": ["tags"]},          # tags is a JSON ARRAY, not a scalar
    },
    "relationships": [],
    "projections": {"document": {"Product": {"collection": "product_docs",
                                             "id_path": "$._id"}}},
}


def test_a_predicate_on_an_ARRAY_property_is_array_contains(repo_root: Path):
    """`tags = 'red'` against `"tags":["red","small"]` means CONTAINS, and only JSON_EXISTS
    expresses that: JSON_VALUE returns NULL for an array, so the filter matches nothing at
    all. Making scalar filters indexable (JSON_VALUE) must not silently break array-contains
    — the two are different questions and need different operators."""
    generate_document, _ = _mods(repo_root)
    q = {"root": "Product", "returns": ["Product.name"],
         "predicates": [{"ref": "Product.tags", "op": "=", "value": "red"}]}
    sql = generate_document(ARR_MODEL, q)
    assert 'JSON_EXISTS(d.data, \'$.tags?(@ == "red")\')' in sql, sql


def test_the_attribute_pattern_flag_also_means_array(repo_root: Path):
    """The pattern catalog marks the Attribute realization with `attribute_kv` rather than
    declaring the array on the entity. Honour both."""
    generate_document, _ = _mods(repo_root)
    m = {"entities": {"Product": {"table": "products", "pk": "product_id",
                                  "columns": {"name": "name", "tags": "tags"}}},
         "relationships": [],
         "projections": {"document": {"Product": {"collection": "product_docs"}}}}
    q = {"root": "Product", "returns": ["Product.name"], "attribute_kv": True,
         "predicates": [{"ref": "Product.tags", "op": "=", "value": "red"}]}
    assert "JSON_EXISTS" in generate_document(m, q)


def test_an_array_predicate_derives_a_MULTIVALUE_index(repo_root: Path):
    """The query side filters an array with JSON_EXISTS('$.tags?(@ == "red")') — a scalar
    JSON_VALUE(data,'$.tags') functional index is NULL for every row (JSON_VALUE of an
    array is NULL), so it is dead weight and the contains query full-scans forever. The
    serving index is MULTIVALUE over the array elements, in the runtime-verified form
    the live pattern-catalog test builds by hand: t.data.tags[*].string()."""
    generate_document, generate_indexes = _mods(repo_root)
    q = {"root": "Product", "returns": ["Product.name"],
         "predicates": [{"ref": "Product.tags", "op": "=", "value": "red"}]}
    idx = generate_indexes(ARR_MODEL, [q], shape="document")
    assert "CREATE MULTIVALUE INDEX" in idx, idx
    assert ".data.tags[*].string()" in idx, idx
    assert "JSON_VALUE(data, '$.tags')" not in idx, \
        f"a scalar index on an array property is all-NULL:\n{idx}"


def test_the_attribute_kv_flag_also_derives_a_MULTIVALUE_index(repo_root: Path):
    """Same coupling for the Attribute realization, where the array-ness is flagged on the
    QUERY (attribute_kv) rather than declared on the entity."""
    _, generate_indexes = _mods(repo_root)
    m = {"entities": {"Product": {"table": "products", "pk": "product_id",
                                  "columns": {"name": "name", "tags": "tags"}}},
         "relationships": [],
         "projections": {"document": {"Product": {"collection": "product_docs"}}}}
    q = {"root": "Product", "returns": ["Product.name"], "attribute_kv": True,
         "predicates": [{"ref": "Product.tags", "op": "=", "value": "red"}]}
    idx = generate_indexes(m, [q], shape="document")
    assert "CREATE MULTIVALUE INDEX" in idx, idx


def test_a_scalar_filter_is_still_the_indexable_form(repo_root: Path):
    """Do not swing the other way: a scalar must stay plain dot (the multivalue-
    served form), never JSON_EXISTS — the two are different questions."""
    generate_document, _ = _mods(repo_root)
    q = {"root": "Product", "returns": ["Product.name"],
         "predicates": [{"ref": "Product.price", "op": "=", "value": 10}]}
    sql = generate_document(ARR_MODEL, q)
    assert "d.data.price = 10" in sql and "JSON_EXISTS" not in sql, sql

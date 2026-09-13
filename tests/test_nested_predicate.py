# Copyright (c) 2026 Oracle and/or its affiliates.
"""A duality view and a document collection index JSON predicates in OPPOSITE ways.

Measured live on the airline capstone (100k reservations), filtering a nested parent's key:

    DV, JSON_VALUE(d.data,'$.passenger.passenger_id' RETURNING NUMBER) = 7   14,292 us  FULL SCAN
    DV, JSON_EXISTS(d.data,'$.passenger?(@.passenger_id == 7)')                 332 us  INDEXED
    relational reference                                                        445 us  INDEXED

A duality view is a projection OVER TABLES: a JSON_EXISTS path predicate is rewritten onto
the base columns and reaches the B-tree, while JSON_VALUE on a NESTED path is not and the
view full-scans. In a document COLLECTION it is the other way round — JSON_VALUE matches a
functional index and JSON_EXISTS cannot (that fix is `tests/test_document_indexable.py`).

Same syntax, same engine, opposite answers. Neither is guessable; both were measured.
"""
import sys
from pathlib import Path


MODEL = {
    "entities": {
        "Res": {"table": "reservations", "pk": "res_id",
                "columns": {"status": "status", "passenger_id": "passenger_id"}},
        "Passenger": {"table": "passengers", "pk": "passenger_id",
                      "columns": {"last_name": "last_name"}},
    },
    "relationships": [{"from": "Passenger", "to": "Res", "cardinality": "1:N",
                       "from_key": "passenger_id", "to_key": "passenger_id"}],
}
# needs the parent's column -> the view nests Passenger -> the FK moves to $.passenger.*
WITH_NAME = {"root": "Res", "returns": ["Res.status", "Passenger.last_name"],
             "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}
# needs nothing but the root -> the LEAN view -> the FK stays flat at $.passenger_id
FLAT = {"root": "Res", "returns": ["Res.status"],
        "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}
PATTERNS = [{"name": "flat", "rate": 5000, "query": FLAT},
            {"name": "with_name", "rate": 40, "query": WITH_NAME}]


def _r(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    return r


def test_a_nested_duality_predicate_uses_json_exists(repo_root: Path):
    """JSON_VALUE on a nested path makes the view FULL SCAN — 43x slower than the same
    filter expressed as JSON_EXISTS, which Oracle pushes down to the base index."""
    r = _r(repo_root)
    m = r.propose_projections(MODEL, PATTERNS)
    sql = r.pattern_sql(m, PATTERNS[1], "duality")
    assert "JSON_EXISTS" in sql, f"a nested duality filter must be JSON_EXISTS:\n{sql}"
    assert "'$.passenger?(@.passenger_id == 7)'" in sql, sql
    assert "$.passenger.passenger_id" not in sql, f"still the full-scanning form:\n{sql}"


def test_a_flat_duality_predicate_stays_json_value(repo_root: Path):
    """The lean view nests nothing, so the FK is a ROOT scalar and JSON_VALUE reaches the
    index perfectly well (measured: IDX RANGE, 4 logical reads). Do not 'fix' what works."""
    r = _r(repo_root)
    m = r.propose_projections(MODEL, PATTERNS)
    sql = r.pattern_sql(m, PATTERNS[0], "duality")
    assert "JSON_VALUE(d.data, '$.passenger_id' RETURNING NUMBER) = 7" in sql, sql


ST_PATTERNS = [
    {"name": "by_pax_single_type", "rate": 5000,
     "query": {"root": "Res", "returns": ["Res.status"],
               "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}},
    {"name": "by_pax_multi_type", "rate": 40,
     "query": {"root": "Res", "returns": ["Res.status", "Passenger.last_name"],
               "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}},
]


def test_a_multi_type_read_gets_a_non_sparse_index(repo_root: Path):
    """Every per-type index on the single collection is SPARSE — CASE WHEN type='X' THEN col
    END. A read that spans SEVERAL types filters on the plain column, so not one sparse index
    matches and the whole 1.2M-row table is scanned (measured: FULL SCAN, 2,481 logical reads,
    4,505us against relational's 499us). A filter used by a multi-type read needs a
    NON-sparse (col, type) index — the same shape as the anchor index, for the same reason."""
    r = _r(repo_root)
    from tooling.generate.ddl import generate_ddl
    m = r.propose_projections(MODEL, ST_PATTERNS)
    ddl = generate_ddl(m, "single_table").upper()
    assert "(PASSENGER_ID, TYPE)" in ddl, \
        f"no non-sparse index for the multi-type filter — it will full-scan:\n{ddl}"


def test_both_index_variants_when_both_read_shapes_exist(repo_root: Path):
    """The index must match the QUERY. A single-type read filters through the sparse CASE
    expression; a multi-type read filters on the plain column. When BOTH read shapes use the
    same filter, both indexes are needed — emit only the non-sparse one and the single-type
    read stops matching and full-scans, which is exactly what happened."""
    r = _r(repo_root)
    from tooling.generate.ddl import generate_ddl
    m = r.propose_projections(MODEL, ST_PATTERNS)   # one single-type + one multi-type read
    ddl = generate_ddl(m, "single_table").upper()
    assert "(PASSENGER_ID, TYPE)" in ddl, f"no non-sparse index for the multi-type read:\n{ddl}"
    assert "CASE WHEN TYPE = 'RES' THEN PASSENGER_ID END" in ddl, \
        f"no sparse index for the single-type read:\n{ddl}"


def test_single_table_columns_are_typed_with_fk_context(repo_root: Path):
    """`passenger_id` is a NUMBER — it is Passenger's PRIMARY KEY. Type it by name-inference
    and it lands VARCHAR2 in the converged table; every numeric filter then wraps in
    TO_NUMBER, and Oracle says so itself:

        filter(TO_NUMBER(CASE "TYPE" WHEN 'Res' THEN "PASSENGER_ID" END) = 7)
        "The following columns have predicates which preclude their use as keys
         in index range scan."

    The index is built, valid, and unusable. Same root cause as the document's mistyped
    JSON index: inference without FK context."""
    import sys
    sys.path.insert(0, str(repo_root))
    from tooling.generate.ddl import generate_ddl
    r = _r(repo_root)
    m = r.propose_projections(MODEL, ST_PATTERNS)
    ddl = generate_ddl(m, "single_table")
    assert "passenger_id NUMBER" in ddl, \
        f"passenger_id is Passenger's PK — it must be NUMBER, not a string:\n{ddl}"

# Copyright (c) 2026 Oracle and/or its affiliates.
"""Query the converged single-table design (from a DynamoDB import)."""
import json
from pathlib import Path

from tooling.generate.ingest import model_from_dynamodb
from tooling.generate.sql import generate_single_table, generate_candidates

M, _ = model_from_dynamodb(json.loads(Path("tests/fixtures/dynamodb_flightsfares.json").read_text()))


def test_per_type_read_filters_discriminator():
    sql = generate_single_table(M, {"root": "fare", "returns": ["fare.origin", "fare.dest"],
        "predicates": [{"ref": "fare.origin", "op": "=", "value": "SFO"},
                       {"ref": "fare.dest", "op": "=", "value": "JFK"}]})
    assert "FROM reservations" in sql
    assert "type IN ('fare')" in sql
    assert "CASE WHEN type = 'fare' THEN origin END = 'SFO'" in sql


def test_seat_map_uses_the_gsi_columns():
    sql = generate_single_table(M, {"type": "assignment", "returns": ["assignment.seat"],
        "predicates": [{"ref": "assignment.flight", "op": "=", "value": 150},
                       {"ref": "assignment.segId", "op": "=", "value": 2}]})
    assert "CASE WHEN type = 'assignment' THEN flight END = 150" in sql


def test_item_collection_read_by_anchor_spans_types():
    # "everything for this passenger" — booking + assignment under the shared anchor
    sql = generate_single_table(M, {"types": ["booking", "assignment"],
        "returns": ["assignment.flight"],
        "predicates": [{"ref": "assignment.pk0", "op": "=", "value": "Smith, Jon"}]})
    assert "type IN ('booking', 'assignment')" in sql
    assert "pk0 = 'Smith, Jon'" in sql   # item-collection: multi-type, not sparse-wrapped


def test_single_table_is_an_optimizer_candidate():
    cands = generate_candidates(M, {"root": "fare", "returns": ["fare.origin"],
        "predicates": [{"ref": "fare.origin", "op": "=", "value": "SFO"}]})
    assert "single_table" in cands


def test_result_transformed_into_a_document():
    # the co-located items assembled into the required document, in SQL — no stored doc
    sql = generate_single_table(M, {"type": "assignment", "as_document": True,
        "returns": ["assignment.flight", "assignment.seat", "assignment.segId"],
        "predicates": [{"ref": "assignment.pk0", "op": "=", "value": "Smith, Jon"}]})
    assert "JSON_ARRAYAGG(JSON_OBJECT(" in sql
    assert "'seat' VALUE seat" in sql
    assert "CASE WHEN type = 'assignment' THEN pk0 END = 'Smith, Jon'" in sql

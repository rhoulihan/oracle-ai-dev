# Copyright (c) 2026 Oracle and/or its affiliates.
"""Ingest a DynamoDB single-table design (NoSQL Workbench export) into a ModelSpec,
decomposing concatenated composite keys into typed columns and mapping GSIs to
multi-column indexes — no string concatenation reproduced."""
import json
from pathlib import Path

from tooling.generate.ingest import model_from_dynamodb
from tooling.generate.model import validate_model

FF = json.loads(Path("tests/fixtures/dynamodb_flightsfares.json").read_text())


def test_entities_are_the_item_types():
    model, ann = model_from_dynamodb(FF)
    assert set(model["entities"]) == {"fare", "flight", "booking", "assignment"}
    assert not validate_model(model)  # composite PKs tolerated


def test_composite_key_decomposed_and_typed():
    model, _ = model_from_dynamodb(FF)
    fare = model["entities"]["fare"]
    # the concatenated SK JFK#date#nonstop -> real key columns, not one string
    pk = fare["pk"] if isinstance(fare["pk"], list) else [fare["pk"]]
    for col in ("origin", "dest", "class"):
        assert col in pk, f"{col} should be part of fare's composite key"
    # date segment typed as a real timestamp, not a string
    assert fare["column_types"]["start_"] == "TIMESTAMP"  # start is reserved -> start_


def test_single_table_projection_with_discriminator():
    model, _ = model_from_dynamodb(FF)
    st = model["projections"]["single_table"]
    assert st["discriminator"] == "type"
    assert set(st["types"]) == {"fare", "flight", "booking", "assignment"}


def test_gsis_become_multi_column_indexes():
    model, _ = model_from_dynamodb(FF)
    idx = model["projections"]["single_table"]["indexes"]
    cols = {i["name"]: i["columns"] for i in idx}
    # flight GSI2: (number, segId) — flight-by-number
    assert any(c[:2] == ["number_", "segId"] for c in cols.values())  # number reserved
    # assignment GSI2: (flight, segId, seat) — the seat map / manifest
    assert any(c == ["flight", "segId", "seat"] for c in cols.values())


def test_returns_annotations_for_confirmation():
    _, ann = model_from_dynamodb(FF)
    assert isinstance(ann, list) and ann  # infer-then-confirm

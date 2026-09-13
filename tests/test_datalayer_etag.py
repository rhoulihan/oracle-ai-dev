# Copyright (c) 2026 Oracle and/or its affiliates.
"""Gate 16 becomes mechanism in the generated data layer.

The ETag round-trip is the single most likely duality integration bug: a write
that strips `_metadata` does not error — it silently disables conflict
detection. So a duality spec's generated Python repository ships the canonical
optimistic write pair: `get_<root>_doc` fetches the document INCLUDING
`_metadata`, and `replace_<root>_doc` REFUSES a document whose `_metadata` was
stripped and maps ORA-42699 to StaleDocumentError. The generated README teaches
the same round-trip for every platform. The live half of this contract (a
deliberately stale etag really raises through the generated code) is
tests/test_write_conflict_live.py.
"""

import json
from pathlib import Path

import pytest

from tooling.datalayer.platforms import render_all

MODEL = json.loads(Path("tests/fixtures/restaurant_model.json").read_text())


def _spec(shape="duality"):
    return {"model": MODEL, "platforms": ["python"], "patterns": [
        {"name": "get_order", "shape": shape,
         "query": {"root": "Order", "returns": ["Order.total"],
                   "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}}]}


def test_duality_spec_generates_the_optimistic_write_pair():
    py = render_all(_spec())["repository.py"]
    assert "def get_order_doc(" in py
    assert "def replace_order_doc(" in py
    assert "class StaleDocumentError" in py
    assert "42699" in py, "the conflict error must be mapped, not leaked"
    # The document must go back as a NATIVE JSON bind: the driver returns
    # NUMBER values as decimal.Decimal, which json.dumps cannot serialize —
    # the round-trip crashed on the live tier until the bind went native.
    assert "DB_TYPE_JSON" in py
    assert "json.dumps" not in py


def test_replace_refuses_a_stripped_metadata_before_touching_the_db():
    import sys
    import types
    # The offline tier ships no oracledb; the generated module only needs the
    # NAME importable here, because the refusal path raises before any driver
    # call — the real-driver behavior is proven live (test_write_conflict_live).
    sys.modules.setdefault("oracledb", types.SimpleNamespace(
        DB_TYPE_JSON=object(), DatabaseError=Exception))
    ns = {}
    exec(compile(render_all(_spec())["repository.py"], "repository.py", "exec"), ns)
    # conn=None proves the refusal happens BEFORE any database call
    with pytest.raises(ValueError, match="_metadata"):
        ns["replace_order_doc"](None, {"_id": 1, "total": 5})


def test_replace_writes_through_the_view_with_a_typed_id_predicate():
    py = render_all(_spec())["repository.py"]
    assert "UPDATE order_dv" in py
    assert "JSON_VALUE" in py and "$._id" in py, \
        "the id predicate must be the canonical typed expression"


def test_readme_teaches_the_round_trip_for_every_platform():
    md = render_all(_spec())["README.md"]
    assert "_metadata" in md
    assert "ORA-42699" in md
    assert "conflict" in md.lower()


def test_non_duality_spec_implies_no_concurrency_it_does_not_have():
    files = render_all(_spec(shape="relational"))
    assert "replace_" not in files["repository.py"]
    assert "StaleDocumentError" not in files["repository.py"]
    assert "_metadata" not in files["README.md"]

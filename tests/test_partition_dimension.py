# Copyright (c) 2026 Oracle and/or its affiliates.
"""The per-entity partition dimension (Phase-1 spec, H3).

Partitioning is an orthogonal DIMENSION on the base-table shapes: a
`partition` block on an entity emits the clause on that entity's table in the
relational AND hybrid lanes, index derivation follows with a LOCAL/global
policy, and the `--no-partition` knob threads CLI -> optimize() -> deploy AND
winning_ddl — the measured design must equal the emitted design. v1 supports
the three lifecycle-justified families: interval (time-series TTL), auto_list
(enumerable categories — the proven single_table mechanism), and hash
(spread). Free licensing is verified (Partitioning Free = Y, 26ai licensing
manual, adversarially confirmed 3-0).
"""

import json

from tooling.generate.ddl import generate_ddl, generate_indexes
from tooling.generate.model import validate_model

MODEL = {
    "entities": {
        "Sensor": {"table": "sensors", "pk": "sensor_id",
                   "columns": {"label": "label"}},
        "Reading": {"table": "readings", "pk": "reading_id",
                    "columns": {"sensor_id": "sensor_id",
                                "taken_at": "taken_at",
                                "value": "value"},
                    "column_types": {"value": "NUMBER"},
                    "partition": {"by": "interval", "column": "taken_at",
                                  "interval": "NUMTOYMINTERVAL(1,'MONTH')"}},
    },
    "relationships": [{"from": "Sensor", "to": "Reading", "cardinality": "1:N",
                       "from_key": "sensor_id", "to_key": "sensor_id"}],
}


def _m():
    return json.loads(json.dumps(MODEL))


# --------------------------------------------------------------- emission

def test_interval_partition_clause_is_emitted():
    ddl = generate_ddl(MODEL, "relational")
    assert ("PARTITION BY RANGE (taken_at) INTERVAL (NUMTOYMINTERVAL(1,'MONTH')) "
            "(PARTITION p0 VALUES LESS THAN "
            "(TIMESTAMP '2000-01-01 00:00:00'))") in ddl, ddl


def test_no_partition_knob_removes_the_clause():
    ddl = generate_ddl(MODEL, "relational", partition=False)
    assert "PARTITION BY" not in ddl, ddl


def test_auto_list_partition_uses_the_proven_seed_form():
    m = _m()
    m["entities"]["Sensor"]["partition"] = {"by": "auto_list", "column": "label"}
    ddl = generate_ddl(m, "relational")
    assert ("PARTITION BY LIST (label) AUTOMATIC "
            "(PARTITION p_seed VALUES ('__seed__'))") in ddl, ddl


def test_hash_partition_names_a_partition_count():
    m = _m()
    del m["entities"]["Reading"]["partition"]
    m["entities"]["Sensor"]["partition"] = {"by": "hash", "column": "sensor_id",
                                            "partitions": 4}
    ddl = generate_ddl(m, "relational")
    assert "PARTITION BY HASH (sensor_id) PARTITIONS 4" in ddl, ddl


def test_partition_carries_into_the_hybrid_lane():
    m = _m()
    m["projections"] = {"hybrid": {"entities": {"Reading": {"flex": ["value"]}}}}
    ddl = generate_ddl(m, "hybrid")
    assert "readings_h" in ddl
    assert "PARTITION BY RANGE (taken_at)" in ddl, ddl


def test_explicit_initial_boundary_overrides_the_default():
    m = _m()
    m["entities"]["Reading"]["partition"]["initial"] = "TIMESTAMP '2020-06-01 00:00:00'"
    ddl = generate_ddl(m, "relational")
    assert "LESS THAN (TIMESTAMP '2020-06-01 00:00:00')" in ddl, ddl


def test_interval_on_a_non_time_column_requires_an_initial_boundary():
    m = _m()
    m["entities"]["Reading"]["partition"] = {"by": "interval", "column": "value",
                                             "interval": "100"}
    try:
        generate_ddl(m, "relational")
        raise AssertionError("expected a ValueError naming the missing initial boundary")
    except ValueError as exc:
        assert "initial" in str(exc), exc


# ------------------------------------------------------------- validation

def test_unknown_strategy_is_a_violation():
    m = _m()
    m["entities"]["Reading"]["partition"]["by"] = "reference"
    v = validate_model(m)
    assert any("partition" in x for x in v), v


def test_partition_column_must_resolve_on_the_entity():
    m = _m()
    m["entities"]["Reading"]["partition"]["column"] = "ghost"
    v = validate_model(m)
    assert any("ghost" in x for x in v), v


# ----------------------------------------------------------- index policy

_Q = {"root": "Reading", "returns": ["Reading.value"],
      "predicates": [{"ref": "Reading.value", "op": ">", "value": 5}]}


def test_btree_on_a_partitioned_entity_is_local_by_default():
    idx = generate_indexes(MODEL, [_Q], shape="relational")
    assert "CREATE INDEX readings_value_ix ON readings (value) LOCAL;" in idx, idx


def test_local_indexes_false_keeps_the_index_global():
    m = _m()
    m["entities"]["Reading"]["partition"]["local_indexes"] = False
    idx = generate_indexes(m, [_Q], shape="relational")
    assert "ON readings (value);" in idx and "LOCAL" not in idx, idx


def test_partition_false_keeps_every_index_global():
    idx = generate_indexes(MODEL, [_Q], shape="relational", partition=False)
    assert "LOCAL" not in idx, idx


def test_join_key_index_on_a_partitioned_child_is_local():
    q = {"root": "Sensor", "returns": ["Sensor.label", "Reading.value"]}
    idx = generate_indexes(MODEL, [q], shape="relational")
    assert "CREATE INDEX readings_sensor_id_ix ON readings (sensor_id) LOCAL;" in idx, idx


def test_unpartitioned_entities_are_untouched():
    q = {"root": "Sensor", "returns": ["Sensor.label"],
         "predicates": [{"ref": "Sensor.label", "op": "=", "value": "a"}]}
    idx = generate_indexes(MODEL, [q], shape="relational")
    assert "ON sensors (label);" in idx and "LOCAL" not in idx, idx


# ---------------------------------------------------------- knob threading

def test_cli_lists_the_partition_and_flex_knobs():
    import pathlib
    import subprocess
    import sys
    repo = pathlib.Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-m", "tooling.optimize", "--help"],
                       capture_output=True, text=True, cwd=repo)
    assert r.returncode == 0
    for flag in ("--no-partition", "--flex-limit", "--no-flex-limit"):
        assert flag in r.stdout, f"missing CLI knob: {flag}"


def test_optimize_threads_partition_and_flex_limit(monkeypatch):
    import tooling.optimize.runner as r
    seen = {}
    meas = {"read_r": {"relational": 1.0}}
    monkeypatch.setattr(r, "candidate_shapes", lambda m, p, only=None: ["relational"])
    monkeypatch.setattr(r, "deploy", lambda conn, m, p, s, **kw: seen.setdefault("deploy_kw", kw))
    monkeypatch.setattr(r, "gather_stats", lambda conn: None)
    monkeypatch.setattr(r, "validate_answers", lambda conn, m, p, c, progress=None: ({}, []))
    monkeypatch.setattr(r, "measure",
                        lambda conn, m, p, c, trials=7, warmup=2, invalid=None: (meas, {}))
    monkeypatch.setattr(r, "flip_sweep", lambda m, p, meas: [])
    monkeypatch.setattr(r, "winning_ddl",
                        lambda m, chosen, **kw: seen.setdefault("ddl_kw", kw) or "")
    patterns = [{"name": "read_r", "kind": "read", "rate": 1.0,
                 "query": {"root": "Reading", "returns": ["Reading.value"]}}]
    r.optimize(None, {"model": _m(), "patterns": patterns}, do_seed=False,
               partition=False, flex_limit=4096)
    assert seen["deploy_kw"]["partition"] is False
    assert seen["deploy_kw"]["flex_limit"] == 4096
    assert seen["ddl_kw"]["partition"] is False, \
        "the emitted winner must be built exactly as the measured one was"
    assert seen["ddl_kw"]["flex_limit"] == 4096

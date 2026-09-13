# Copyright (c) 2026 Oracle and/or its affiliates.
"""The per-entity `organization` (IOT) and `compress` dimensions (Phase-3 spec).

Two more orthogonal DIMENSIONS on the shared base-table emitter: an
`organization: "index"` block makes that entity's table its own primary-key
B-tree, a `compress: "advanced"` block turns on Advanced Row Compression, and
both compose across the relational, hybrid `_h` and summary `_s` lanes. The
knobs `--no-iot` / `--no-compress` thread CLI -> optimize() -> deploy AND
winning_ddl — the measured design must equal the emitted design.

The engine decided the rules; the live probes (26ai Free 23.26.2) are quoted
in the spec's §2 and enforced here as validation BLOCKERS naming the ORA each
one prevents: IOT x non-hash partition is ORA-25198 (hash alone composes),
IOT x row compression is ORA-00922, and a multivalue index on an IOT is
ORA-61714 — so an entity carrying hybrid flex properties may not also be an
IOT, or its flex predicates would silently full-scan without their MVIs.
Clause order (`ORGANIZATION INDEX [PCTTHRESHOLD n] [INCLUDING col] OVERFLOW`,
then `ROW STORE COMPRESS ADVANCED`, then the partition clause) is
probe-pinned, not guessed.
"""

import json

from tooling.generate.ddl import generate_ddl
from tooling.generate.model import validate_model

MODEL = {
    "entities": {
        "Sensor": {"table": "sensors", "pk": "sensor_id",
                   "columns": {"label": "label"}},
        "Reading": {"table": "readings", "pk": "reading_id",
                    "columns": {"sensor_id": "sensor_id",
                                "taken_at": "taken_at",
                                "status": "status_code",
                                "value": "value"},
                    "column_types": {"value": "NUMBER"},
                    "organization": "index"},
    },
    "relationships": [{"from": "Sensor", "to": "Reading", "cardinality": "1:N",
                       "from_key": "sensor_id", "to_key": "sensor_id"}],
}

_SUMMARY = {"mvs": [{"name": "readings_by_status_mv",
                     "query": {"root": "Reading",
                               "group_by": ["Reading.status"],
                               "aggregates": [{"name": "n", "fn": "COUNT",
                                               "ref": "*"}]}}]}


def _m():
    return json.loads(json.dumps(MODEL))


def _create(ddl, table):
    """The one CREATE TABLE statement for `table` — a clause on the wrong
    entity's table is not the clause the model asked for."""
    head = f"CREATE TABLE IF NOT EXISTS {table} ("
    assert head in ddl, ddl
    i = ddl.index(head)
    return ddl[i:ddl.index(";", i) + 1]


# --------------------------------------------------------------- emission

def test_organization_index_is_emitted_on_that_entity():
    ddl = generate_ddl(MODEL, "relational")
    # OVERFLOW is unconditional: name-inferred VARCHAR2(4000) columns make a
    # >50%-of-block row the COMMON case, and an IOT without an overflow
    # segment then fails to create at all (ORA-01429 when partitioned) —
    # live-isolated during Phase-3 validation
    assert "ORGANIZATION INDEX OVERFLOW" in _create(ddl, "readings")
    assert "ORGANIZATION INDEX" not in _create(ddl, "sensors")


def test_organization_carries_into_the_summary_lane():
    m = _m()
    m["projections"] = {"summary": _SUMMARY}
    ddl = generate_ddl(m, "summary")
    assert "ORGANIZATION INDEX OVERFLOW" in _create(ddl, "readings_s")
    assert "ORGANIZATION INDEX" not in _create(ddl, "sensors_s")


def test_organization_carries_into_the_hybrid_lane():
    # the flex lives on the OTHER entity: an IOT may not carry flex props
    # (ORA-61714 kills their multivalue indexes), so the lanes compose here
    # exactly as P8 allows.
    m = _m()
    m["projections"] = {"hybrid": {"entities": {"Sensor": {"flex": ["label"]}}}}
    ddl = generate_ddl(m, "hybrid")
    assert "ORGANIZATION INDEX OVERFLOW" in _create(ddl, "readings_h")
    assert "ORGANIZATION INDEX" not in _create(ddl, "sensors_h")


def test_pctthreshold_emits_the_overflow_form():
    m = _m()
    m["entities"]["Reading"]["pctthreshold"] = 30
    stmt = _create(generate_ddl(m, "relational"), "readings")
    assert "ORGANIZATION INDEX PCTTHRESHOLD 30 OVERFLOW" in stmt, stmt


def test_including_resolves_the_property_to_its_column():
    m = _m()
    m["entities"]["Reading"]["including"] = "status"
    stmt = _create(generate_ddl(m, "relational"), "readings")
    assert "ORGANIZATION INDEX INCLUDING status_code OVERFLOW" in stmt, stmt


def test_pctthreshold_and_including_keep_the_probe_pinned_order():
    m = _m()
    m["entities"]["Reading"]["pctthreshold"] = 30
    m["entities"]["Reading"]["including"] = "status"
    stmt = _create(generate_ddl(m, "relational"), "readings")
    assert ("ORGANIZATION INDEX PCTTHRESHOLD 30 INCLUDING status_code "
            "OVERFLOW") in stmt, stmt


def test_organization_precedes_the_partition_clause():
    m = _m()
    m["entities"]["Reading"]["partition"] = {"by": "hash",
                                             "column": "sensor_id",
                                             "partitions": 4}
    stmt = _create(generate_ddl(m, "relational"), "readings")
    assert stmt.index("ORGANIZATION INDEX") < stmt.index("PARTITION BY HASH"), stmt


def test_compress_advanced_is_emitted_before_the_partition_clause():
    m = _m()
    del m["entities"]["Reading"]["organization"]
    m["entities"]["Reading"]["compress"] = "advanced"
    m["entities"]["Reading"]["partition"] = {"by": "hash",
                                             "column": "sensor_id",
                                             "partitions": 4}
    stmt = _create(generate_ddl(m, "relational"), "readings")
    assert "ROW STORE COMPRESS ADVANCED" in stmt, stmt
    assert stmt.index(")") < stmt.index("ROW STORE COMPRESS ADVANCED"), stmt
    assert (stmt.index("ROW STORE COMPRESS ADVANCED")
            < stmt.index("PARTITION BY HASH")), stmt


def test_duality_base_tables_inherit_the_dimensions():
    # P6: a duality view over an IOT base creates and answers a point read.
    m = _m()
    m["projections"] = {"duality": {"Sensor": "sensors_dv"}}
    ddl = generate_ddl(m, "duality")
    assert "ORGANIZATION INDEX" in _create(ddl, "readings")


# ------------------------------------------------------------------ knobs

def test_no_iot_knob_removes_the_organization_clause():
    m = _m()
    m["entities"]["Reading"]["pctthreshold"] = 30
    ddl = generate_ddl(m, "relational", iot=False)
    assert "ORGANIZATION" not in ddl, ddl


def test_no_compress_knob_removes_the_compress_clause():
    m = _m()
    del m["entities"]["Reading"]["organization"]
    m["entities"]["Reading"]["compress"] = "advanced"
    assert "ROW STORE COMPRESS ADVANCED" in generate_ddl(m, "relational")
    assert "COMPRESS" not in generate_ddl(m, "relational", compress=False)


# ------------------------------------------------------------- validation

def test_organization_value_is_allowlisted():
    m = _m()
    m["entities"]["Reading"]["organization"] = "cluster"
    v = validate_model(m)
    assert any("organization" in x and "cluster" in x for x in v), v


def test_heap_is_a_legal_organization():
    m = _m()
    m["entities"]["Reading"]["organization"] = "heap"
    assert not [x for x in validate_model(m) if "organization" in x], validate_model(m)


def test_pctthreshold_outside_1_to_50_is_a_violation():
    for bad in (0, 51):
        m = _m()
        m["entities"]["Reading"]["pctthreshold"] = bad
        v = validate_model(m)
        assert any("pctthreshold" in x for x in v), (bad, v)


def test_including_must_resolve_on_the_entity():
    m = _m()
    m["entities"]["Reading"]["including"] = "ghost"
    v = validate_model(m)
    assert any("ghost" in x for x in v), v


def test_overflow_options_need_organization_index():
    m = _m()
    del m["entities"]["Reading"]["organization"]
    m["entities"]["Reading"]["pctthreshold"] = 30
    m["entities"]["Reading"]["including"] = "status"
    v = validate_model(m)
    assert any("pctthreshold" in x and "organization" in x for x in v), v
    assert any("including" in x and "organization" in x for x in v), v


def test_iot_with_compress_is_blocked_naming_ora_00922():
    m = _m()
    m["entities"]["Reading"]["compress"] = "advanced"
    v = validate_model(m)
    assert any("ORA-00922" in x for x in v), v


def test_iot_with_a_non_hash_partition_is_blocked_naming_ora_25198():
    m = _m()
    m["entities"]["Reading"]["partition"] = {
        "by": "interval", "column": "taken_at",
        "interval": "NUMTOYMINTERVAL(1,'MONTH')"}
    v = validate_model(m)
    assert any("ORA-25198" in x for x in v), v


def test_iot_with_a_hash_partition_passes_validation():
    # the hash key must sit WITHIN the primary key (see the ORA-25199 test) —
    # so the passing fixture partitions on the IOT's own pk
    m = _m()
    m["entities"]["Reading"]["partition"] = {"by": "hash",
                                             "column": "reading_id",
                                             "partitions": 4}
    v = validate_model(m)
    assert not v, v


def test_iot_hash_partition_key_must_be_within_the_pk():
    # live-flagged during Phase-3 review: an IOT's partitioning key must be a
    # subset of its primary key — a non-PK hash column deploys into ORA-25199.
    # The validator names it before the engine does.
    m = _m()
    m["entities"]["Reading"]["partition"] = {"by": "hash",
                                             "column": "sensor_id",
                                             "partitions": 4}
    v = validate_model(m)
    assert any("ORA-25199" in x for x in v), v


def test_iot_with_hybrid_flex_props_is_blocked_naming_ora_61714():
    m = _m()
    m["projections"] = {"hybrid": {"entities": {"Reading": {"flex": ["value"]}}}}
    v = validate_model(m)
    assert any("ORA-61714" in x for x in v), v


def test_compress_allowlist_is_exactly_advanced():
    m = _m()
    del m["entities"]["Reading"]["organization"]
    m["entities"]["Reading"]["compress"] = "basic"
    v = validate_model(m)
    hits = [x for x in v if "compress" in x]
    assert hits, v
    # the measured reason, not a bare allowlist: BASIC compresses on
    # bulk load only and conventional-path updates decompress the block.
    assert any("bulk" in x and "decompress" in x for x in hits), hits


# ---------------------------------------------------------- knob threading

def test_cli_lists_the_iot_and_compress_knobs():
    import pathlib
    import subprocess
    import sys
    repo = pathlib.Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-m", "tooling.optimize", "--help"],
                       capture_output=True, text=True, cwd=repo)
    assert r.returncode == 0
    for flag in ("--no-iot", "--no-compress"):
        assert flag in r.stdout, f"missing CLI knob: {flag}"


def test_optimize_threads_iot_and_compress(monkeypatch):
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
               iot=False, compress=False)
    assert seen["deploy_kw"]["iot"] is False
    assert seen["deploy_kw"]["compress"] is False
    assert seen["ddl_kw"]["iot"] is False, \
        "the emitted winner must be built exactly as the measured one was"
    assert seen["ddl_kw"]["compress"] is False

# Copyright (c) 2026 Oracle and/or its affiliates.
"""The duality design gates are a VALIDATOR, not prose.

`references/duality-design-gates.md` states 24 RULEs; the ones decidable from a
ModelSpec alone must be enforced by `tooling.duality.validate_duality`, and the
DDL emit path must refuse to emit a view that trips a blocker. Gate numbers here
map 1:1 to the RULE numbering in that reference.
"""

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _model():
    """A minimal clean model: Order (root) --1:N--> OrderItem, scoped view."""
    return {
        "entities": {
            "Order": {"table": "orders", "pk": "order_id",
                      "columns": {"total": "total"}},
            "OrderItem": {"table": "order_item", "pk": "order_item_id",
                          "columns": {"quantity": "quantity"}},
        },
        "relationships": [
            {"from": "Order", "to": "OrderItem", "from_key": "order_id",
             "to_key": "order_id", "cardinality": "1:N"},
        ],
        "projections": {"duality": {"Order": [
            {"view": "order_dv", "includes": ["OrderItem"]}]}},
    }


def _blockers(model, **kw):
    from tooling.duality.validate import validate_duality
    return [v for v in validate_duality(model, **kw) if v.severity == "blocker"]


def _warnings(model, **kw):
    from tooling.duality.validate import validate_duality
    return [v for v in validate_duality(model, **kw) if v.severity == "warning"]


# ---------------------------------------------------------------- blockers

def test_keyless_root_is_a_blocker_gate_1():
    m = _model()
    m["entities"]["Order"]["pk"] = ""
    assert any(v.gate == 1 for v in _blockers(m)), \
        "a root with no PK/UK cannot root a duality view (ORA-42647)"


def test_unknown_include_is_a_blocker_gate_2():
    m = _model()
    m["projections"]["duality"]["Order"][0]["includes"] = ["OrderItem", "Nowhere"]
    assert any(v.gate == 2 for v in _blockers(m))


def test_unreachable_include_is_a_blocker_gate_2():
    # Orphan exists but no relationship reaches it: today the generator would
    # SILENTLY omit it from the view and queries against it return nothing.
    m = _model()
    m["entities"]["Orphan"] = {"table": "orphan", "pk": "orphan_id", "columns": {}}
    m["projections"]["duality"]["Order"][0]["includes"] = ["OrderItem", "Orphan"]
    assert any(v.gate == 2 for v in _blockers(m))


def test_fk_target_not_parent_key_is_a_blocker_gate_3():
    # Order N:1 Customer joined on customer.name (not its PK): a non-unique
    # parent-side join column fans rows out and breaks one-document-per-root.
    m = _model()
    m["entities"]["Customer"] = {"table": "customer", "pk": "customer_id",
                                 "columns": {"name": "name"}}
    m["relationships"].append(
        {"from": "Order", "to": "Customer", "from_key": "customer_name",
         "to_key": "name", "cardinality": "N:1"})
    m["projections"]["duality"]["Order"][0]["includes"] = ["OrderItem", "Customer"]
    assert any(v.gate == 3 for v in _blockers(m))


def test_column_type_off_the_allowlist_is_a_blocker_gate_9():
    m = _model()
    m["entities"]["Order"]["column_types"] = {"total": "XMLTYPE"}
    assert any(v.gate == 9 for v in _blockers(m))


def test_duplicate_keys_at_one_level_is_a_blocker_gate_11():
    # The child array is emitted as `orderitems`; a root scalar of the same
    # name makes a document with two `orderitems` keys at one level.
    m = _model()
    m["entities"]["Order"]["columns"]["orderitems"] = "note"
    assert any(v.gate == 11 for v in _blockers(m))


def test_self_nesting_is_a_blocker_gate_11():
    # An all-in view over a self-referencing edge defines a recursive document;
    # the spec has no distinct-join-predicate syntax, so refuse.
    m = _model()
    m["entities"]["Order"]["columns"]["parentId"] = "parent_id"
    m["relationships"].append(
        {"from": "Order", "to": "Order", "from_key": "order_id",
         "to_key": "parent_id", "cardinality": "1:N"})
    m["projections"]["duality"]["Order"] = "order_dv"      # all-in
    assert any(v.gate == 11 for v in _blockers(m))


def test_clean_model_has_no_blockers():
    assert _blockers(_model()) == []


# ---------------------------------------------------------------- warnings

def test_writable_view_warns_gate_12():
    # Generated views are writable by default (the optimizer must measure
    # writes); Gate 12 wants each writable table recorded as a decision.
    assert any(v.gate == 12 for v in _warnings(_model()))


def test_single_all_in_view_warns_gate_18():
    # A bare-string projection over a multi-entity aggregate is one kitchen-sink
    # view: every point read pays for the widest read's joins.
    m = json.loads((FIXTURES / "restaurant_model.json").read_text())
    assert any(v.gate == 18 for v in _warnings(m))


# ------------------------------------------------------- the emit-path hook

def test_generate_ddl_refuses_to_emit_on_a_blocker():
    from tooling.duality.validate import DualityGateError
    from tooling.generate.ddl import generate_ddl
    m = _model()
    m["entities"]["Order"]["pk"] = ""
    with pytest.raises(DualityGateError) as err:
        generate_ddl(m, "duality")
    assert "gate-1" in str(err.value)


def test_generate_ddl_annotates_warnings_above_the_view():
    from tooling.generate.ddl import generate_ddl
    ddl = generate_ddl(_model(), "duality")
    warn = ddl.find("-- WARN [gate-12]")
    view = ddl.find("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW")
    assert 0 <= warn < view, "warnings must annotate the emitted DDL, not vanish"


def test_warn_comments_never_contain_a_statement_terminator():
    # Deployers split the DDL on ';' (ensure_schema, schema.sql) — a semicolon
    # inside a comment line cuts it in half and the orphaned tail reaches the
    # server as an invalid statement (ORA-00900, caught on the live tier).
    from tooling.generate.ddl import generate_ddl
    ddl = generate_ddl(_model(), "duality")
    warn_lines = [l for l in ddl.splitlines() if l.startswith("--")]
    assert warn_lines, "expected at least one warning annotation"
    for line in warn_lines:
        assert ";" not in line, f"statement terminator inside a comment: {line!r}"


def test_shipped_fixture_passes_its_own_gates():
    m = json.loads((FIXTURES / "restaurant_model.json").read_text())
    assert _blockers(m) == [], "our own shipped model must pass our own gates"
    from tooling.generate.ddl import generate_ddl
    assert "CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW" in generate_ddl(m, "duality")


# ------------------------------------------------------------------ the CLI

def test_cli_reports_blockers_and_exits_1(tmp_path):
    m = _model()
    m["entities"]["Order"]["pk"] = ""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(m))
    r = subprocess.run([sys.executable, "-m", "tooling.duality", str(bad)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 1
    assert "gate-1" in r.stdout


def test_cli_passes_a_clean_model_and_exits_0(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_model()))
    r = subprocess.run([sys.executable, "-m", "tooling.duality", str(good)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr

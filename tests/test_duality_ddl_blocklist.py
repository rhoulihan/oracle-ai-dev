# Copyright (c) 2026 Oracle and/or its affiliates.
"""Two hard duality limits, as tripwires (gates 22 and 23 of the design gates).

An index cannot be created on a duality view's DATA column, and VPD/RAS policy
is not supported on a duality view — both belong on the BASE TABLES. No code
path emits either today; these tests fail the moment any generator, asset, or
skill reference starts producing them. The VPD package name is assembled from
parts below so this file itself never contains the token it bans.
"""

import json
import re
from pathlib import Path

from tooling.generate.ddl import duality_views, generate_ddl, generate_indexes

# CREATE [UNIQUE|BITMAP|MULTIVALUE|SEARCH] INDEX <name> ON <target>
_INDEX_ON = re.compile(
    r"CREATE\s+(?:UNIQUE\s+|BITMAP\s+|MULTIVALUE\s+|SEARCH\s+)*INDEX\s+\S+\s+ON\s+([A-Za-z0-9_$#.\"]+)",
    re.IGNORECASE)
# the VPD package (DBMS_||RLS) and its policy call, assembled so this file
# never contains the contiguous token and needs no scan exemption.
_VPD = re.compile("DBMS_" + "RLS", re.IGNORECASE)

_FIXTURE = Path("tests/fixtures/restaurant_model.json")


def _queries(model):
    """A synthetic workload that filters and aggregates every entity, so the
    index generator is forced to derive an index for each of them."""
    qs = []
    for ent, e in model["entities"].items():
        for prop in (e.get("columns") or {}):
            qs.append({"root": ent, "returns": [f"{ent}.{prop}"],
                       "predicates": [{"ref": f"{ent}.{prop}", "op": "=", "value": 1}]})
    root = next(iter(model["entities"]))
    prop = next(iter(model["entities"][root].get("columns") or {}), None)
    if prop:
        qs.append({"root": root, "group_by": [f"{root}.{prop}"],
                   "aggregates": [{"fn": "count", "ref": "*", "name": "n"}]})
    return qs


def _index_targets(sql):
    return {m.group(1).strip('"').lower() for m in _INDEX_ON.finditer(sql)}


# --------------------------------------------------------------- red paths

def test_scanner_detects_a_planted_index_on_a_view(tmp_path):
    planted = "CREATE MULTIVALUE INDEX bad_ix ON order_dv (data);"
    assert "order_dv" in _index_targets(planted)


def test_scanner_detects_a_planted_vpd_call(tmp_path):
    planted = ("BEGIN DBMS_" + "RLS.ADD_POLICY(object_name => 'ORDER_DV', "
               "policy_name => 'p'); END;")
    assert _VPD.search(planted)


# ------------------------------------------------------- generated surfaces

def test_generated_duality_indexes_target_base_tables_never_the_view():
    model = json.loads(_FIXTURE.read_text())
    views = {v["view"].lower()
             for r in (model.get("projections") or {}).get("duality", {})
             for v in duality_views(model, r)}
    assert views, "fixture must declare at least one duality view"
    tables = {e["table"].lower() for e in model["entities"].values()}

    stmts = generate_indexes(model, _queries(model), "duality")
    targets = _index_targets(stmts)
    assert targets, "the synthetic workload must derive at least one index"
    assert targets & views == set(), \
        f"an index targets a duality view: {sorted(targets & views)}"
    assert targets <= tables, f"index targets outside the base tables: {sorted(targets - tables)}"


def test_generated_duality_ddl_carries_no_index_on_view_and_no_vpd():
    model = json.loads(_FIXTURE.read_text())
    ddl = generate_ddl(model, "duality")
    views = {v["view"].lower()
             for r in (model.get("projections") or {}).get("duality", {})
             for v in duality_views(model, r)}
    assert _index_targets(ddl) & views == set()
    assert not _VPD.search(ddl)


# ----------------------------------------------------------- static sweep

def _findings(root: Path, subdir: str, pattern):
    hits = []
    for f in sorted((root / subdir).rglob("*")):
        if not f.is_file() or f.name == Path(__file__).name:
            continue
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if pattern(text):
            hits.append(f.relative_to(root).as_posix())
    return hits


def test_no_index_on_a_dv_named_view_anywhere(repo_root: Path):
    # The repo names duality views *_dv throughout; an index ON one of them in
    # any asset, tool, or skill is the exact confusion gate 23 pre-empts.
    def bad(text):
        return any(t.endswith("_dv") for t in _index_targets(text))
    hits = sum((_findings(repo_root, d, bad) for d in ("tooling", "skills", "assets")), [])
    assert not hits, f"index on a duality view found in: {hits}"


def test_no_vpd_call_anywhere_in_code_or_assets(repo_root: Path):
    # Row/column security goes on BASE TABLES (gate 22); the VPD package has no
    # business in anything we generate or ship as runnable SQL.
    hits = sum((_findings(repo_root, d, _VPD.search) for d in ("tooling", "assets")), [])
    assert not hits, f"VPD package call found in: {hits}"

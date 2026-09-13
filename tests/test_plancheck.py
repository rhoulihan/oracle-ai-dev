# Copyright (c) 2026 Oracle and/or its affiliates.
"""query-craft advertises "every generated query is plan-checked before delivery."

`tooling.plancheck` is the mechanism behind that sentence: ONE explain path
(shared with the optimizer's runner, so the two can never drift), a pure plan
summary an agent can reason over, and a CLI it can gate on. The canned plan
lines below are real DBMS_XPLAN BASIC output shapes.
"""

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

INDEXED = ["SELECT STATEMENT",
           "TABLE ACCESS BY INDEX ROWID| RESERVATIONS |",
           "INDEX RANGE SCAN| RES_PAX_IX |"]
SCANNED = ["SELECT STATEMENT",
           "|  1 |  TABLE ACCESS FULL| RESERVATIONS |"]


def test_summary_of_an_indexed_plan():
    from tooling.plancheck.check import summarize_plan
    s = summarize_plan(INDEXED, sql="SELECT status FROM reservations WHERE passenger_id = :1")
    assert s["uses_index"] is True
    assert s["full_scans"] == []
    assert s["warnings"] == []
    assert s["access"] == "IDX RANGE"


def test_a_full_scan_on_a_filtered_query_is_a_warning():
    from tooling.plancheck.check import summarize_plan
    s = summarize_plan(SCANNED, sql="SELECT status FROM reservations WHERE passenger_id = :1")
    assert s["uses_index"] is False
    assert s["full_scans"] == ["RESERVATIONS"]
    assert s["warnings"] and "RESERVATIONS" in s["warnings"][0]


def test_an_unfiltered_scan_is_the_honest_plan_not_a_warning():
    from tooling.plancheck.check import summarize_plan
    s = summarize_plan(SCANNED, sql="SELECT COUNT(*) FROM reservations")
    assert s["full_scans"] == ["RESERVATIONS"]
    assert s["warnings"] == []


def test_runner_and_plancheck_share_one_explain_path():
    # Single source of truth: the optimizer's measured cells and the delivery
    # gate must read plans through the SAME code, or they drift.
    import tooling.optimize.runner as runner
    from tooling.plancheck import check
    assert runner.explain is check.explain
    assert runner.plan_access is check.plan_access


def test_cli_help_runs_without_a_database():
    r = subprocess.run([sys.executable, "-m", "tooling.plancheck", "--help"],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0
    assert "plan" in r.stdout.lower()


def test_query_craft_names_the_mechanism():
    # The description promises plan-checking; the skill body must point at the
    # command that makes the promise real, not at prose.
    text = (REPO / "skills" / "query-craft" / "SKILL.md").read_text()
    assert "python -m tooling.plancheck" in text


def test_explain_supplies_null_binds_for_placeholders():
    """python-oracledb refuses even EXPLAIN PLAN FOR with unbound placeholders
    (DPY-4010) — which made the datalayer's own generated bind-form queries
    uncheckable (caught by the dot-doctrine e2e exercise). EXPLAIN needs no
    values, only bind metadata: NULLs suffice."""
    from tooling.plancheck.check import _placeholder_binds
    assert _placeholder_binds(
        "SELECT 1 FROM t WHERE a = :b0 AND c BETWEEN :lo AND :hi"
    ) == {"b0": None, "lo": None, "hi": None}
    # colons inside literals (timestamps) must not be mistaken for binds
    assert _placeholder_binds(
        "SELECT d.data FROM t d WHERE d.data.paidAt > TIMESTAMP '2026-07-07 00:00:00'"
    ) == {}

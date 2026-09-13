# Copyright (c) 2026 Oracle and/or its affiliates.
"""The noise gate must actually GATE.

measure_cell computes a per-cell coefficient of variation (cv) — how much the
trials of ONE cell disagree with each other. Before this test file existed the cv
was stored and never read: build_result declared a SEPARATION on any margin over
the fixed 5% NOISE_FLOOR, even when the cells the margin was computed from carried
8-10% cv (trials disagreeing by more than the claimed separation). DEMO-SCRIPT
recorded the consequence: a "5.5% SEPARATES" verdict whose winner flipped across
five rehearsal runs.

The rule these tests pin down:
  * NOISE_FLOOR (5%) is the FLOOR — no margin below it is ever a separation.
  * The measured cv of the cells the verdict rests on RAISES the floor: a margin
    is a separation only if it beats the worst cv among the top two designs' cells.
  * A cell whose cv exceeds benchparse.CV_GATE (10%) is untrustworthy outright and
    must be flagged loudly in the report.
"""
import sys
from pathlib import Path


def _r(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.optimize import runner
    return runner


MEAS = {
    # document leads relational by ~5.5% on every cell — above the 5% floor,
    # below the 8% cv the cells actually carry.
    "get_order":    {"relational": 1055, "document": 1000},
    "by_status":    {"relational": 1055, "document": 1000},
    "update_total": {"relational": 1055, "document": 1000},
}


def _detail(cv):
    return {p: {s: {"us": us, "cv": cv, "diag": {}} for s, us in cells.items()}
            for p, cells in MEAS.items()}


def _workload(repo_root: Path):
    from tests.test_optimize_runner import WORKLOAD
    return WORKLOAD


def test_measured_cv_raises_the_noise_floor(repo_root: Path):
    """A 5.5% margin over cells that each carry 8% cv is not a separation — the
    trials disagree with themselves by more than the designs disagree with each
    other. The effective noise floor must be max(NOISE_FLOOR, worst top-two cv)."""
    r = _r(repo_root)
    w = _workload(repo_root)
    result = r.build_result(w["model"], w["patterns"], MEAS, detail=_detail(0.08))
    assert result["margin"] > r.NOISE_FLOOR          # the old gate would pass this
    assert result["noise_floor"] >= 0.08, \
        "the measured cv of the deciding cells must raise the noise floor"
    text = r.format_report(result, detail=_detail(0.08))
    assert "TOO CLOSE TO CALL" in text, \
        "a margin inside the measured cell noise must not be presented as a decision"


def test_quiet_cells_keep_the_default_floor(repo_root: Path):
    r = _r(repo_root)
    w = _workload(repo_root)
    result = r.build_result(w["model"], w["patterns"], MEAS, detail=_detail(0.01))
    assert result["noise_floor"] == r.NOISE_FLOOR
    assert "TOO CLOSE TO CALL" not in r.format_report(result, detail=_detail(0.01))


def test_scenario_separates_respects_the_measured_noise(repo_root: Path):
    """scenario_sweep printed '<= SEPARATES' from margin >= NOISE_FLOOR alone.
    The same margin over noisy cells must NOT separate."""
    r = _r(repo_root)
    w = _workload(repo_root)
    scenarios = [{"name": "real mix", "rates": {p: pat.get("rate", 0)
                  for p, pat in ((p["name"], p) for p in w["patterns"])}}]
    noisy = r.scenario_sweep(w["model"], w["patterns"], MEAS, scenarios,
                             detail=_detail(0.08))
    clean = r.scenario_sweep(w["model"], w["patterns"], MEAS, scenarios,
                             detail=_detail(0.01))
    assert clean[0]["separates"] is True
    assert noisy[0]["separates"] is False, \
        "a 5.5% margin over 8%-cv cells flipped winners across rehearsal runs"


def test_a_cell_above_cv_gate_is_flagged_in_the_report(repo_root: Path):
    """benchparse.CV_GATE is the tool's own single-measurement trust rule: trials
    disagreeing above 10% mean the cell itself cannot be trusted. The Python path
    must apply the same rule it ships for the bash harness."""
    r = _r(repo_root)
    w = _workload(repo_root)
    from tooling.optimize.benchparse import CV_GATE
    assert r.CV_GATE == CV_GATE, "one trust gate, one source of truth"
    d = _detail(0.15)
    result = r.build_result(w["model"], w["patterns"], MEAS, detail=d)
    text = r.format_report(result, detail=d)
    assert "NOISY" in text and "cv" in text.lower(), \
        "cells above CV_GATE must be flagged loudly, not silently trusted"

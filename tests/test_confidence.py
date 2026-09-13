# Copyright (c) 2026 Oracle and/or its affiliates.
"""P11: analyze.py must flag near-ties as too-close-to-call, not trust a
coin-flip difference as a real winner."""
from tooling.optimize.analyze import optimal_shape_with_confidence


def test_clear_winner_is_high_confidence():
    m = {"q": {"document": 10.0, "relational": 50.0}}
    r = optimal_shape_with_confidence(m)["q"]
    assert r["shape"] == "document"
    assert r["too_close_to_call"] is False
    assert r["confidence"] == "high"


def test_near_tie_is_too_close_to_call():
    m = {"q": {"document": 10.0, "relational": 10.3}}  # 3% gap < 5% margin
    r = optimal_shape_with_confidence(m)["q"]
    assert r["too_close_to_call"] is True
    assert r["confidence"] == "low"
    assert r["runner_up"] == "relational"


def test_single_shape_has_no_runner_up():
    m = {"q": {"document": 10.0}}
    r = optimal_shape_with_confidence(m)["q"]
    assert r["runner_up"] is None
    assert r["too_close_to_call"] is False

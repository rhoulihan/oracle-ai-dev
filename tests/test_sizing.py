# Copyright (c) 2026 Oracle and/or its affiliates.
"""Sizing a synthetic sample for the optimizer against a large/external system:
enough rows to be representative, bounded by a storage cap."""
from tooling.optimize.sizing import recommend_sample_size, FREE_DATA_CAP_BYTES


def test_returns_requested_size_when_under_cap():
    r = recommend_sample_size(root_rows=10_000, avg_row_bytes=400, fanout=5,
                              storage_cap_bytes=FREE_DATA_CAP_BYTES)
    assert r["root_rows"] == 10_000
    assert r["capped"] is False
    assert r["total_rows"] == 10_000 * (1 + 5)
    assert r["est_bytes"] > 0


def test_scales_down_to_fit_cap():
    # Ask for far more than a tiny cap allows -> capped, root reduced, still > 0.
    r = recommend_sample_size(root_rows=10_000_000, avg_row_bytes=1_000, fanout=10,
                              storage_cap_bytes=50 * 1024 * 1024)  # 50 MB
    assert r["capped"] is True
    assert 0 < r["root_rows"] < 10_000_000
    assert r["est_bytes"] <= 50 * 1024 * 1024


def test_accounts_for_three_shapes_holding_identical_content():
    # relational + duality + document each store the logical content -> ~3x factor.
    r = recommend_sample_size(root_rows=1_000, avg_row_bytes=500, fanout=4,
                              storage_cap_bytes=FREE_DATA_CAP_BYTES, shapes=3)
    base = 1_000 * (1 + 4) * 500
    assert r["est_bytes"] >= 3 * base  # at least the raw 3x (plus index overhead)


def test_warns_when_sample_too_small_to_separate_shapes():
    r = recommend_sample_size(root_rows=50, avg_row_bytes=200, fanout=2,
                              storage_cap_bytes=FREE_DATA_CAP_BYTES)
    assert any("small" in n.lower() or "representative" in n.lower() for n in r["notes"])

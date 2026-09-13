# Copyright (c) 2026 Oracle and/or its affiliates.
"""The BENCH output contract: server-side metrics parsed from the harness line."""
from tooling.optimize.benchparse import parse_bench


def test_parses_extended_line_with_server_side_metrics():
    d = parse_bench("noise\nBENCH:document:7:cg=7:us=1234:cv=0.04\nmore")
    assert d["label"] == "document"
    assert d["primary"] == 7
    assert d["consistent_gets"] == 7
    assert d["elapsed_us"] == 1234
    assert d["cv"] == 0.04
    assert d["noisy"] is False  # cv <= 0.10


def test_flags_noisy_when_cv_over_gate():
    d = parse_bench("BENCH:relational:12:cg=12:us=900:cv=0.22")
    assert d["noisy"] is True


def test_back_compat_plain_line():
    d = parse_bench("BENCH:duality:40")
    assert d["primary"] == 40
    assert d["consistent_gets"] is None
    assert d["noisy"] is False


def test_no_match_returns_none():
    assert parse_bench("no bench here") is None


def test_comma_decimal_nls_output_still_feeds_the_noise_gate():
    """time-query.sql emits cv via TO_CHAR, so a comma-decimal NLS session (e.g. a
    German-locale SQLcl in easy/wallet mode, which pins no NLS) prints 'cv=,22'.
    The old regex tail silently failed to match, returning cv=None/noisy=False —
    a 22% variation trusted as clean. The parser must read the value, not drop it."""
    d = parse_bench("BENCH:relational:12:cg=12:us=900:cv=,22")
    assert d["cv"] == 0.22
    assert d["noisy"] is True
    assert d["consistent_gets"] == 12 and d["elapsed_us"] == 900


def test_comma_decimal_with_integer_part():
    d = parse_bench("BENCH:document:7:cg=7:us=1234:cv=1,5")
    assert d["cv"] == 1.5
    assert d["noisy"] is True

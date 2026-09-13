# Copyright (c) 2026 Oracle and/or its affiliates.
"""Result-set equivalence: two query results with the same logical content hash
equal regardless of row order, column order, or minor type formatting. Used to
gate shape comparisons (P9) and to check the data layer is consistent across
runtimes."""
from tooling.optimize.equivalence import canonical_hash, results_equivalent


def test_same_content_different_row_order_is_equal():
    a = [{"id": 1, "total": 10}, {"id": 2, "total": 20}]
    b = [{"id": 2, "total": 20}, {"id": 1, "total": 10}]
    assert canonical_hash(a) == canonical_hash(b)
    assert results_equivalent(a, b)


def test_column_order_does_not_matter():
    a = [{"id": 1, "total": 10}]
    b = [{"total": 10, "id": 1}]
    assert canonical_hash(a) == canonical_hash(b)


def test_numeric_string_normalization():
    # a driver returning 10 vs "10" vs 10.0 for the same value is equivalent
    a = [{"id": 1, "total": 10}]
    b = [{"id": "1", "total": 10.0}]
    assert canonical_hash(a) == canonical_hash(b)


def test_different_content_is_not_equal():
    a = [{"id": 1, "total": 10}]
    b = [{"id": 1, "total": 11}]
    assert canonical_hash(a) != canonical_hash(b)
    assert not results_equivalent(a, b)


def test_tuples_and_dicts_interop_by_position_keys():
    # rows as tuples canonicalize by value sequence
    a = [(1, 10), (2, 20)]
    b = [(2, 20), (1, 10)]
    assert canonical_hash(a) == canonical_hash(b)


def test_row_count_matters():
    assert not results_equivalent([{"id": 1}], [{"id": 1}, {"id": 1}])

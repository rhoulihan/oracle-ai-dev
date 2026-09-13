import sys
from pathlib import Path


def _v(repo_root: Path, obj):
    sys.path.insert(0, str(repo_root))
    from tooling.intake.validate import validate_answers
    return validate_answers(obj)


MIN_VALID = {
    "workload": "oltp",
    "entities": ["Restaurant", "MenuItem"],
    "access_patterns": [
        {"name": "menu_for_restaurant", "returns": ["Restaurant.name", "MenuItem.price"],
         "frequency": 1000, "cardinality": "1:N", "latency_budget_ms": 50, "write": "low"}
    ],
    "required_features": ["duality"],
    "deployment": "free",
}


def test_minimal_valid_answer_set_passes(repo_root: Path):
    assert _v(repo_root, MIN_VALID) == []


def test_missing_access_patterns_flagged(repo_root: Path):
    bad = {**MIN_VALID}
    del bad["access_patterns"]
    assert any("access_patterns" in m for m in _v(repo_root, bad))


def test_unknown_feature_flagged(repo_root: Path):
    bad = {**MIN_VALID, "required_features": ["time_travel"]}
    assert any("time_travel" in m for m in _v(repo_root, bad))


def test_access_pattern_needs_returns_and_frequency(repo_root: Path):
    bad = {**MIN_VALID, "access_patterns": [{"name": "x"}]}
    msgs = _v(repo_root, bad)
    assert any("returns" in m for m in msgs) and any("frequency" in m for m in msgs)


def test_scale_must_be_an_object(repo_root: Path):
    # A free-text scale answer ("12GB") must be a catchable violation here —
    # otherwise build_plan crashes with AttributeError instead of ValueError.
    for bad_scale in ("12GB", ["12GB"]):
        assert any("scale" in m for m in _v(repo_root, {**MIN_VALID, "scale": bad_scale}))


def test_scale_fields_must_be_numbers(repo_root: Path):
    bad = {**MIN_VALID, "scale": {"rows_estimate": "50000000", "doc_size_kb": 4}}
    assert any("rows_estimate" in m for m in _v(repo_root, bad))


def test_well_formed_scale_passes(repo_root: Path):
    good = {**MIN_VALID, "scale": {"rows_estimate": 50_000_000, "doc_size_kb": 4}}
    assert _v(repo_root, good) == []


def test_field_memory_scale_fields_validate(repo_root: Path):
    good = {**MIN_VALID, "scale": {
        "doc_size_p99_kb": 64, "hot_set_pct": 12, "indexes_per_collection": 4,
        "sizing_basis": "compressed TiB, replicas excluded"}}
    assert _v(repo_root, good) == []
    bad_num = {**MIN_VALID, "scale": {"doc_size_p99_kb": "64KB"}}
    assert any("doc_size_p99_kb" in m for m in _v(repo_root, bad_num))
    bad_basis = {**MIN_VALID, "scale": {"sizing_basis": 3}}
    assert any("sizing_basis" in m for m in _v(repo_root, bad_basis))


def test_returns_elements_must_be_strings(repo_root: Path):
    # A non-string in returns must be flagged here — otherwise the recommender
    # crashes with AttributeError (42.split) instead of a catchable ValueError.
    bad = {**MIN_VALID, "access_patterns": [
        {"name": "x", "returns": [42, "Customer.name"], "frequency": 1}]}
    assert any("returns" in m and "string" in m.lower() for m in _v(repo_root, bad))

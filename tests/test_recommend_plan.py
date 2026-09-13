import sys
from pathlib import Path

import pytest


def _plan(repo_root: Path, answers):
    sys.path.insert(0, str(repo_root))
    from tooling.recommend.plan import build_plan
    return build_plan(answers)


BASE = {
    "workload": "mixed", "entities": ["Order", "Customer"],
    "access_patterns": [{"name": "o", "returns": ["Order.total", "Customer.name"],
                         "frequency": 100, "cardinality": "N:1", "latency_budget_ms": 100, "write": "low"}],
    "required_features": ["mongo_api"], "deployment": "free",
}


def test_mongo_api_selects_db_ords_profile(repo_root: Path):
    p = _plan(repo_root, BASE)
    assert p["compose_profile"] == "db+ords"
    assert any("mongo" in c for c in p["configurators"])


def test_duality_selects_db_ords_profile(repo_root: Path):
    # enable-duality-graphql calls ORDS.ENABLE_SCHEMA and the GraphQL endpoint
    # is served by ORDS — a duality plan cannot ride the ORDS-less db profile.
    p = _plan(repo_root, {**BASE, "required_features": ["duality"]})
    assert p["compose_profile"] == "db+ords"


def test_every_configurator_is_runnable_on_the_plan_profile(repo_root: Path):
    # Invariant: any configurator whose script touches ORDS must be paired with
    # the ORDS-including compose profile, for EVERY feature combination.
    from itertools import combinations
    from tooling.intake.validate import FEATURES
    cfg_dir = repo_root / "assets" / "tooling" / "configure"
    feats = sorted(FEATURES)
    for n in range(len(feats) + 1):
        for combo in combinations(feats, n):
            p = _plan(repo_root, {**BASE, "required_features": list(combo)})
            for cfg in p["configurators"]:
                script = (cfg_dir / f"{cfg}.sh").read_text(encoding="utf-8")
                if "ords" in script.lower():
                    assert p["compose_profile"] == "db+ords", (
                        f"{cfg} needs ORDS but plan for {combo} chose {p['compose_profile']}")


def test_vector_via_mongo_api_on_free_is_critiqued(repo_root: Path):
    a = {**BASE, "required_features": ["mongo_api", "vector"]}
    p = _plan(repo_root, a)
    assert any("native sql" in c.lower() for c in p["critique"])


def test_oversized_dataset_warns_on_free_cap(repo_root: Path):
    a = {**BASE, "scale": {"rows_estimate": 50_000_000, "doc_size_kb": 4}}
    assert any("12" in w or "cap" in w.lower() for w in _plan(repo_root, a)["sizing_warnings"])


def test_plan_includes_per_pattern_shape(repo_root: Path):
    p = _plan(repo_root, BASE)
    assert p["shapes"][0]["strategy"] == "relational_duality"


def test_invalid_answers_rejected(repo_root: Path):
    with pytest.raises(ValueError):
        _plan(repo_root, {"workload": "oltp"})


def test_malformed_scale_raises_value_error_not_crash(repo_root: Path):
    # Agent-recorded free-text scale answers must surface as the contract's
    # ValueError, never an AttributeError/TypeError from the sizing math.
    for bad_scale in ("12GB", ["12GB"], {"rows_estimate": "50000000", "doc_size_kb": 4}):
        with pytest.raises(ValueError):
            _plan(repo_root, {**BASE, "scale": bad_scale})

# Copyright (c) 2026 Oracle and/or its affiliates.
"""Every test module gated on ORACLE_AI_DEV_LIVE must carry the `live` marker.

Without the marker, `pytest -m live` — the documented way to run the live
suite — silently deselects the module: it skips under plain `pytest` and is
deselected under `-m live`, so it runs in neither mode. This lint failed for
24 of 36 live tests (test_pattern_catalog_live.py, test_stack_validation.py)
when introduced during the 2026-07-14 repo review.
"""
import re
from pathlib import Path

TESTS = Path(__file__).parent

def test_live_gated_modules_carry_live_marker():
    missing = []
    for path in sorted(TESTS.glob("test_*.py")):
        text = path.read_text()
        if "ORACLE_AI_DEV_LIVE" not in text:
            continue
        # Accept either a module-level pytestmark list containing pytest.mark.live
        # or per-test @pytest.mark.live decorators.
        if not re.search(r"pytest\.mark\.live\b", text):
            missing.append(path.name)
    assert not missing, (
        "live-gated test modules missing the `live` marker "
        f"(invisible to `pytest -m live`): {missing}"
    )


def test_shared_container_fixture_users_carry_the_marker():
    """The nightly runs the live tier in two serialized passes because the
    compose files pin ONE container name (oracle-ai-dev-db): self-managing
    stacks first (`-m "live and not shared_container"`), then the modules
    that share the session `live_container` fixture. Before this contract
    the tier was green by ALPHABETICAL ACCIDENT — the fixture users happened
    to collect after every self-manager — and adding
    test_live_hybrid_partition.py (h < i) booted the session stack early,
    held the name, and killed ten later `compose up`s with a name Conflict
    (nightlies of 2026-08-01/02). A fixture user without the marker would
    re-create exactly that race."""
    missing = []
    for path in sorted(TESTS.glob("test_*.py")):
        text = path.read_text()
        if "live_container" not in text or path.name in (
                "conftest.py", "test_live_marker_lint.py"):
            continue
        if not re.search(r"pytest\.mark\.shared_container\b", text):
            missing.append(path.name)
    assert not missing, (
        "modules using the session live_container fixture must carry "
        f"pytest.mark.shared_container (two-pass nightly contract): {missing}"
    )


def test_the_shared_container_detector_catches_the_planted_defect():
    planted = 'def db(live_container):\n    ...'
    assert "live_container" in planted and not re.search(
        r"pytest\.mark\.shared_container\b", planted), \
        "the detector must catch a fixture user without the marker"

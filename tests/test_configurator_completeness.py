import subprocess
import sys
from pathlib import Path


def _configurator_stems(repo_root: Path):
    return {p.stem for p in (repo_root / "assets/tooling/configure").glob("*.sh")}


def test_every_feature_map_configurator_exists(repo_root: Path):
    # Every configurator the recommender points a developer at must be a real script.
    sys.path.insert(0, str(repo_root))
    from tooling.recommend.plan import _FEATURE_MAP, build_plan  # noqa: F401
    referenced = {cfg for (_path, cfg) in _FEATURE_MAP.values()}
    referenced.add("create-plugin-user")  # always in the plan
    missing = referenced - _configurator_stems(repo_root)
    assert not missing, f"recommender references configurators that don't exist: {missing}"


def test_all_configurators_pass_shellcheck(repo_root: Path):
    scripts = list((repo_root / "assets/tooling/configure").glob("*.sh"))
    r = subprocess.run(["shellcheck", *map(str, scripts)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_every_configurator_emits_an_assert(repo_root: Path):
    for sh in (repo_root / "assets/tooling/configure").glob("*.sh"):
        if sh.name == "doctor.sh":
            continue
        assert "assert " in sh.read_text(), f"{sh.name} must emit an ASSERT result"

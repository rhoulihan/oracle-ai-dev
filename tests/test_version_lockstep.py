import json
import subprocess
from pathlib import Path


def test_all_registered_manifests_share_one_version(repo_root: Path):
    reg = json.loads((repo_root / ".version-bump.json").read_text())
    paths = reg["manifests"]
    versions = {p: json.loads((repo_root / p).read_text())["version"] for p in paths}
    assert len(set(versions.values())) == 1, f"version drift: {versions}"


def test_registry_covers_both_plugin_manifests(repo_root: Path):
    paths = set(json.loads((repo_root / ".version-bump.json").read_text())["manifests"])
    assert ".claude-plugin/plugin.json" in paths
    assert ".codex-plugin/plugin.json" in paths


def test_bump_script_is_executable(repo_root: Path):
    s = repo_root / "scripts" / "bump-version.sh"
    assert s.is_file()
    assert s.stat().st_mode & 0o111, "bump-version.sh must be executable"


def test_all_shell_scripts_executable_in_git_index(repo_root: Path):
    # Guards against the executable bit being lost on filesystems with
    # core.filemode off (e.g. Windows-mounted /mnt/c under WSL2): the git
    # index mode must be 100755 so scripts stay runnable on CI checkout.
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-s", "*.sh"],
        capture_output=True, text=True, check=True).stdout
    non_exec = [ln.split("\t")[-1] for ln in out.splitlines() if not ln.startswith("100755")]
    assert not non_exec, f"shell scripts missing +x in git index: {non_exec}"

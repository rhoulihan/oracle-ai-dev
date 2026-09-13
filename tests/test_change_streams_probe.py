import subprocess
from pathlib import Path


def test_probe_passes_shellcheck(repo_root: Path):
    r = subprocess.run(
        ["shellcheck", str(repo_root / "assets/verify/verify-change-streams.sh")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_probe_emits_change_streams_assert(repo_root: Path):
    sh = (repo_root / "assets/verify/verify-change-streams.sh").read_text()
    assert "change_streams" in sh
    assert "assert " in sh or "ASSERT:" in sh

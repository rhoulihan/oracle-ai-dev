import re

from pathlib import Path


def test_ci_workflow_runs_pytest_and_shellcheck(repo_root: Path):
    text = (repo_root / ".github/workflows/ci.yml").read_text()
    assert "pytest" in text
    assert "shellcheck" in text


def test_agents_md_within_size_cap(repo_root: Path):
    assert (repo_root / "AGENTS.md").stat().st_size <= 32 * 1024


def test_readme_documents_both_platforms(repo_root: Path):
    r = (repo_root / "README.md").read_text().lower()
    assert "claude" in r and "codex" in r


def test_install_has_both_marketplace_commands(repo_root: Path):
    t = (repo_root / "INSTALL.md").read_text()
    assert "plugin marketplace add" in t
    assert "codex plugin marketplace add" in t


def test_nightly_live_workflow_has_headroom_and_names_slow_tests(repo_root: Path):
    """2026-08-09: a slow-infrastructure morning stretched pass 1 alone to
    59m02s (normal full run: 21-27m) — it PASSED, then the 60-minute job
    ceiling killed pass 2 before it ran a test. The ceiling must clear the
    observed worst case with room for both passes, and the passes must
    report durations so the next slow morning names its cause."""
    text = (repo_root / ".github/workflows/live.yml").read_text()
    m = re.search(r"timeout-minutes:\s*(\d+)", text)
    assert m, "the live job must declare an explicit timeout"
    assert int(m.group(1)) >= 120, "60m starved pass 2 on a slow morning"
    assert text.count("--durations") >= 2, "both passes must report durations"


def test_nightly_live_workflow_notifies_on_success_too(repo_root: Path):
    """GitHub emails only on failure by default, so a green nightly is
    indistinguishable from one that never ran. The workflow must report BOTH
    outcomes (an always() step commenting a rolling status issue) — and hold
    the issues:write permission that comment needs."""
    text = (repo_root / ".github/workflows/live.yml").read_text()
    assert "if: always()" in text
    assert "gh issue comment" in text
    assert "issues: write" in text

from pathlib import Path

SKILL = "skills/sql-json-dev"


def test_skill_exists(repo_root: Path):
    assert (repo_root / SKILL / "SKILL.md").is_file()


def test_indexing_reference_states_multivalue_vs_search_rule(repo_root: Path):
    idx = (repo_root / SKILL / "references/json-indexing.md").read_text().lower()
    assert "multivalue" in idx
    assert "search index" in idx
    # the performance cliff and the VARCHAR2 default gotcha must be documented
    assert "json_value" in idx


def test_sync_on_commit_gotcha_present(repo_root: Path):
    idx = (repo_root / SKILL / "references/json-indexing.md").read_text().lower()
    assert "sync" in idx and "commit" in idx

from pathlib import Path

S = "skills/soda-dev"


def test_skill_exists(repo_root: Path):
    assert (repo_root / S / "SKILL.md").is_file()


def test_status_not_deprecated_and_thick_mode(repo_root: Path):
    s = (repo_root / S / "references/soda-status.md").read_text().lower()
    assert "not deprecated" in s
    assert "thick" in s
    assert "mongo" in s  # routes modern app code to the Mongo API


def test_in_db_api_shows_create_index_gotcha(repo_root: Path):
    a = (repo_root / S / "references/in-db-api.md").read_text().lower()
    assert "dbms_soda" in a
    assert "commit" in a and ("ora-00054" in a or "create_index" in a)

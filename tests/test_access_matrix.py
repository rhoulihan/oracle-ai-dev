from pathlib import Path

S = "skills/oracle-ai-setup"


def test_access_matrix_covers_each_api(repo_root: Path):
    a = (repo_root / S / "references/access-matrix.md").read_text().lower()
    assert "1521" in a and "27017" in a  # SQL + Mongo ports
    assert "sql" in a and "mongo" in a and "rest" in a
    assert "service" in a  # service name for SQL connections


def test_setup_skill_links_connection_kit(repo_root: Path):
    s = (repo_root / S / "SKILL.md").read_text().lower()
    assert "connection" in s and "kit" in s
    assert "access-matrix" in s or "access matrix" in s

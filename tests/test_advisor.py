from pathlib import Path

SKILL = "skills/oracle-ai-dev"


def test_advisor_reference_exists(repo_root: Path):
    assert (repo_root / SKILL / "references/advisor.md").is_file()


def test_advisor_documents_intake_recommend_critique(repo_root: Path):
    a = (repo_root / SKILL / "references/advisor.md").read_text().lower()
    assert "intake" in a
    assert "recommend" in a
    assert "critique" in a or "feedback" in a


def test_router_skill_links_to_advisor(repo_root: Path):
    s = (repo_root / SKILL / "SKILL.md").read_text()
    assert "advisor" in s.lower()

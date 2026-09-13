from pathlib import Path

S = "skills/ai-agent-dev"


def test_skill_exists(repo_root: Path):
    assert (repo_root / S / "SKILL.md").is_file()


def test_client_side_covers_store_and_mcp_and_approval(repo_root: Path):
    c = (repo_root / S / "references/client-side.md").read_text().lower()
    assert "vector" in c and "mcp" in c
    assert "approval" in c or "approve" in c


def test_in_db_select_ai_notes_manual_install(repo_root: Path):
    s = (repo_root / S / "references/in-db-select-ai.md").read_text().lower()
    assert "dbms_cloud" in s
    assert "not preinstalled" in s or "manual" in s or "23.7" in s

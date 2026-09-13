from pathlib import Path

# The 12 skills the spec defines (S0-S11), plus the mneme-generated fact
# index (machinery of the knowledge-plugin adoption, not a spec skill), plus
# two skills adopted from a knowledge harvest (ADB's DynamoDB-compatible API
# and headless ORDS REST-Enabled SQL) — capabilities the original spec predates.
EXPECTED_SKILLS = {
    "oracle-ai-dev", "oracle-ai-setup", "sqlcl-mcp-setup", "oracle-data-modeling",
    "sql-json-dev", "json-duality-dev", "mongodb-api-dev", "soda-dev",
    "vector-rag-dev", "ai-agent-dev", "query-craft", "query-tuning",
    "knowledge-index",
    "adb-dynamodb-api", "ords-rest-sql-headless-adb",
}


def _skill_names(repo_root: Path):
    return {p.name for p in (repo_root / "skills").iterdir() if (p / "SKILL.md").is_file()}


def test_all_spec_skills_present(repo_root: Path):
    missing = EXPECTED_SKILLS - _skill_names(repo_root)
    assert not missing, f"spec skills not yet built: {missing}"


def test_no_unexpected_skills(repo_root: Path):
    extra = _skill_names(repo_root) - EXPECTED_SKILLS
    assert not extra, f"unexpected skills (update EXPECTED_SKILLS or the spec): {extra}"


def test_readme_lists_the_router_and_setup(repo_root: Path):
    r = (repo_root / "README.md").read_text().lower()
    assert "oracle-ai-dev" in r and "oracle-ai-setup" in r

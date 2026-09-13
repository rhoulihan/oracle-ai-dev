# Copyright (c) 2026 Oracle and/or its affiliates.
"""Documentation completeness: the README, multi-level help, and architecture doc
must cover the system as built."""
from pathlib import Path

SKILLS = ["oracle-ai-setup", "sqlcl-mcp-setup", "oracle-data-modeling",
          "sql-json-dev", "json-duality-dev", "mongodb-api-dev", "soda-dev",
          "vector-rag-dev", "ai-agent-dev", "query-craft", "query-tuning",
    "adb-dynamodb-api", "ords-rest-sql-headless-adb"]


def test_readme_covers_the_system(repo_root: Path):
    r = (repo_root / "README.md").read_text().lower()
    for topic in ("optimization", "data layer", "wallet", "safety",
                  "unified model theory", "write amplification", "datalayer"):
        assert topic in r, f"README missing {topic!r}"
    for s in SKILLS:
        assert s in r, f"README missing skill {s!r}"


def test_no_false_claim_that_setup_needs_no_sqlcl(repo_root: Path):
    """Every setup configurator (create-plugin-user, doctor, enable-*) and run-sql's
    easy/wallet modes shell out to a bare `sql` on PATH — and the plugin's
    self-installed copy is never put on PATH. So the claim that setup 'works without
    SQLcl or Java at all' is false: on a fresh machine the README quickstart step 2
    fails with command-not-found. The docs must state the configurators' real
    requirement instead."""
    readme = (repo_root / "README.md").read_text()
    assert "works without SQLcl or Java at all" not in readme
    assert "`sql` on PATH" in readme, \
        "README must state that the setup configurators shell out to `sql` on PATH"
    launcher = (repo_root / "scripts/sqlcl-mcp.sh").read_text()
    assert "(setup," not in launcher, \
        "the launcher's fallback message must not list setup as SQLcl-free"


def test_help_covers_every_skill(repo_root: Path):
    h = (repo_root / "skills/oracle-ai-dev/references/help.md").read_text()
    for s in SKILLS:
        assert s in h, f"help.md missing skill {s!r}"
    for level in ("Level 1", "Level 2", "Level 3", "Level 4"):
        assert level in h


def test_architecture_doc_covers_layers(repo_root: Path):
    a = (repo_root / "docs/ARCHITECTURE.md").read_text().lower()
    for topic in ("skills", "tooling", "assets", "benchmark", "dual-platform"):
        assert topic in a

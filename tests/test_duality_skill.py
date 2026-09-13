from pathlib import Path

S = "skills/json-duality-dev"


def test_skill_exists(repo_root: Path):
    assert (repo_root / S / "SKILL.md").is_file()


def test_design_covers_ora_40477_workaround(repo_root: Path):
    d = (repo_root / S / "references/duality-design.md").read_text().lower()
    assert "ora-40477" in d
    assert "full" in d and "pk" in d


def test_design_flags_write_amplification(repo_root: Path):
    d = (repo_root / S / "references/duality-design.md").read_text().lower()
    assert "read-time join" in d or "write" in d


def test_limitations_name_coalesce_and_sql_view_fallback(repo_root: Path):
    lim = (repo_root / S / "references/limitations.md").read_text().lower()
    assert "coalesce" in lim
    assert "sql view" in lim or "traditional view" in lim

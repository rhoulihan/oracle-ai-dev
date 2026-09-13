from pathlib import Path

S = "skills/query-tuning"


def test_skill_exists(repo_root: Path):
    assert (repo_root / S / "SKILL.md").is_file()


def test_tuning_loop_documented(repo_root: Path):
    t = (repo_root / S / "references/tuning-loop.md").read_text().lower()
    assert "explain" in t or "dbms_xplan" in t
    assert "re-measure" in t or "measure" in t


def test_advisors_state_packs_on_free_and_exclusions(repo_root: Path):
    a = (repo_root / S / "references/advisors.md").read_text().lower()
    assert "tuning pack" in a and "diagnostics pack" in a
    assert "free" in a
    # must NOT recommend the not-licensed features
    assert "real application testing" in a or "automatic indexing" in a


def test_awr_on_free_gotcha(repo_root: Path):
    w = (repo_root / S / "references/awr-on-free.md").read_text().lower()
    assert "create_snapshot" in w
    assert "freepdb1" in w or "pdb" in w

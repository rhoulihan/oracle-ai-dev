import sys
from pathlib import Path


def _validate(repo_root: Path, skill_dir: Path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from skill_frontmatter import validate_skill
    return validate_skill(skill_dir)


def _mk(tmp_path, name, fm, body="Short body."):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n{body}\n")
    return d


def test_valid_skill_passes(repo_root, tmp_path):
    d = _mk(tmp_path, "my-skill", "name: my-skill\ndescription: Use when testing.")
    assert _validate(repo_root, d) == []


def test_name_must_match_dir(repo_root, tmp_path):
    d = _mk(tmp_path, "my-skill", "name: other-name\ndescription: Use when testing.")
    assert any("name" in v for v in _validate(repo_root, d))


def test_extra_frontmatter_key_flagged(repo_root, tmp_path):
    d = _mk(tmp_path, "my-skill", "name: my-skill\ndescription: Use when testing.\nversion: 1")
    assert any("frontmatter" in v.lower() for v in _validate(repo_root, d))

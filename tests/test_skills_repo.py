import sys
from pathlib import Path


def _skill_dirs(repo_root: Path):
    return sorted(p for p in (repo_root / "skills").iterdir() if (p / "SKILL.md").is_file())


def _lints(repo_root):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from skill_frontmatter import validate_skill
    from banned_strings import scan
    from link_check import check_links
    return validate_skill, scan, check_links


def test_at_least_router_skill_exists(repo_root: Path):
    names = [p.name for p in _skill_dirs(repo_root)]
    assert "oracle-ai-dev" in names


def test_all_skills_pass_frontmatter(repo_root: Path):
    validate_skill, _, _ = _lints(repo_root)
    problems = {d.name: validate_skill(d) for d in _skill_dirs(repo_root)}
    assert all(v == [] for v in problems.values()), problems


def test_all_skill_bodies_clean_of_banned_terms(repo_root: Path):
    import sys as _sys
    _sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from banned_strings import scan_tree
    problems = scan_tree(repo_root / "skills")  # recurses into references/*.md too
    assert not problems, problems


def test_all_skill_links_resolve(repo_root: Path):
    _, _, check_links = _lints(repo_root)
    problems = {}
    for d in _skill_dirs(repo_root):
        for md in d.rglob("*.md"):
            b = check_links(repo_root, md)
            if b:
                problems[str(md)] = b
    assert not problems, problems


def test_setup_skill_present(repo_root: Path):
    assert (repo_root / "skills/oracle-ai-setup/SKILL.md").is_file()

from pathlib import Path


def test_agents_skills_mirror_resolves_to_skills(repo_root: Path):
    # Codex scans .agents/skills/ for zero-install cloned-repo use. It must
    # resolve to the same skills as the canonical skills/ directory.
    mirror = repo_root / ".agents" / "skills"
    assert mirror.exists(), ".agents/skills mirror missing"
    canonical = {p.name for p in (repo_root / "skills").iterdir() if (p / "SKILL.md").is_file()}
    mirrored = {p.name for p in mirror.iterdir() if (p / "SKILL.md").is_file()}
    assert mirrored == canonical, f"mirror drift: {canonical ^ mirrored}"

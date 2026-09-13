from pathlib import Path

S = "skills/oracle-ai-dev"


def test_help_has_four_levels(repo_root: Path):
    h = (repo_root / S / "references/help.md").read_text().lower()
    for level in ("overview", "common tasks", "reference", "troubleshooting"):
        assert level in h, f"help.md missing the {level!r} level"


def test_troubleshooting_covers_hit_errors(repo_root: Path):
    t = (repo_root / S / "references/troubleshooting.md").read_text().lower()
    for err in ("ora-40477", "ora-06598", "ora-43853", "ora-51962", "ora-01403"):
        assert err in t, f"troubleshooting.md missing {err}"


def test_router_links_help(repo_root: Path):
    s = (repo_root / S / "SKILL.md").read_text().lower()
    assert "help" in s

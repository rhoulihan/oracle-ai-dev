import sys
from pathlib import Path


def _scan(repo_root: Path, rel: str):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from banned_strings import scan
    return scan((repo_root / rel).read_text())


def test_bare_23ai_is_flagged(repo_root: Path):
    assert _scan(repo_root, "tests/lint/fixtures/bad_23ai.md")


def test_23ai_under_version_notes_is_exempt(repo_root: Path):
    assert _scan(repo_root, "tests/lint/fixtures/good_versionnote.md") == []


def test_uppercase_23ai_is_flagged(repo_root: Path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from banned_strings import scan
    assert scan("Run the 23AI container.")


def test_scan_tree_catches_reference_files(repo_root: Path, tmp_path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from banned_strings import scan_tree
    (tmp_path / "references").mkdir()
    (tmp_path / "SKILL.md").write_text("clean body")
    (tmp_path / "references" / "bad.md").write_text("Run the 23ai container.")
    problems = scan_tree(tmp_path)
    assert problems, "scan_tree must recurse into references/*.md"


# --- confidential-token lint ---------------------------------------------------
# The real register lives OUTSIDE the repository (maintainer-local plaintext file;
# see banned_strings._register_path). Shipping hashes was rejected by the
# 2026-07-15 adversarial review: unsalted single-word SHA-256 is trivially
# reversible. The mechanism is proven with sentinel tokens; the real register is
# exercised wherever it is installed (maintainer machines, private release CI).

def _lint(repo_root: Path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    import banned_strings
    return banned_strings


def test_confidential_scan_flags_a_planted_token(repo_root: Path, tmp_path):
    b = _lint(repo_root)
    planted = tmp_path / "leak.md"
    planted.write_text("The PoC ran at Plutonium in March.\n")
    hits = b.scan_confidential(planted.read_text(), words={"plutonium"})
    assert hits and "line 1" in hits[0]


def test_confidential_scan_flags_a_planted_word_pair(repo_root: Path, tmp_path):
    b = _lint(repo_root)
    planted = tmp_path / "leak.md"
    planted.write_text("A session at Acme Corp last year.\n")
    hits = b.scan_confidential(planted.read_text(), words=frozenset(),
                               pairs={"acme corp"})
    assert hits


def test_confidential_scan_matches_whole_words_only(repo_root: Path):
    b = _lint(repo_root)
    assert b.scan_confidential("acmeish and preacme text", words={"acme"}) == []


def test_confidential_scan_is_case_insensitive(repo_root: Path):
    b = _lint(repo_root)
    assert b.scan_confidential("PLUTONIUM", words={"plutonium"})


def test_confidential_scan_catches_numbered_hostname_instances(repo_root: Path):
    # Register entries include hostname PREFIXES; hosts appear as prefix01/02.
    b = _lint(repo_root)
    assert b.scan_confidential("db host PLUTONIUM07 down", words={"plutonium"})


def test_confidential_register_never_ships_in_repo(repo_root: Path):
    """The register file must not exist anywhere under the repository, and the
    lint module must contain no name-derived data (no hex digests)."""
    import re as _re
    hits = [p for p in repo_root.rglob("confidential-register*") if ".git" not in p.parts]
    assert hits == [], f"register file tracked inside the repo: {hits}"
    src = (repo_root / "tests" / "lint" / "banned_strings.py").read_text()
    assert not _re.search(r"[0-9a-f]{64}", src), "hex digests found in shipped lint"


def test_confidential_scan_noop_without_register(repo_root: Path, monkeypatch):
    b = _lint(repo_root)
    monkeypatch.setenv("ORACLE_AI_DEV_CONFIDENTIAL_REGISTER", "/nonexistent/register")
    words, pairs = b._load_register()
    assert words == frozenset() and pairs == frozenset()


def test_confidential_tree_scan_flags_a_planted_file(repo_root: Path, tmp_path):
    b = _lint(repo_root)
    (tmp_path / "skills").mkdir()
    (tmp_path / "README.md").write_text("clean")
    (tmp_path / "skills" / "bad.md").write_text("word Plutonium here")
    problems = b.scan_confidential_tree(tmp_path, words={"plutonium"})
    assert problems, "tree scan must recurse into skills/**"


def test_confidential_tree_scan_skips_research_dossiers(repo_root: Path, tmp_path):
    b = _lint(repo_root)
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "research" / "dossier.md").write_text("Plutonium")
    (tmp_path / "docs" / "other.md").write_text("clean")
    assert b.scan_confidential_tree(tmp_path, words={"plutonium"}) == {}


def test_repo_tree_carries_no_confidential_tokens(repo_root: Path):
    b = _lint(repo_root)
    problems = b.scan_confidential_tree(repo_root)
    assert problems == {}, problems

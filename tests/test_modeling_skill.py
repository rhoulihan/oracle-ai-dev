from pathlib import Path

SKILL = "skills/oracle-data-modeling"


def test_methodology_has_umt_vocabulary(repo_root: Path):
    m = (repo_root / SKILL / "references/umt-methodology.md").read_text()
    for term in ["Canonical Form", "Projected Shape", "Shape Projection", "Access Surface"]:
        assert term in m, f"UMT vocabulary term missing: {term}"


def test_methodology_names_the_three_strategies(repo_root: Path):
    m = (repo_root / SKILL / "references/umt-methodology.md").read_text().lower()
    assert "json collection" in m
    assert "single collection" in m
    assert "duality" in m


def test_skill_supports_greenfield_and_critique(repo_root: Path):
    s = (repo_root / SKILL / "SKILL.md").read_text().lower()
    assert "intake" in s
    assert "review" in s or "critique" in s or "feedback" in s


def test_decision_rules_present(repo_root: Path):
    r = (repo_root / SKILL / "references/decision-rules.md").read_text().lower()
    assert "embed" in r and "reference" in r


def test_optimization_workflow_documented(repo_root: Path):
    o = (repo_root / SKILL / "references/optimization.md").read_text().lower()
    assert "benchmark" in o
    assert "frequenc" in o
    assert "break" in o  # break-point / breakpoint
    assert "tooling/optimize" in o


def test_skill_links_to_optimization(repo_root: Path):
    s = (repo_root / SKILL / "SKILL.md").read_text().lower()
    assert "optimization" in s


def test_optimization_documents_general_generation(repo_root: Path):
    o = (repo_root / SKILL / "references/optimization.md").read_text().lower()
    assert "modelspec" in o
    assert "tooling/generate" in o
    assert "any model" in o or "arbitrary" in o


def test_optimization_documents_write_amplification_and_options(repo_root: Path):
    o = (repo_root / SKILL / "references/optimization.md").read_text().lower()
    assert "write amplification" in o
    assert "breakpoint" in o or "break-point" in o
    assert "options" in o


def test_optimization_pack_licensing_matches_gap1(repo_root: Path):
    # gap-1 (runtime-verified): Diagnostics AND Tuning packs are INCLUDED on
    # 26ai Free — CONTROL_MANAGEMENT_PACK_ACCESS defaults to DIAGNOSTIC+TUNING.
    # The reference must not claim the packs are unavailable/unlicensed on Free.
    o = (repo_root / SKILL / "references/optimization.md").read_text().lower()
    assert "unavailable on free" not in o
    assert "included on 26ai free" in o or "included on free" in o
    assert "diagnostic+tuning" in o


def test_duality_design_gates_reference(repo_root: Path):
    # W1 (2026-07-15 field-memories spec, themes T1+T2): the mechanical
    # duality-view rulebook — checklist-styled gates, each RULE / WHY / CHECK.
    f = repo_root / SKILL / "references/duality-design-gates.md"
    assert f.is_file(), "references/duality-design-gates.md is missing"
    g = f.read_text()
    assert "## Sources" in g
    # Every gate carries the three-part shape; ~20 gates ship, never fewer than 18.
    assert g.count("**RULE**") >= 18, "fewer than 18 gates (RULE lines)"
    assert g.count("**CHECK**") >= 18, "every gate needs a CHECK"
    assert g.count("**WHY**") >= 18, "every gate needs a WHY"
    for section in ("Structural gates", "Write-path gates",
                    "Projection-scope gates", "Packaging"):
        assert section in g, f"missing section: {section}"


def _field_lessons(repo_root: Path) -> str:
    return (repo_root / SKILL / "references/field-lessons.md").read_text()


def test_field_lessons_exists_with_entry_format(repo_root: Path):
    import re
    f = _field_lessons(repo_root)
    # every war story ships as Lesson / What happened / Apply
    assert len(re.findall(r"\*\*Lesson\.?\*\*", f)) >= 12
    assert len(re.findall(r"\*\*What happened\.?\*\*", f)) >= 12
    assert len(re.findall(r"\*\*Apply\.?\*\*", f)) >= 12
    assert "## Sources" in f


def test_field_lessons_quotes_corrected_suite_headline(repo_root: Path):
    f = _field_lessons(repo_root)
    # the production-cardinality result is the only quotable headline; figures ship
    # ROUNDED (2026-07-15 PII review: exact constants fingerprint their source)
    assert "~0.16" in f
    assert "~0.83" in f
    import re
    assert not re.search(r"0\.\d{3}\s*s", f), "unrounded seconds figure shipped"


def test_field_lessons_wrong_scale_number_stays_in_the_cautionary_tale(repo_root: Path):
    f = _field_lessons(repo_root)
    # 0.11x-second figures were measured at 213x-understated cardinality and may
    # appear ONLY inside the wrong-scale cautionary-tale entry
    sections = f.split("\n## ")
    tale = [s for s in sections if "wrong scale" in s.splitlines()[0].lower()]
    assert len(tale) == 1, "expected exactly one wrong-scale cautionary-tale entry"
    outside = [s for s in sections if s not in tale]
    assert "0.11" in tale[0]
    assert not any("0.11" in s for s in outside), "0.11x figure leaked outside the cautionary tale"


def test_field_lessons_free_of_banned_provenance(repo_root: Path):
    """Do-not-cite bench figures and confidential identities must never ship.
    Identities are checked via the maintainer-local register loaded by
    tests/lint/banned_strings.py — listing them in plaintext here would itself
    leak them into the public repo (caught by the 2026-07-15 PII sweep)."""
    import sys
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from banned_strings import scan_confidential
    f = _field_lessons(repo_root)
    low = f.lower()
    for banned in ["477", "165x", "165\u00d7"]:  # numbers, not identities — plaintext is fine
        assert banned not in low, f"do-not-cite figure shipped: {banned}"
    assert scan_confidential(f) == [], "confidential token shipped in field-lessons"


def test_patterns_reference_is_neutral_and_measured(repo_root: Path):
    p = (repo_root / SKILL / "references/patterns.md").read_text().lower()
    assert "embedded document" in p and "duality" in p and "normalized" in p
    assert "measured" in p or "benchmark" in p  # winner is measured
    assert "mongodb" not in p  # generic, no branding
    s = (repo_root / SKILL / "SKILL.md").read_text().lower()
    assert "patterns" in s

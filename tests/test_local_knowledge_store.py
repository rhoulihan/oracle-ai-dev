# Copyright (c) 2026 Oracle and/or its affiliates.
"""Phase A of the local-knowledge store keeps its own shape.

Spec: docs/specs/2026-07-15-local-knowledge-spec.md (v2) — §2 lessons entry
format, §2.5 the gap-fill flow, §3/§3.5 standards entry format and the
adopted-principles unification, §5 item 6 (the lints), §6 verification.

The store is plain markdown a team commits, so nothing but a lint stands
between it and rot. Each detector below kills a named defect class:

* a lessons entry that drops **Apply.** — a war story with no instruction,
  which an agent cannot act on;
* an `active` standard with no **Consequence.** line — the spec's named lint:
  a directive the user approved without ever being shown what it costs them;
* a `status:` outside its ledger's legend — the file IS the ledger, so an
  unknown status is an entry in no state at all;
* a `category:` outside the allowlist — `process` in particular, because
  gap-fill adoptions land there (§3.5) and a typo silently orphans them;
* a template that ships with a real entry in it — a starter file that seeds
  every project with someone else's standard.

Phase A ships no `tooling/` code, so the detectors live here as pure
functions and prove themselves against planted defects (the house pattern —
see tests/test_docs_reference.py and tests/test_live_marker_lint.py).
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = "skills/oracle-data-modeling"
LESSONS_TPL = "assets/templates/lessons.md"
STANDARDS_TPL = "assets/templates/standards.md"
PRINCIPLES = f"{SKILL}/references/operating-principles.md"
LOCAL_KNOWLEDGE = f"{SKILL}/references/local-knowledge.md"

LESSON_STATUSES = ("local", "offered", "submitted", "declined")
STANDARD_STATUSES = ("proposed", "active", "retired", "declined")
CATEGORIES = ("naming", "shape", "keys", "indexing", "integrity", "process")

_STATUS = re.compile(r"^status:\s*(\S+)", re.M)
_CATEGORY = re.compile(r"^category:\s*(\S+)", re.M)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _text(rel: str) -> str:
    path = REPO / rel
    if not path.is_file():
        pytest.fail(f"missing artifact: {rel}")
    return path.read_text()


# --- detectors ---------------------------------------------------------------

def _lint_lesson_entry(text: str) -> list:
    """§2 entry format. Returns violations; empty means clean."""
    bad = []
    m = _STATUS.search(text)
    if not m:
        bad.append("missing status:")
    elif m.group(1) not in LESSON_STATUSES:
        bad.append(f"status {m.group(1)!r} outside the lessons legend")
    if not re.search(r"^captured:", text, re.M):
        bad.append("missing captured:")
    for section in ("**Lesson.**", "**What happened.**", "**Apply.**"):
        if section not in text:
            bad.append(f"missing {section}")
    return bad


def _lint_standard_entry(text: str) -> list:
    """§3 entry format, including the consequence-line-required rule."""
    bad = []
    m = _STATUS.search(text)
    if not m:
        bad.append("missing status:")
    elif m.group(1) not in STANDARD_STATUSES:
        bad.append(f"status {m.group(1)!r} outside the standards legend")
    c = _CATEGORY.search(text)
    if not c:
        bad.append("missing category:")
    elif c.group(1) not in CATEGORIES:
        bad.append(f"category {c.group(1)!r} outside the allowlist")
    for section in ("**Directive.**", "**Enforcement.**"):
        if section not in text:
            bad.append(f"missing {section}")
    if m and m.group(1) == "active" and "**Consequence.**" not in text:
        bad.append("active standard without **Consequence.**")
    return bad


def _real_entries(text: str) -> list:
    """Entry headings that survive comment-stripping — i.e. not examples."""
    return [ln for ln in _COMMENT.sub("", text).splitlines()
            if ln.startswith("## ")]


# --- 1. template integrity ---------------------------------------------------

def test_lessons_template_carries_its_legend_and_the_opt_out():
    text = _text(LESSONS_TPL)
    assert "status: local | offered | submitted | declined" in text
    assert "contribution: never" in text, "the opt-out line must be documented"


def test_standards_template_carries_legend_categories_and_gapfill_marker():
    text = _text(STANDARDS_TPL)
    for status in STANDARD_STATUSES:
        assert status in text, f"the standards legend must name {status!r}"
    for category in CATEGORIES:
        assert category in text, f"the category list must name {category!r}"
    assert "gapfill:" in text, "the gap-fill marker semantics must be documented"


# --- 2. entry-format detectors, each proven against a planted defect ---------

_GOOD_LESSON = """## partition-by-type-beat-the-flat-heap
status: local
captured: 2026-07-20 · context: 26ai RU, document, mixed read/write
**Lesson.** Partition by type before you reach for a second collection.
**What happened.** 4.1 s -> 0.4 s on the same 20M rows.
**Apply.** Try the partition first and measure it.
"""

_GOOD_STANDARD = """## tables-are-plural-snake-case
status: active
category: naming
**Directive.** Table names are plural snake_case.
**Enforcement.** Generated DDL is renamed to match before it is shown.
**Consequence.** Generated names differ from the entity names in the model.
"""


def test_well_formed_entries_lint_clean():
    assert _lint_lesson_entry(_GOOD_LESSON) == []
    assert _lint_standard_entry(_GOOD_STANDARD) == []


def test_lesson_detector_catches_the_planted_missing_apply():
    planted = _GOOD_LESSON.replace(
        "**Apply.** Try the partition first and measure it.\n", "")
    assert any("**Apply.**" in v for v in _lint_lesson_entry(planted)), \
        "a lesson with no Apply line tells an agent nothing to do"


def test_lesson_detector_catches_a_status_outside_the_legend():
    planted = _GOOD_LESSON.replace("status: local", "status: maybe")
    assert any("maybe" in v for v in _lint_lesson_entry(planted))


def test_standard_detector_catches_the_planted_missing_consequence():
    planted = _GOOD_STANDARD.replace(
        "**Consequence.** Generated names differ from the entity names in the "
        "model.\n", "")
    assert any("Consequence" in v for v in _lint_standard_entry(planted)), \
        "the spec's named lint: an active standard must state its cost"


def test_standard_detector_lets_a_proposed_entry_omit_consequence_only_if_it_must():
    # `proposed` is pre-gate; the consequence is what the gate SHOWS, so the
    # requirement binds at activation, not at drafting.
    proposed = _GOOD_STANDARD.replace("status: active", "status: proposed")
    proposed = proposed[:proposed.index("**Consequence.**")]
    assert _lint_standard_entry(proposed) == []


def test_standard_detector_catches_bad_status_and_bad_category():
    assert any("maybe" in v for v in _lint_standard_entry(
        _GOOD_STANDARD.replace("status: active", "status: maybe")))
    assert any("policy" in v for v in _lint_standard_entry(
        _GOOD_STANDARD.replace("category: naming", "category: policy")))


# --- 3. the gap-fill contract, asserted against the content ------------------

def test_local_knowledge_documents_the_gap_fill_contract():
    text = _text(LOCAL_KNOWLEDGE).lower()
    assert ".oracle-ai-dev/standards.md" in text, "first-use marker must be named"
    assert "absen" in text, "first use is detected by ABSENCE of the store"
    assert "silent" in text and "cover" in text, "silent where already covered"
    assert "category: process" in text, "§3.5 — outcomes are process standards"
    assert "status: active" in text and "status: declined" in text
    assert "re-ask" in text or "never asks again" in text or "asked again" in text


def test_operating_principles_carry_the_groups_the_carve_out_and_companions():
    text = _text(PRINCIPLES).lower()
    for group in ("measurement", "generation", "process", "non-overridable"):
        assert group in text, f"missing the {group} group heading"
    assert "destructive" in text, "non-overridable 1"
    assert "identifying" in text or "pii" in text, "non-overridable 2"
    assert "claim" in text, "non-overridable 3"
    for companion in ("test-driven-development", "verification-before-completion",
                      "systematic-debugging", "brainstorming"):
        assert companion in text, f"the companion table must name {companion}"


def test_operating_principles_include_learnings_capture():
    # the SME-round addition (2026-08): capture Oracle learnings at the
    # moment of confirmation, evidence-graded, and offer them upstream
    text = _text(PRINCIPLES).lower()
    assert "moment" in text and "lessons.md" in text
    assert "verbatim" in text and "ora-" in text     # exact errors, exact codes
    assert "unverified" in text                      # inferred ≠ confirmed
    assert "undocumented" in text                    # docs-status discipline
    assert "upstream" in text                        # the contribution path
    assert "directly" in text                        # never edit skills directly


def test_install_recommends_the_companion_plugins():
    assert "superpowers" in _text("INSTALL.md").lower()


# --- 4. housekeeping ---------------------------------------------------------

def test_both_new_references_are_reachable_from_the_skill():
    text = _text(f"{SKILL}/SKILL.md")
    for ref in ("references/local-knowledge.md", "references/operating-principles.md"):
        assert ref in text, f"SKILL.md must link {ref} — an unlinked reference is dead"


def test_real_entry_detector_catches_the_planted_entry():
    planted = "# Standards\n<!-- ## example-only\nstatus: proposed\n-->\n## real-one\n"
    assert _real_entries(planted) == ["## real-one"], \
        "a starter template must not seed a project with someone else's standard"


def test_templates_ship_with_examples_only():
    for tpl in (LESSONS_TPL, STANDARDS_TPL):
        assert _real_entries(_text(tpl)) == [], f"{tpl} ships with a real entry"

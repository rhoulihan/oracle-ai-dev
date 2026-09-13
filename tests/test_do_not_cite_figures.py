# Copyright (c) 2026 Oracle and/or its affiliates.
"""Do-not-cite engagement figures are banned from ALL shipped content.

The scenario count and the headline multiplier fingerprint their source even
with every name scrubbed (2026-07-15 PII review), so they must not appear in
any skill, README, or shipped doc — not just field-lessons.md, where the
original narrow check lived.

Scope note: the unrounded-seconds SHAPE guard (`0.xxx s`) deliberately stays
scoped to field-lessons.md (test_modeling_skill.py) — sub-second constants are
legitimate across the other skills (latency examples, vendor thresholds), and
only field-lessons carries engagement-derived timings. A repo-wide shape ban
would false-positive; a repo-wide ban on the two exact figures cannot.
"""

import sys
from pathlib import Path


def _lint(repo_root: Path):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    import banned_strings
    return banned_strings


# --------------------------------------------------------------- red paths

def test_detector_catches_the_banned_figures(repo_root: Path):
    b = _lint(repo_root)
    assert b.scan_do_not_cite("the suite ran 477 scenarios")
    assert b.scan_do_not_cite("a 165x speedup")
    assert b.scan_do_not_cite("about 165× faster")
    assert b.scan_do_not_cite("about 165 × faster")


def test_error_codes_and_larger_numbers_do_not_false_positive(repo_root: Path):
    b = _lint(repo_root)
    assert b.scan_do_not_cite("throws ORA-40477 on read") == []
    assert b.scan_do_not_cite("ports 14770 and 1477 and 4771") == []
    assert b.scan_do_not_cite("165 xml documents") == []
    assert b.scan_do_not_cite("throughput of 165 rows/s") == []


# ------------------------------------------------------------ shipped tree

def test_no_shipped_file_cites_the_banned_figures(repo_root: Path):
    # Same shipped-content surface as the confidential-token scan: skills/**,
    # README, docs/** minus the internal dossiers that legitimately discuss
    # the sanitization targets they mandate.
    b = _lint(repo_root)
    assert b.scan_do_not_cite_tree(repo_root) == {}


def test_tree_scan_catches_a_planted_figure(repo_root: Path, tmp_path):
    b = _lint(repo_root)
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "SKILL.md").write_text("we measured a 165x speedup")
    problems = b.scan_do_not_cite_tree(tmp_path)
    assert problems and "skills/SKILL.md" in problems

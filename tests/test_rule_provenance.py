# Copyright (c) 2026 Oracle and/or its affiliates.
"""Prose that reads like a validator must be one — or say it isn't.

The tooling audit found 24 RULE/CHECK gates that read like a validator while
enforcing nothing: everyone assumed the CHECKs gated something because of the
FORM they were written in. The standing rule makes that failure mode
unrepeatable: any reference file written in RULE/CHECK form must either cite
the code that enforces it (a repo path that exists) or carry an explicit
`> Advisory:` marker telling the reader it is judgment, not mechanism.
"""

import re
from pathlib import Path

_RULE_FORM = re.compile(r"\*\*RULE\.?\*\*|\*\*CHECK\.?\*\*")
_ADVISORY = re.compile(r"^> Advisory:", re.MULTILINE)
# a cited enforcing path: repo-relative, in code/test/asset space
_CODE_PATH = re.compile(r"\b(?:tooling|tests|assets)/[\w./-]+\.(?:py|sql|sh)\b")


def _rule_files(repo_root: Path):
    return [f for f in sorted((repo_root / "skills").rglob("references/*.md"))
            if _RULE_FORM.search(f.read_text())]


def test_rule_form_files_exist_to_scan(repo_root: Path):
    assert _rule_files(repo_root), "expected at least the duality gates file"


def test_rule_form_prose_cites_its_enforcement_or_admits_advisory(repo_root: Path):
    problems = []
    for f in _rule_files(repo_root):
        text = f.read_text()
        rel = f.relative_to(repo_root).as_posix()
        cited = [p for p in _CODE_PATH.findall(text) if (repo_root / p).exists()]
        dead = [p for p in _CODE_PATH.findall(text) if not (repo_root / p).exists()]
        if dead:
            problems.append(f"{rel}: cites nonexistent path(s) {dead}")
        if not cited and not _ADVISORY.search(text):
            problems.append(
                f"{rel}: written in RULE/CHECK form but cites no enforcing code "
                f"and carries no '> Advisory:' marker")
    assert not problems, "\n".join(problems)

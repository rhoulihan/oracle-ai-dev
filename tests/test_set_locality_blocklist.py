# Copyright (c) 2026 Oracle and/or its affiliates.
"""A non-GA locality clause for duality views must never leave
this repo in generated DDL, examples, or prose. No generator code path emits it
today, so these tests are a tripwire: they fail the moment any code path, skill
reference, or asset starts producing or quoting the clause. The single sanctioned
mention is the guardrail that bans it (claims-guardrails.md).

The banned string is built by concatenation below so this test file itself never
contains the literal and needs no scan exemption.
"""
import json
import re
from pathlib import Path

from tooling.generate.ddl import generate_ddl
from tooling.generate.ingest import model_from_dynamodb

# the two banned words with any whitespace between them, case-insensitive;
# assembled from parts so this file never contains the contiguous clause.
_BANNED = re.compile(r"SET\s+" + "LOCALITY", re.IGNORECASE)

_ALLOWED = {"skills/oracle-data-modeling/references/claims-guardrails.md"}

def _models():
    for fixture in ("tests/fixtures/restaurant_model.json",
                    "tests/fixtures/orgchart_model.json"):
        yield fixture, json.loads(Path(fixture).read_text())
    for fixture in ("tests/fixtures/dynamodb_banking.json",
                    "tests/fixtures/dynamodb_flightsfares.json"):
        model, _ = model_from_dynamodb(json.loads(Path(fixture).read_text()))
        yield fixture, model


def _findings(root: Path, subdir: str):
    hits = []
    for f in sorted((root / subdir).rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        if rel in _ALLOWED:
            continue
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if _BANNED.search(text):
            hits.append(rel)
    return hits


def test_scanner_detects_a_planted_clause(tmp_path):
    # Red-path proof: the detection regex catches the clause however it is spaced.
    planted = "ALTER JSON RELATIONAL DUALITY VIEW order_dv SET" + "  Locality (x);"
    (tmp_path / "bad.sql").write_text(planted)
    assert _BANNED.search((tmp_path / "bad.sql").read_text())


def test_generated_ddl_never_contains_the_clause():
    # Every shape the generator can emit, over every fixture model that offers it.
    emitted = 0
    for fixture, model in _models():
        for shape in ("relational", "single_table", "document", "duality"):
            try:
                ddl = generate_ddl(model, shape)
            except ValueError:
                continue                    # fixture has no projection for this shape
            emitted += 1
            assert not _BANNED.search(ddl), \
                f"{shape} DDL from {fixture} emitted the non-GA clause"
    assert emitted >= 4, "expected the fixtures to exercise several shapes"


def test_tripwire_clause_absent_from_tooling_and_skills(repo_root: Path):
    hits = _findings(repo_root, "tooling") + _findings(repo_root, "skills")
    assert not hits, f"non-GA locality clause found in: {hits}"

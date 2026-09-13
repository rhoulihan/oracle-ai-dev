# Copyright (c) 2026 Oracle and/or its affiliates.
"""The rules/tuning reference docs stay honest as the code moves.

docs/model-rules-reference.md presents rules as mechanism with the enforcing
path next to each one; docs/tuning-and-custom-standards.md names the knobs.
A cited path that stops existing means the doc is describing code that is no
longer there — the same rot class the rule-provenance lint kills in skills.
"""

import re
import subprocess
from pathlib import Path

DOCS = ("docs/model-rules-reference.md", "docs/tuning-and-custom-standards.md")
_CODE_PATH = re.compile(
    r"\b(?:tooling|tests|assets|skills|docs)/[\w./-]+\.(?:py|sql|sh|md|json|txt)\b")
SHAPES = ("relational", "document", "hybrid", "duality", "summary",
          "single_table", "sql_view")


def test_reference_docs_exist(repo_root: Path):
    for d in DOCS:
        assert (repo_root / d).is_file(), f"missing: {d}"


def test_every_cited_path_is_tracked(repo_root: Path):
    # TRACKED, not merely present: a gitignored internal file (docs/specs/...)
    # exists on a maintainer's disk but not in anyone's clone — a citation that
    # resolves locally and 404s for every user, which is how this test first
    # failed on CI only.
    tracked = set(subprocess.run(["git", "ls-files"], capture_output=True,
                                 text=True, cwd=repo_root).stdout.splitlines())
    dead = []
    for d in DOCS:
        text = (repo_root / d).read_text()
        dead += [f"{d} -> {p}" for p in sorted(set(_CODE_PATH.findall(text)))
                 if p not in tracked]
    assert not dead, "docs cite paths not tracked in the repo:\n" + "\n".join(dead)


def test_matrix_covers_every_shape(repo_root: Path):
    text = (repo_root / DOCS[0]).read_text()
    for shape in SHAPES:
        assert shape in text, f"the matrix must cover shape {shape!r}"


def test_tuning_doc_names_the_cli_knobs(repo_root: Path):
    text = (repo_root / DOCS[1]).read_text()
    for knob in ("--write-scale", "--walk-scales", "--no-sparse",
                 "--no-partition-by-type", "--no-partition", "--flex-limit",
                 "--no-flex-limit", "--no-iot", "--no-compress",
                 "--trials", "--platforms",
                 "ORACLE_AI_DEV_CONFIDENTIAL_REGISTER", "OPT_ALLOW_EXTERNAL_WRITES"):
        assert knob in text, f"tuning doc must document {knob}"


def test_unshipped_pipeline_is_labeled_not_promised(repo_root: Path):
    # The local-knowledge standards pipeline is designed, unimplemented, and
    # pending review — the doc must say so, not present it as available.
    text = (repo_root / DOCS[1]).read_text().lower()
    assert "not yet" in text or "not implemented" in text or "pending" in text
    assert "2026-07-15-local-knowledge-spec" in text


# --- Claims-level check: the matrix must agree with the GENERATORS ------------
#
# The path check above catches a cited file that vanishes; it is blind to a doc
# that contradicts the code it cites — which happened: the document matrix kept
# teaching "RETURNING NUMBER on both sides" after the generators moved to
# dot-notation-first. Each claim below is asserted twice: the GENERATOR must
# actually behave that way (so a doctrine change fails here first), and the
# MATRIX section must state it (so the doc is forced to move in the same
# commit). Superseded claims are banned outright.

_CLAIM_MODEL = {
    "entities": {"Res": {"table": "reservations", "pk": "res_id",
                         "columns": {"status": "status", "total": "total",
                                     "tags": "tags"},
                         "arrays": ["tags"]}},
    "relationships": [],
    "projections": {"document": {"Res": {"collection": "res_docs",
                                         "id_path": "$._id"}}},
}

# claims that would mean the doc regressed to a superseded doctrine
_SUPERSEDED = ("RETURNING NUMBER` on both",
               "Scalar comparisons render as JSON_VALUE")


def _matrix_section(repo_root: Path, shape_heading: str) -> str:
    text = (repo_root / DOCS[0]).read_text()
    start = text.index(shape_heading)
    nxt = text.find("\n### ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def _stale_claims(text: str):
    return [c for c in _SUPERSEDED if c in text]


def test_stale_claim_detector_catches_the_planted_regression():
    planted = ("| Numeric properties are pinned with `RETURNING NUMBER` on both "
               "the query and index sides | by construction |")
    assert _stale_claims(planted), "the detector must catch the claim that rotted"


def test_document_matrix_claims_match_the_generators(repo_root: Path):
    from tooling.datalayer.generate import bound_sql
    from tooling.generate.ddl import generate_indexes
    from tooling.generate.sql import generate_document

    q_scalar = {"root": "Res", "returns": ["Res.status"],
                "predicates": [{"ref": "Res.status", "op": "=", "value": "OPEN"}]}
    q_num = {"root": "Res", "returns": ["Res.status"],
             "predicates": [{"ref": "Res.total", "op": ">", "value": 9}]}
    q_id = {"root": "Res", "returns": ["Res.status"],
            "predicates": [{"ref": "Res.res_id", "op": "=", "value": 7}]}
    q_arr = {"root": "Res", "returns": ["Res.status"],
             "predicates": [{"ref": "Res.tags", "op": "=", "value": "red"}]}
    q_agg = {"root": "Res", "group_by": ["Res.status"],
             "aggregates": [{"fn": "SUM", "ref": "Res.total", "name": "t"}]}

    sec = _matrix_section(repo_root, "### document — JSON collection table")

    # claim 1 — plain-dot scalar predicates, in both literal and bound emitters
    sql = generate_document(_CLAIM_MODEL, q_scalar)
    bnd, _ = bound_sql(_CLAIM_MODEL, q_scalar, "document")
    assert "d.data.status = 'OPEN'" in sql and "JSON_VALUE" not in sql, sql
    assert "d.data.status = :b0" in bnd, bnd
    assert "plain dot" in sec and "d.data.prop = :b" in sec

    # claim 2 — typed-item-method MULTIVALUE indexes, no scalar JSON_VALUE index
    idx = generate_indexes(_CLAIM_MODEL, [q_num], shape="document")
    assert "CREATE MULTIVALUE INDEX" in idx and ".numberOnly()" in idx, idx
    assert "JSON_VALUE" not in idx, idx
    assert "MULTIVALUE" in sec and ".numberOnly()" in sec

    # claim 3 — _id stays the typed JSON_VALUE last resort
    id_sql = generate_document(_CLAIM_MODEL, q_id)
    assert "JSON_VALUE(d.data, '$._id'" in id_sql, id_sql
    assert "LAST RESORT" in sec, "the _id exception must be named as the last resort"

    # claim 4 — arrays stay JSON_EXISTS containment
    arr_sql = generate_document(_CLAIM_MODEL, q_arr)
    assert "JSON_EXISTS" in arr_sql, arr_sql
    assert "JSON_EXISTS" in sec

    # claim 5 — aggregation uses item methods on both sides
    agg_sql = generate_document(_CLAIM_MODEL, q_agg)
    agg_idx = generate_indexes(_CLAIM_MODEL, [q_agg], shape="document")
    assert ".numberOnly()" in agg_sql and ".numberOnly()" in agg_idx
    assert "ORDER BY" in sec or "aggregation" in sec.lower()

    # and the doc must carry NO superseded claim, anywhere
    whole = (repo_root / DOCS[0]).read_text()
    assert not _stale_claims(whole), _stale_claims(whole)

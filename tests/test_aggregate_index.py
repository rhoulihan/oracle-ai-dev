# Copyright (c) 2026 Oracle and/or its affiliates.
"""An aggregation deserves an index too — "documents can't aggregate" was our bug, not Oracle's.

Index derivation looked only at FILTER predicates, so a `GROUP BY` key never got one and every
aggregation scanned the whole collection. Measured live (30k reservations, count_by_status):

    plain GROUP BY, no index      15,479 us   3,359 logical reads   TABLE ACCESS FULL
    with an index on (key, 0)      1,789 us     102 logical reads   INDEX FAST FULL SCAN
    relational reference           1,352 us     247 logical reads

Nine times faster, on LESS I/O than the relational table — and the document goes from 8.6x
slower than relational at aggregating to parity. The capstone's headline finding ("the
document is 2.4x worse, and it is all aggregation") was measuring a missing index.

Two details that are the whole trick:
  * THE TRAILING CONSTANT. A B-tree omits entries whose key is entirely NULL, so Oracle
    cannot use it for COUNT(*) — any document might lack the field. `(expr, 0)` makes the
    entry never wholly NULL, so the index holds EVERY row. No query change, no semantic
    change: the NULL group is still counted.
  * THE EXPRESSIONS MUST MATCH EXACTLY, or the index is built, valid and ignored — the
    lesson from the document's mistyped JSON index and the single table's TO_NUMBER.
"""
import sys
from pathlib import Path


MODEL = {
    "entities": {"Res": {"table": "reservations", "pk": "res_id",
                         "columns": {"status": "status", "party": "party"}}},
    "relationships": [],
    "projections": {"document": {"Res": {"collection": "res_docs", "id_path": "$._id"}}},
}
COUNT_Q = {"root": "Res", "group_by": ["Res.status"],
           "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"}]}
SUM_Q = {"root": "Res", "group_by": ["Res.status"],
         "aggregates": [{"fn": "SUM", "ref": "Res.party", "name": "total"}]}


def _m(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.ddl import generate_indexes
    from tooling.generate.sql import generate_document, generate_relational
    return generate_indexes, generate_document, generate_relational


def test_a_group_by_key_gets_an_index(repo_root: Path):
    gi, _, _ = _m(repo_root)
    rel = gi(MODEL, [COUNT_Q], shape="relational")
    assert "(status, 0)" in rel, f"no index on the GROUP BY key:\n{rel}"


def test_the_index_carries_a_trailing_constant_so_it_can_serve_count(repo_root: Path):
    """Without it Oracle will not use the index for COUNT(*) — the NULL keys are missing."""
    gi, _, _ = _m(repo_root)
    doc = gi(MODEL, [COUNT_Q], shape="document")
    assert doc.rstrip().rstrip(";").endswith(", 0)"), f"no trailing constant:\n{doc}"


def test_the_index_covers_the_aggregate_argument_too(repo_root: Path):
    """SUM(party) GROUP BY status: index (status, party, 0) is COVERING — Oracle never has to
    touch the fat documents at all."""
    gi, _, _ = _m(repo_root)
    rel = gi(MODEL, [SUM_Q], shape="relational")
    assert "(status, party, 0)" in rel, rel


def test_query_and_index_expressions_match_exactly_for_the_document(repo_root: Path):
    """The index is built, valid and IGNORED unless the expression is character-identical.
    That defect has now bitten the document's JSON index and the single table's TO_NUMBER."""
    gi, gdoc, _ = _m(repo_root)
    idx = gi(MODEL, [SUM_Q], shape="document")
    sql = gdoc(MODEL, SUM_Q)
    for expr in ("data.status.string()", "data.party.numberOnly()"):
        assert expr in idx, f"{expr!r} missing from the index:\n{idx}"
        assert f"d.{expr}" in sql, \
            f"the query does not use the indexed expression:\n{sql}"

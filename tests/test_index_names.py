# Copyright (c) 2026 Oracle and/or its affiliates.
"""An index is named for the OBJECT IT IS BUILT ON — or one shape steals another's indexes.

`generate_indexes` named every index after the ENTITY'S TABLE regardless of the shape being
deployed. So the document shape created

    CREATE INDEX itinerary_reservations_passenger_id_ix ON reservation_docs (JSON_VALUE(...))

...and when the relational deploy then tried to build ITS index of that same name on
`itinerary_reservations`, Oracle raised ORA-00955 ("name is already used by an existing
object") — which the runner TOLERATES as "already exists" and swallows.

Relational therefore never got a single access-pattern index and full-scanned its filtered
reads, at 1,500/hr and 300/hr, in every run of the capstone. Duality and the document were
not beating relational; relational was crippled, by their index names.
"""
import sys
from pathlib import Path


MODEL = {
    "entities": {
        "Res": {"table": "reservations", "pk": "res_id",
                "columns": {"status": "status", "passenger_id": "passenger_id"}},
        "Passenger": {"table": "passengers", "pk": "passenger_id", "columns": {}},
    },
    "relationships": [{"from": "Passenger", "to": "Res", "cardinality": "1:N",
                       "from_key": "passenger_id", "to_key": "passenger_id"}],
    "projections": {"document": {"Res": {"collection": "res_docs", "id_path": "$._id"}}},
}
QUERIES = [{"root": "Res", "returns": ["Res.status"],
            "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}]


def _gi(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.ddl import generate_indexes
    return generate_indexes


def test_index_names_are_namespaced_by_the_object_they_are_built_on(repo_root: Path):
    gi = _gi(repo_root)
    rel = gi(MODEL, QUERIES, shape="relational")
    doc = gi(MODEL, QUERIES, shape="document")
    assert "ON reservations (passenger_id)" in rel, rel
    assert "ON res_docs t (" in doc, doc

    def names(ddl):
        return {s.split(" ON ")[0].split()[-1] for s in ddl.splitlines()
                if s.startswith(("CREATE INDEX", "CREATE MULTIVALUE INDEX"))}

    clash = names(rel) & names(doc)
    assert not clash, (
        f"the document and relational shapes generate the SAME index name {clash} on "
        f"DIFFERENT tables — whichever deploys second hits ORA-00955 and is silently skipped")


def test_the_document_index_is_named_for_the_collection(repo_root: Path):
    gi = _gi(repo_root)
    doc = gi(MODEL, QUERIES, shape="document")
    assert "CREATE MULTIVALUE INDEX res_docs_" in doc, doc
    assert "reservations_passenger_id_ix" not in doc, \
        f"named for the base table, but built on the collection:\n{doc}"


def test_the_runner_verifies_the_indexes_actually_landed(repo_root: Path):
    """Naming was the bug; TOLERATING ORA-00955 is what hid it for weeks. `CREATE INDEX` is
    allowed to say "already exists" — that is what makes a re-run idempotent — so a silent
    skip is indistinguishable from a success. The only honest check is to look afterwards:
    does each index exist, ON THE TABLE IT WAS MEANT FOR?"""
    import sys
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r

    # A MULTIVALUE index with a table alias must be visible to the verifier too —
    # the old grammar silently skipped every multivalue index, so the check could
    # not see whether the document's shared-lane indexes actually landed.
    ddl = ("CREATE INDEX reservations_passenger_id_ix ON reservations (passenger_id);\n"
           "CREATE MULTIVALUE INDEX res_docs_passenger_id_ix ON res_docs t "
           "(t.data.passenger_id.numberOnly());")
    want = r.expected_indexes(ddl)
    assert want == {"RESERVATIONS_PASSENGER_ID_IX": "RESERVATIONS",
                    "RES_DOCS_PASSENGER_ID_IX": "RES_DOCS"}, want

# Copyright (c) 2026 Oracle and/or its affiliates.
"""A duality view costs exactly what it nests — so nest only what the query needs.

Measured live on the airline capstone, for the SAME two-scalar filtered read:

    kitchen-sink view (nests passenger + agent + legs + payments):  3,257 us
    lean view (root scalars only):                                    451 us
    relational:                                                       584 us

One view per root, covering the union of every pattern, makes the point read pay for the
itinerary read's joins — which is why duality placed LAST in the capstone matrix. That is a
defect in the generator, not in duality. A modeller builds a view per aggregate; so does this.

Each pattern then reads through the LEANEST view that can answer it.
"""
import sys
from pathlib import Path


MODEL = {
    "entities": {
        "Res":      {"table": "reservations", "pk": "res_id",
                     "columns": {"status": "status", "passenger_id": "passenger_id"}},
        "Passenger": {"table": "passengers", "pk": "passenger_id",
                      "columns": {"last_name": "last_name"}},
        "ResLeg":   {"table": "res_legs", "pk": ["res_id", "leg_id"], "columns": {}},
        "Leg":      {"table": "legs", "pk": "leg_id",
                     "columns": {"flight_number": "flight_number"}},
    },
    "relationships": [
        {"from": "Passenger", "to": "Res", "cardinality": "1:N",
         "from_key": "passenger_id", "to_key": "passenger_id"},
        {"from": "Res", "to": "ResLeg", "cardinality": "1:N",
         "from_key": "res_id", "to_key": "res_id"},
        {"from": "Leg", "to": "ResLeg", "cardinality": "1:N",
         "from_key": "leg_id", "to_key": "leg_id"},
    ],
}
POINT_READ = {"root": "Res", "returns": ["Res.status"],
              "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}
BY_PASSENGER = {"root": "Res", "returns": ["Res.status"],
                "predicates": [{"ref": "Res.passenger_id", "op": "=", "value": 7}]}
WITH_NAME = {"root": "Res", "returns": ["Res.status", "Passenger.last_name"],
             "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}
ITINERARY = {"root": "Res", "returns": ["Res.status", "Leg.flight_number"],
             "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}
PATTERNS = [{"name": "point", "rate": 5000, "query": POINT_READ},
            {"name": "by_passenger", "rate": 1500, "query": BY_PASSENGER},
            {"name": "with_name", "rate": 40, "query": WITH_NAME},
            {"name": "itinerary", "rate": 4000, "query": ITINERARY}]


def _r(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    return r


def test_one_view_per_aggregate_not_one_per_root(repo_root: Path):
    """Four patterns needing three different aggregates -> three views, not one kitchen sink."""
    r = _r(repo_root)
    m = r.propose_projections(MODEL, PATTERNS)
    views = m["projections"]["duality"]["Res"]
    assert isinstance(views, list), "duality must offer a view PER AGGREGATE"
    scopes = {frozenset(v["includes"]) for v in views}
    assert frozenset() in scopes, "the point read needs a LEAN view — root scalars only"
    assert frozenset({"Passenger"}) in scopes
    assert frozenset({"Leg"}) in scopes
    assert len(views) == 3, f"one view per distinct aggregate, got {views}"


def test_the_lean_view_nests_nothing(repo_root: Path):
    """The point read must not pay to assemble the passenger and every leg."""
    r = _r(repo_root)
    from tooling.generate.ddl import generate_ddl
    m = r.propose_projections(MODEL, PATTERNS)
    ddl = generate_ddl(m, "duality")
    lean = [b for b in ddl.split("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW")
            if b.strip().startswith("reservations_dv ")][0]
    assert "passengers" not in lean and "legs" not in lean, f"the lean view nests things:\n{lean}"
    # and the FK stays a ROOT SCALAR when its parent is not nested (no ORA-40609 to dodge)
    assert "passenger_id : passenger_id" in lean


def test_each_pattern_reads_through_the_leanest_view_that_answers_it(repo_root: Path):
    r = _r(repo_root)
    m = r.propose_projections(MODEL, PATTERNS)
    sql = {p["name"]: r.pattern_sql(m, p, "duality") for p in PATTERNS}
    assert "FROM reservations_dv d" in sql["point"], sql["point"]
    assert "FROM reservations_dv d" in sql["by_passenger"], sql["by_passenger"]
    assert "_passenger" in sql["with_name"], sql["with_name"]
    assert "_leg" in sql["itinerary"], sql["itinerary"]
    # the lean view is flat, so the FK filter uses the FLAT path
    assert "'$.passenger_id'" in sql["by_passenger"], sql["by_passenger"]
    # the passenger view nests it, so that one uses the NESTED path
    assert "'$.passenger.last_name'" in sql["with_name"] or "passenger" in sql["with_name"]


def test_a_declared_string_view_still_works(repo_root: Path):
    """Back-compat: a model that declares `duality: {Res: "reservations_dv"}` keeps the
    single all-in view it asked for."""
    r = _r(repo_root)
    from tooling.generate.ddl import generate_ddl
    m = dict(MODEL, projections={"duality": {"Res": "reservations_dv"}})
    ddl = generate_ddl(m, "duality")
    assert ddl.count("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW") == 1
    assert "legs" in ddl and "passengers" in ddl


def test_a_duality_write_targets_a_duality_view(repo_root: Path):
    """`generate_insert(..., "duality")` had no duality branch at all — it fell through and
    inserted into the DOCUMENT COLLECTION, then reported that as duality's write cost. It was
    measuring the wrong design."""
    r = _r(repo_root)
    from tooling.generate.sql import generate_insert
    m = r.propose_projections(MODEL, PATTERNS)
    sql = generate_insert(m, POINT_READ, "duality")
    assert "reservations_dv" in sql, sql
    assert "_docs" not in sql, f"a duality write must not go to the document collection:\n{sql}"


def test_a_duality_write_goes_through_the_view_that_models_that_aggregate(repo_root: Path):
    """A write goes through the view holding the aggregate being written: a status change
    touches one root scalar (the lean view); creating a booking writes the reservation AND its
    legs, so it writes through the view that holds them. Point a leg-bearing document at the
    lean view and Oracle rejects it — ORA-40944, JZN-00651 'field is unknown or undefined'."""
    r = _r(repo_root)
    from tooling.generate.sql import generate_update, generate_insert
    m = r.propose_projections(MODEL, PATTERNS)
    upd = generate_update(m, POINT_READ, "duality", "Res.status", 1)
    assert "UPDATE reservations_dv " in upd, upd            # the LEAN view: cheapest write
    assert "[" not in upd, f"a list of views leaked into the SQL:\n{upd}"
    ins = generate_insert(m, ITINERARY, "duality")          # writes the legs too
    assert "reservations_dv_leg" in ins, ins


def test_no_view_repr_leaks_into_sql(repo_root: Path):
    """`projections.duality[root]` is now a LIST of views. Render it with str() and a Python
    repr lands in the SQL — the same defect that took the duality DDL out with ORA-24558."""
    r = _r(repo_root)
    from tooling.generate.sql import generate_duality, generate_update
    m = r.propose_projections(MODEL, PATTERNS)
    for sql in (generate_duality(m, POINT_READ),
                generate_update(m, POINT_READ, "duality", "Res.status", 1)):
        assert "{'view'" not in sql and "[{" not in sql, sql


def test_nested_columns_are_scoped_to_what_the_patterns_reference(repo_root: Path):
    """Scoping by AGGREGATE but not by COLUMN leaves a kitchen sink one level down: the
    passenger view nested all 11 passenger columns when the only pattern using it wants
    `last_name`, and the itinerary view nested every leg and payment column when the query
    asks for three. A view costs exactly what it nests — and that includes the columns."""
    r = _r(repo_root)
    from tooling.generate.ddl import generate_ddl
    m = r.propose_projections(MODEL, PATTERNS)
    ddl = generate_ddl(m, "duality")

    pax = [b for b in ddl.split("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW")
           if b.strip().startswith("reservations_dv_passenger ")][0]
    assert "last_name : last_name" in pax                 # the one property anybody asked for
    assert "passenger_id : passenger_id" in pax           # ...and the key duality requires


def test_the_key_survives_even_when_no_pattern_returns_it(repo_root: Path):
    """Trim the columns, not the keys. Duality needs the nested entity's key to identify the
    row (ORA-40477 on a child array without its full PK), and the root's key IS `_id`."""
    r = _r(repo_root)
    from tooling.generate.ddl import generate_ddl
    m = r.propose_projections(MODEL, PATTERNS)
    itin = [b for b in generate_ddl(m, "duality").split(
        "CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW")
        if b.strip().startswith("reservations_dv_leg ")][0]
    assert "_id : res_id" in itin
    assert "res_id : res_id" in itin and "leg_id : leg_id" in itin   # junction's full PK
    assert "flight_number : flight_number" in itin                   # the payload asked for


def _view_bodies(ddl):
    """Just the views — `generate_ddl(.., "duality")` also emits the BASE TABLES, and of
    course `passengers` has a phone_number column. The question is whether the VIEW carries
    it."""
    return "".join(b.split(";")[0] for b in
                   ddl.split("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW")[1:])


def test_an_unreferenced_column_is_not_nested_at_any_level(repo_root: Path):
    """Scope the attributes at EVERY level of every view — root scalars, the nested parent,
    the junction, and the far side of the M:N. A column nobody queries is a column nobody
    should be assembling on every read."""
    r = _r(repo_root)
    from tooling.generate.ddl import generate_ddl
    import copy
    m = copy.deepcopy(MODEL)
    m["entities"]["Res"]["columns"]["notes"] = "notes"            # root: unreferenced
    m["entities"]["Passenger"]["columns"]["phone"] = "phone_number"   # parent: unreferenced
    m["entities"]["Leg"]["columns"]["tail"] = "tail_number"        # far side: unreferenced
    views = _view_bodies(generate_ddl(r.propose_projections(m, PATTERNS), "duality"))
    assert "notes" not in views, "an unreferenced ROOT column is being carried"
    assert "phone_number" not in views, "an unreferenced PARENT column is being nested"
    assert "tail_number" not in views, "an unreferenced FAR-SIDE column is being nested"
    # ...and everything that IS referenced survives, at every level
    for kept in ("status", "last_name", "flight_number"):
        assert kept in views, f"{kept} was scoped away but a pattern needs it"

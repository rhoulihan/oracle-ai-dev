# Copyright (c) 2026 Oracle and/or its affiliates.
"""The fan trap: joining two INDEPENDENT child collections multiplies them.

A reservation with 3 legs and 2 payments, joined naively, returns 3x2 = 6 rows — every leg
repeated once per payment, every payment repeated once per leg, the reservation repeated six
times. It is not the aggregate the query asked for, and it costs more to produce.

Live on the airline capstone:

    relational, cartesian join (generated):  528 us,  6 rows   <- wrong answer, slower
    relational, nested aggregation:          377 us,  1 row
    duality:                                 380 us,  1 row

Which answers the question that prompted this: **duality is not free joins.** It performs
exactly the same joins — and once the relational query performs them correctly rather than
cross-producting, the two are a dead heat (377 vs 380). The 200us "duality advantage" was a
bad relational query, not a fast duality view.
"""
import sys
from pathlib import Path


MODEL = {
    "entities": {
        "Res":     {"table": "reservations", "pk": "res_id", "columns": {"status": "status"}},
        "ResLeg":  {"table": "res_legs", "pk": ["res_id", "leg_id"], "columns": {}},
        "Leg":     {"table": "legs", "pk": "leg_id", "columns": {"flight_number": "flight_number"}},
        "ResPay":  {"table": "res_pays", "pk": ["res_id", "pay_id"], "columns": {}},
        "Payment": {"table": "payments", "pk": "pay_id", "columns": {"amount": "amount",
                                                                     "status": "status"}},
        "Agency":  {"table": "agencies", "pk": "agency_id", "columns": {"name": "name"}},
    },
    "relationships": [
        {"from": "Res", "to": "ResLeg", "cardinality": "1:N", "from_key": "res_id", "to_key": "res_id"},
        {"from": "Leg", "to": "ResLeg", "cardinality": "1:N", "from_key": "leg_id", "to_key": "leg_id"},
        {"from": "Res", "to": "ResPay", "cardinality": "1:N", "from_key": "res_id", "to_key": "res_id"},
        {"from": "Payment", "to": "ResPay", "cardinality": "1:N", "from_key": "pay_id", "to_key": "pay_id"},
        {"from": "Agency", "to": "Res", "cardinality": "1:N", "from_key": "agency_id", "to_key": "agency_id"},
    ],
}
AGG_Q = {"root": "Res",
         "returns": ["Res.status", "Leg.flight_number", "Payment.amount"],
         "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}
ONE_CHILD_Q = {"root": "Res", "returns": ["Res.status", "Leg.flight_number"],
               "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}


def _gen(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.generate.sql import generate_relational
    return generate_relational


def test_two_child_collections_do_not_cross_product(repo_root: Path):
    """3 legs x 2 payments must not become 6 rows of duplicated everything."""
    sql = _gen(repo_root)(MODEL, AGG_Q).upper()
    assert "JSON_ARRAYAGG" in sql, f"the two child collections are being cross-joined:\n{sql}"
    # each collection is gathered in its own correlated subquery, not joined to the other
    assert sql.count("JSON_ARRAYAGG") == 2, sql
    assert "FLIGHT_NUMBER" in sql and "AMOUNT" in sql


def test_the_rewrite_keeps_non_root_predicates(repo_root: Path):
    """A predicate on a branch entity must filter INSIDE its branch. Dropped, the payments
    subquery aggregates ALL payments including unpaid — a silently wrong answer, and the
    reference every other design is judged against."""
    q = {**AGG_Q, "predicates": AGG_Q["predicates"]
         + [{"ref": "Payment.status", "op": "=", "value": "paid"}]}
    sql = _gen(repo_root)(MODEL, q).lower()
    assert "payment.status = 'paid'" in sql, f"the branch predicate vanished:\n{sql}"
    assert "res.res_id = 1" in sql


def test_the_rewrite_keeps_parent_returns(repo_root: Path):
    """An N:1 parent of the root is not a branch — joined, it cannot fan. Its column must
    not vanish from the projection."""
    q = {"root": "Res",
         "returns": ["Res.status", "Agency.name", "Leg.flight_number", "Payment.amount"],
         "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}
    sql = _gen(repo_root)(MODEL, q)
    low = sql.lower()
    assert "agency.name" in low, f"the parent's column vanished from the projection:\n{sql}"
    assert "join agencies" in low, f"the parent is referenced but never joined:\n{sql}"
    assert sql.upper().count("JSON_ARRAYAGG") == 2


def test_the_rewrite_without_root_columns_is_valid_sql(repo_root: Path):
    """Every returned column inside a branch: the projection is just the two subqueries.
    'SELECT ,' is ORA-00936 — the reference errors and the whole pattern is unmeasurable."""
    import re
    q = {"root": "Res", "returns": ["Leg.flight_number", "Payment.amount"],
         "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}
    sql = _gen(repo_root)(MODEL, q)
    assert not re.search(r"SELECT\s*,", sql, re.I), f"empty projection head:\n{sql}"
    assert sql.upper().count("JSON_ARRAYAGG") == 2


def test_mn_far_side_joins_on_its_own_key(repo_root: Path):
    """The far side of an M:N joins on ITS OWN key. `flight.leg_id = resleg.leg_id` probes
    a column flights does not have (ORA-00904) — it only ever worked because every fixture
    used the same key name on both sides. Both spellings of the M:N are covered: the
    1:N INTO the junction and the N:1 OUT of it."""
    model = {
        "entities": {
            "Res":     {"table": "reservations", "pk": "res_id", "columns": {"status": "status"}},
            "ResLeg":  {"table": "res_legs", "pk": ["res_id", "leg_id"], "columns": {}},
            "Flight":  {"table": "flights", "pk": "id", "columns": {"flight_number": "flight_number"}},
            "ResPay":  {"table": "res_pays", "pk": ["res_id", "payment_ref"], "columns": {}},
            "Payment": {"table": "payments", "pk": "pay_id", "columns": {"amount": "amount"}},
        },
        "relationships": [
            {"from": "Res", "to": "ResLeg", "cardinality": "1:N", "from_key": "res_id", "to_key": "res_id"},
            {"from": "Flight", "to": "ResLeg", "cardinality": "1:N", "from_key": "id", "to_key": "leg_id"},
            {"from": "Res", "to": "ResPay", "cardinality": "1:N", "from_key": "res_id", "to_key": "res_id"},
            {"from": "ResPay", "to": "Payment", "cardinality": "N:1", "from_key": "payment_ref", "to_key": "pay_id"},
        ],
    }
    q = {"root": "Res", "returns": ["Res.status", "Flight.flight_number", "Payment.amount"],
         "predicates": [{"ref": "Res.res_id", "op": "=", "value": 1}]}
    sql = _gen(repo_root)(model, q).lower()
    assert "join flights flight on flight.id = resleg.leg_id" in sql, sql
    assert "flight.leg_id" not in sql, f"flights has no leg_id column:\n{sql}"
    assert "join payments payment on payment.pay_id = respay.payment_ref" in sql, sql


def test_a_single_child_collection_still_joins(repo_root: Path):
    """One child cannot fan out against anything — a plain join is correct AND cheaper.
    Do not pay for aggregation you do not need."""
    sql = _gen(repo_root)(MODEL, ONE_CHILD_Q).upper()
    assert "JSON_ARRAYAGG" not in sql, f"one child needs no aggregation:\n{sql}"
    assert "JOIN" in sql

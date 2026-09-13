# Copyright (c) 2026 Oracle and/or its affiliates.
"""A design must ANSWER the query before its speed means anything.

Twice now a design has been fast because it was returning less. The duality view nested the
junction tables and stopped — `itinerarylegs: [{reservation_id, leg_id}]`, no flight number,
no payment amount — so it never performed the joins the query required and "beat" relational
on a query that needs exactly those joins. Duality is not free joins; it wasn't doing them.
Before that, the "document" embedded nothing at all.

Both are the same failure: an unanswered query timed as though it were answered. A cost
matrix compares designs that all return the SAME answer, or it compares nothing.
"""
import sys
from pathlib import Path

import pytest


def _r(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    return r


QUERY = {"root": "Res", "returns": ["Res.status", "Leg.flight_number", "Payment.amount"]}
PATTERN = {"name": "get_itinerary", "kind": "read", "rate": 1, "query": QUERY}


def test_missing_fields_are_detected(repo_root: Path):
    """The exact duality bug: the answer carries the junction keys but not the payload."""
    r = _r(repo_root)
    rows = [{"_id": 1, "status": "OPEN",
             "itinerarylegs": [{"reservation_id": 1, "leg_id": 8}]}]     # no flight_number
    missing = r.unanswered(PATTERN, rows)
    assert "flight_number" in missing and "amount" in missing
    assert "status" not in missing


def test_a_complete_answer_passes(repo_root: Path):
    r = _r(repo_root)
    rows = [{"_id": 1, "status": "OPEN",
             "legs": [{"flight_number": "FL1"}],
             "payments": [{"amount": 250}]}]
    assert r.unanswered(PATTERN, rows) == []


def test_fields_may_be_spread_across_rows(repo_root: Path):
    """The single collection answers an item-collection read with one row PER TYPE — the
    reservation row has no flight_number and the leg row has no status. The answer is the
    result SET, so the check is a union across rows, not a test of any one row."""
    r = _r(repo_root)
    rows = [{"type": "ItineraryReservation", "status": "OPEN",
             "flight_number": None, "amount": None},
            {"type": "Leg", "status": None, "flight_number": "FL1", "amount": None},
            {"type": "Payment", "status": None, "flight_number": None, "amount": 250}]
    assert r.unanswered(PATTERN, rows) == []


def test_an_all_null_column_does_not_count_as_answered(repo_root: Path):
    """A relational row that has the column but never a value has not answered anything —
    this is how a broken join hides: the column is there, the data is not."""
    r = _r(repo_root)
    rows = [{"status": "OPEN", "flight_number": None, "amount": None}]
    assert set(r.unanswered(PATTERN, rows)) == {"flight_number", "amount"}


def test_aggregates_are_exempt(repo_root: Path):
    """An aggregation returns computed aliases, not the entity properties it grouped over."""
    r = _r(repo_root)
    agg = {"name": "kpi", "kind": "read", "rate": 1,
           "query": {"root": "Res", "group_by": ["Res.status"],
                     "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"}]}}
    assert r.unanswered(agg, [{"STATUS": "OPEN", "N": 3}]) == []


class _FakeCursor:
    def __init__(self, rowcount):
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, *args):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self, rowcount):
        self._rc = rowcount
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self._rc)

    def rollback(self):
        self.rollbacks += 1


WRITE_PATTERN = {
    "name": "update_total", "kind": "write", "rate": 800,
    "query": {"root": "Order", "returns": ["Order.total"],
              "predicates": [{"ref": "Order.order_id", "op": "=", "value": 999}]},
    "sql": {"relational": "UPDATE orders SET total = total + 1 WHERE order_id = 999"},
}


def test_a_write_that_matches_no_rows_is_a_measurement_error(repo_root: Path):
    """The write-side answer gate. A generated UPDATE against an item type the seed
    silently failed to populate touches 0 rows — near-zero elapsed, near-zero redo —
    and 'wins' every write row: fast because it did LESS, the exact failure the read
    gate exists to stop. A zero-rowcount write must invalidate the cell, not win it."""
    r = _r(repo_root)
    with pytest.raises(ValueError, match="no rows"):
        r.measure_cell(_FakeConn(rowcount=0), {}, WRITE_PATTERN, "relational",
                       trials=2, warmup=1)


def test_a_plsql_block_write_is_not_a_false_zero(repo_root: Path):
    """python-oracledb reports rowcount 0 after a BEGIN...END block even when its
    inner INSERTs succeeded (verified live: block inserts a row, rowcount stays 0).
    rowcount is only meaningful for a single DML statement — a block write must be
    measured, not invalidated. Caught re-running the airline capstone: the gate
    excluded relational's multi-INSERT create_reservation as 'touched no rows'."""
    block = dict(WRITE_PATTERN)
    block["sql"] = {"relational": ("BEGIN INSERT INTO orders (order_id) VALUES (1); "
                                   "INSERT INTO order_items (order_id) VALUES (1); END;")}
    r = _r(repo_root)
    cell = r.measure_cell(_FakeConn(rowcount=0), {}, block, "relational",
                          trials=2, warmup=1)
    assert cell["us"] >= 0


def test_a_write_that_touches_rows_is_measured_and_rolled_back(repo_root: Path):
    r = _r(repo_root)
    conn = _FakeConn(rowcount=1)
    cell = r.measure_cell(conn, {}, WRITE_PATTERN, "relational", trials=2, warmup=1)
    assert cell["us"] >= 0
    assert conn.rollbacks >= 3            # gate + warmup + trials all roll back


DV_MODEL = {
    "entities": {
        "Res":  {"table": "reservations", "pk": "res_id", "columns": {"status": "status"}},
        "ResLeg": {"table": "res_legs", "pk": ["res_id", "leg_id"], "columns": {}},
        "Leg":  {"table": "legs", "pk": "leg_id",
                 "columns": {"flight_number": "flight_number"}},
    },
    "relationships": [
        {"from": "Res", "to": "ResLeg", "cardinality": "1:N",
         "from_key": "res_id", "to_key": "res_id"},
        {"from": "Leg", "to": "ResLeg", "cardinality": "1:N",
         "from_key": "leg_id", "to_key": "leg_id"},
    ],
    "projections": {"duality": {"Res": "reservations_dv"}},
}


def test_duality_joins_through_the_junction_to_the_payload(repo_root):
    """Duality is NOT free joins. Nest the junction table and stop, and the view returns
    `[{res_id, leg_id}]` — the keys, never the flight number. It then does none of the work
    the query asked for and "beats" relational on a query that needs exactly those joins.
    The far side of an M:N must be @unnest-ed in, so the view really does the join."""
    import sys
    sys.path.insert(0, str(repo_root))
    from tooling.generate.ddl import generate_ddl

    ddl = generate_ddl(DV_MODEL, "duality")
    body = ddl.split("DUALITY VIEW")[1]
    assert "flight_number : flight_number" in body, \
        f"the view returns junction keys and no payload:\n{ddl}"
    assert "leg : legs @noinsert @noupdate @nodelete" in body, \
        f"the far side must be a NAMED nested object:\n{ddl}"
    # NOT @unnest: on 26ai Free an @unnest block without the far-side PK raises ORA-00600
    # [qjsnbzoUpdateRow:zero_pk_cols] and KILLS THE SESSION on any update through the view;
    # putting the PK inside the @unnest collides with the junction's copy (ORA-40473).
    assert "@unnest" not in body, f"@unnest crashes the session on update:\n{ddl}"

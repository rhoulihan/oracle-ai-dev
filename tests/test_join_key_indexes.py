# Copyright (c) 2026 Oracle and/or its affiliates.
"""Join keys are access paths too — index them, or the child full-scans.

Field-verified on the hotel capstone, twice: (I.7) generated reads that reach
a child join on the child's FK, which never appears as a predicate, so it got
no index and get_booking full-scanned two designs (1,012us -> 779us once
added by hand); (K) the same gap on the WRITE path cost 367ms at 775k rows —
16ms at small scale, where it read as 'write amplification' instead of a
missing index — and would have flipped the reported verdict.
"""

from tooling.generate.ddl import generate_indexes

MODEL = {
    "entities": {
        "Booking": {"table": "bookings", "pk": "booking_id",
                    "columns": {"status": "status"}},
        "Line": {"table": "booking_lines", "pk": "line_id",
                 "columns": {"qty": "qty", "roomType": "room_type"}},
    },
    "relationships": [
        {"from": "Booking", "to": "Line", "from_key": "booking_id",
         "to_key": "booking_id", "cardinality": "1:N"},
    ],
    "projections": {"document": {"Booking": {"collection": "booking_docs"}}},
}

READ = {"root": "Booking", "returns": ["Booking.status", "Line.qty"],
        "predicates": [{"ref": "Booking.booking_id", "op": "=", "value": 7}]}


def test_a_child_reached_by_a_read_gets_its_join_key_indexed():
    idx = generate_indexes(MODEL, [READ], shape="relational")
    assert "CREATE INDEX booking_lines_booking_id_ix ON booking_lines (booking_id);" in idx, idx


def test_the_duality_lane_gets_the_same_base_table_join_index():
    # duality reads rewrite onto base-table B-trees (measured 43x) and child
    # writes through the view scope by the same FK — same index serves both.
    idx = generate_indexes(MODEL, [READ], shape="duality")
    assert "booking_lines_booking_id_ix" in idx, idx


def test_a_write_patterns_query_also_derives_the_join_index():
    # deploy feeds every pattern's query to derivation — a write scoping child
    # rows by the root's key needs the same index (the 367ms -> 2ms cell).
    write_q = {"root": "Booking", "returns": ["Line.qty"],
               "predicates": [{"ref": "Booking.booking_id", "op": "=", "value": 7}]}
    idx = generate_indexes(MODEL, [write_q], shape="relational")
    assert "booking_lines_booking_id_ix" in idx, idx


def test_join_key_index_dedupes_against_a_predicate_derived_one():
    q2 = {"root": "Line", "returns": ["Line.qty"],
          "predicates": [{"ref": "Line.booking_id", "op": "=", "value": 7}]}
    m = dict(MODEL)
    m["entities"] = dict(MODEL["entities"])
    m["entities"]["Line"] = dict(MODEL["entities"]["Line"],
                                 columns={"qty": "qty", "booking_id": "booking_id"})
    idx = generate_indexes(m, [READ, q2], shape="relational")
    assert idx.count("ON booking_lines (booking_id)") == 1, idx

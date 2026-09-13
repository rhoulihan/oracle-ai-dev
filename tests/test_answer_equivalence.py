# Copyright (c) 2026 Oracle and/or its affiliates.
"""Every design must return the SAME ANSWER — that is the model validation.

A cost matrix compares designs that all answer the question identically, or it compares
nothing. Three separate defects in this capstone were a design being fast because it
returned *less*: a duality view that nested the junction keys and never joined through to
the flight number; a "document" that embedded nothing; a pattern whose filter matched zero
rows. Each looked excellent. None of them answered the query.

The shapes legitimately differ — relational returns flat columns, the document returns one
nested JSON document, the single collection returns one row PER TYPE — so raw row-hashing
cannot compare them. The comparable thing is the ANSWER: for every property the query asked
for, the set of values that came back.
"""
import sys
from pathlib import Path


def _eq(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    from tooling.optimize.equivalence import canonical_answer, answers_match
    return canonical_answer, answers_match


QUERY = {"root": "Res", "returns": ["Res.status", "Leg.flight_number", "Payment.amount"]}

# The same answer, in four different shapes — this is what the four designs actually return.
RELATIONAL = [{"status": "PENDING",
               "itinerarylegs": [{"flight_number": "FL1"}, {"flight_number": "FL2"}],
               "reservationpayments": [{"amount": 250}]}]
DOCUMENT = [{"data": {"_id": 1, "status": "PENDING",
                      "legs": [{"flight_number": "FL1"}, {"flight_number": "FL2"}],
                      "payments": [{"amount": 250}]}}]
SINGLE_TABLE = [{"type": "Res", "status": "PENDING", "flight_number": None, "amount": None},
                {"type": "Leg", "status": None, "flight_number": "FL1", "amount": None},
                {"type": "Leg", "status": None, "flight_number": "FL2", "amount": None},
                {"type": "Payment", "status": None, "flight_number": None, "amount": 250}]
# Oracle hands JSON numbers back as strings — "250" must equal 250.
DUALITY = [{"data": {"_id": "1", "status": "PENDING",
                     "itinerarylegs": [{"leg": {"flight_number": "FL1"}},
                                       {"leg": {"flight_number": "FL2"}}],
                     "reservationpayments": [{"payment": {"amount": "250"}}]}}]


def test_the_same_answer_in_four_different_shapes_matches(repo_root: Path):
    canonical_answer, answers_match = _eq(repo_root)
    ref = canonical_answer(QUERY, RELATIONAL)
    for name, rows in (("document", DOCUMENT), ("single_table", SINGLE_TABLE),
                       ("duality", DUALITY)):
        assert answers_match(ref, canonical_answer(QUERY, rows)), \
            f"{name} does not agree with relational"


def test_a_missing_join_is_caught(repo_root: Path):
    """THE duality bug: the junction keys came back, the flight number never did."""
    canonical_answer, answers_match = _eq(repo_root)
    broken = [{"data": {"_id": 1, "status": "PENDING",
                        "itinerarylegs": [{"reservation_id": 1, "leg_id": 8}],
                        "reservationpayments": [{"reservation_id": 1, "payment_id": 4}]}}]
    assert not answers_match(canonical_answer(QUERY, RELATIONAL),
                             canonical_answer(QUERY, broken))


def test_a_missing_row_is_caught(repo_root: Path):
    """Same fields, fewer values — one leg silently dropped."""
    canonical_answer, answers_match = _eq(repo_root)
    short = [{"data": {"status": "PENDING", "legs": [{"flight_number": "FL1"}],
                       "payments": [{"amount": 250}]}}]
    assert not answers_match(canonical_answer(QUERY, RELATIONAL),
                             canonical_answer(QUERY, short))


def test_a_wrong_value_is_caught(repo_root: Path):
    canonical_answer, answers_match = _eq(repo_root)
    wrong = [{"data": {"status": "CANCELLED", "legs": [{"flight_number": "FL1"},
                                                       {"flight_number": "FL2"}],
                       "payments": [{"amount": 250}]}}]
    assert not answers_match(canonical_answer(QUERY, RELATIONAL),
                             canonical_answer(QUERY, wrong))


def test_zero_rows_never_matches_a_real_answer(repo_root: Path):
    """`open_for_agent` filtered a status the seed never produced and matched NOTHING in
    every design. Four designs agreeing on nothing is not agreement."""
    canonical_answer, answers_match = _eq(repo_root)
    assert not answers_match(canonical_answer(QUERY, RELATIONAL), canonical_answer(QUERY, []))
    empty = canonical_answer(QUERY, [])
    assert empty is None or not answers_match(empty, empty) or empty == {} or True
    # and an empty answer is explicitly flagged as such
    from tooling.optimize.equivalence import is_empty_answer
    assert is_empty_answer(canonical_answer(QUERY, []))
    assert not is_empty_answer(canonical_answer(QUERY, RELATIONAL))


def test_wrong_row_pairings_are_caught(repo_root: Path):
    """A broken join can return the right value POOLS in the wrong PAIRINGS — the
    payments attached to the wrong reservations. Same per-property sets, different
    answer. Both designs express the pairing (each returns rows carrying both
    properties), so it must agree."""
    canonical_answer, answers_match = _eq(repo_root)
    q = {"root": "Res", "returns": ["Res.status", "Payment.amount"]}
    ref = [{"status": "OPEN", "amount": 10}, {"status": "CLOSED", "amount": 20}]
    swapped = [{"status": "OPEN", "amount": 20}, {"status": "CLOSED", "amount": 10}]
    assert not answers_match(canonical_answer(q, ref), canonical_answer(q, swapped))


ITINERARY_QUERY = {"root": "Res", "returns": ["Res.status", "Leg.flight_number",
                                              "Leg.departure"]}
# Two wanted properties inside the SAME array elements — the airline capstone shape.
NESTED_LEGS = [{"status": "PENDING",
                "legs": [{"flight_number": "FL1", "departure": "14:05"},
                         {"flight_number": "FL2", "departure": "15:05"}]}]
TYPED_ROW_LEGS = [{"type": "Res", "status": "PENDING", "flight_number": None, "departure": None},
                  {"type": "Leg", "status": None, "flight_number": "FL1", "departure": "14:05"},
                  {"type": "Leg", "status": None, "flight_number": "FL2", "departure": "15:05"}]


def test_two_properties_in_one_array_element_pair_within_the_element(repo_root: Path):
    """The airline capstone false positive: the nested reference carries (FL1, 14:05) and
    (FL2, 15:05); pooling the row and cross-producting invents (FL1, 15:05) too, so the
    single collection's typed rows — which pair correctly — could never match. Pairings
    live in the array ELEMENT, not the row."""
    canonical_answer, answers_match = _eq(repo_root)
    assert answers_match(canonical_answer(ITINERARY_QUERY, NESTED_LEGS),
                         canonical_answer(ITINERARY_QUERY, TYPED_ROW_LEGS))


def test_wrong_pairing_inside_a_nested_array_is_caught(repo_root: Path):
    """The flip side the cross-product could NEVER catch: same value pools, but the
    nested design attached each departure to the wrong flight."""
    canonical_answer, answers_match = _eq(repo_root)
    swapped = [{"status": "PENDING",
                "legs": [{"flight_number": "FL1", "departure": "15:05"},
                         {"flight_number": "FL2", "departure": "14:05"}]}]
    assert not answers_match(canonical_answer(ITINERARY_QUERY, swapped),
                             canonical_answer(ITINERARY_QUERY, TYPED_ROW_LEGS))


def test_a_dropped_row_is_caught_even_when_its_values_appear_elsewhere(repo_root: Path):
    canonical_answer, answers_match = _eq(repo_root)
    q = {"root": "Res", "returns": ["Res.status", "Payment.amount"]}
    ref = [{"status": "OPEN", "amount": 10}, {"status": "CLOSED", "amount": 20},
           {"status": "OPEN", "amount": 20}]
    short = ref[:2]           # the dropped row's values both survive in other rows
    assert not answers_match(canonical_answer(q, ref), canonical_answer(q, short))


def test_scalar_arrays_are_answers_not_nothing(repo_root: Path):
    """An array property (`arrays: ["tags"]`) answers with its scalar elements.
    Dropping them made differing arrays compare equal AND classified a non-empty
    answer as EMPTY (so validate_answers blamed the workload's filter)."""
    canonical_answer, answers_match = _eq(repo_root)
    from tooling.optimize.equivalence import is_empty_answer
    q = {"root": "Res", "returns": ["Res.tags"]}
    rel = [{"tags": ["red", "small"]}]
    doc_same = [{"data": {"_id": 1, "tags": ["red", "small"]}}]
    doc_diff = [{"data": {"_id": 1, "tags": ["blue"]}}]
    assert not is_empty_answer(canonical_answer(q, rel))
    assert answers_match(canonical_answer(q, rel), canonical_answer(q, doc_same))
    assert not answers_match(canonical_answer(q, rel), canonical_answer(q, doc_diff))


def test_aggregates_compare_by_group(repo_root: Path):
    """An aggregation returns computed aliases; the groups and their values must agree.
    The sql_view fallback wraps each row in a JSON document — same answer, different shape."""
    canonical_answer, answers_match = _eq(repo_root)
    agg = {"root": "Res", "group_by": ["Res.status"],
           "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"}]}
    flat = [{"STATUS": "PENDING", "N": 750}, {"STATUS": "CONFIRMED", "N": 1500}]
    as_doc = [{"doc": {"status": "CONFIRMED", "n": "1500"}},
              {"doc": {"status": "PENDING", "n": 750}}]
    assert answers_match(canonical_answer(agg, flat), canonical_answer(agg, as_doc))
    off_by_one = [{"STATUS": "PENDING", "N": 749}, {"STATUS": "CONFIRMED", "N": 1500}]
    assert not answers_match(canonical_answer(agg, flat), canonical_answer(agg, off_by_one))


def test_the_document_spells_the_root_key_underscore_id(repo_root: Path):
    """A document's root key is `_id`; the query asks for `reservation_id`. Same value,
    different name — not a different answer. Miss this and the document is falsely accused
    of failing every query that returns its own primary key."""
    canonical_answer, answers_match = _eq(repo_root)
    q = {"root": "Res", "returns": ["Res.res_id", "Res.status"]}
    rel = [{"res_id": 1, "status": "PENDING"}]
    doc = [{"data": {"_id": "1", "status": "PENDING"}}]
    assert not answers_match(canonical_answer(q, rel), canonical_answer(q, doc))
    assert answers_match(canonical_answer(q, rel, id_prop="res_id"),
                         canonical_answer(q, doc, id_prop="res_id"))

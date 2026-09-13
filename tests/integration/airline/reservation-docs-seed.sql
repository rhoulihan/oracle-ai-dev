-- Populate the candidate DOCUMENT shape from the relational overlay, so every design holds
-- the same data and the measurement is apples-to-apples.
--
-- The legs and the payments are EMBEDDED. This is the whole point of the document design:
-- one read returns the entire itinerary, no joins. Store only the reservation scalars and
-- the "document" is just a JSON-wrapped row — it pays all of a document's write
-- amplification (every status change rewrites the doc) and earns none of its read
-- consolidation, so it loses every column of the matrix for a reason that is an artifact
-- of the fixture rather than a property of the design.
DELETE FROM reservation_docs;
INSERT INTO reservation_docs (data)
SELECT JSON_OBJECT(
         '_id' VALUE r.reservation_id,
         'passenger_id' VALUE r.passenger_id,
         'agent_id' VALUE r.agent_id,
         'reservation_status_code' VALUE r.reservation_status_code,
         'ticket_type_code' VALUE r.ticket_type_code,
         'travel_class_code' VALUE r.travel_class_code,
         'number_in_party' VALUE r.number_in_party,
         -- EXTENDED REFERENCE: the passenger's name is denormalized onto the reservation.
         -- `passenger_history` returns it alongside the reservation, and a document that
         -- does not carry it cannot answer that query at all — it would have to join back
         -- to `passengers`, which is the one thing the document design exists to avoid.
         -- This is what a document modeller actually does, and it is what the answer gate
         -- (tooling/optimize/runner.py::unanswered) forces us to be honest about.
         'last_name' VALUE (SELECT p.last_name FROM passengers p
                            WHERE p.passenger_id = r.passenger_id),
         'legs' VALUE (
           SELECT JSON_ARRAYAGG(JSON_OBJECT(
                    'leg_id' VALUE l.leg_id,
                    'flight_number' VALUE l.flight_number,
                    'origin_airport_code' VALUE l.origin_airport_code,
                    'destination_airport_code' VALUE l.destination_airport_code,
                    'actual_departure_time' VALUE l.actual_departure_time,
                    'actual_arrival_time' VALUE l.actual_arrival_time
                  RETURNING JSON) RETURNING JSON)
           FROM itinerary_legs il
           JOIN legs l ON l.leg_id = il.leg_id
           WHERE il.reservation_id = r.reservation_id),
         'payments' VALUE (
           SELECT JSON_ARRAYAGG(JSON_OBJECT(
                    'payment_id' VALUE p.payment_id,
                    'payment_status_code' VALUE p.payment_status_code,
                    'payment_date' VALUE p.payment_date,
                    'payment_amount' VALUE p.payment_amount
                  RETURNING JSON) RETURNING JSON)
           FROM reservation_payments rp
           JOIN payments p ON p.payment_id = rp.payment_id
           WHERE rp.reservation_id = r.reservation_id)
       RETURNING JSON)
FROM itinerary_reservations r

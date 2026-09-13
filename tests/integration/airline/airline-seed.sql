-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Sample data for the real airline-reservations relational overlay (DataBaseAnswers
-- model). Populates the FK targets, then itinerary_reservations and its junctions.
-- Idempotent for the transactional tables. Typed/code PKs (airport_code, flight_number,
-- day_date) and composite-PK junctions (reservation_payments, itinerary_legs).
SET FEEDBACK OFF
DEFINE reservations = 30000
DEFINE passengers = 20000
DEFINE agents = 200
DEFINE payments_n = 10000
DEFINE legs_n = 8000
DEFINE flights_n = 2000
DEFINE airports_n = 20

DELETE FROM itinerary_legs;
DELETE FROM reservation_payments;
DELETE FROM itinerary_reservations;
DELETE FROM legs;
DELETE FROM flight_schedules;

-- reference pools (typed/code PKs)
INSERT INTO airports (airport_code, airport_name, airport_location, other_details)
SELECT 'AP' || LPAD(lvl, 2, '0'), 'Airport ' || lvl, 'City ' || lvl, 'details'
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &airports_n) x
WHERE NOT EXISTS (SELECT 1 FROM airports a WHERE a.airport_code = 'AP' || LPAD(x.lvl, 2, '0'));

INSERT INTO flight_schedules (flight_number, airline_code, usual_aircraft_type_code,
       origin_airport_code, destination_airport_code, departure_date_time, arrival_date_time)
SELECT 'FL' || LPAD(lvl, 5, '0'), 'AL' || MOD(lvl, 8), 'AC' || MOD(lvl, 5),
       'AP' || LPAD(MOD(lvl, &airports_n) + 1, 2, '0'),
       'AP' || LPAD(MOD(lvl + 3, &airports_n) + 1, 2, '0'),
       TIMESTAMP '2026-08-01 06:00:00' + NUMTODSINTERVAL(lvl, 'HOUR'),
       TIMESTAMP '2026-08-01 09:00:00' + NUMTODSINTERVAL(lvl, 'HOUR')
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &flights_n) x;

INSERT INTO booking_agents (agent_id, agent_name, agent_details)
SELECT lvl, 'Agent ' || lvl, 'agent details ' || lvl
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &agents) x
WHERE NOT EXISTS (SELECT 1 FROM booking_agents b WHERE b.agent_id = x.lvl);

INSERT INTO passengers (passenger_id, first_name, second_name, last_name, phone_number,
       email_address, address_lines, city, state_province_county, country, other_passenger_details)
SELECT lvl, 'First' || lvl, 'Mid' || lvl, 'Last' || lvl, '555-' || LPAD(lvl, 6, '0'),
       'pax' || lvl || '@example.test', lvl || ' Main St', 'City ' || MOD(lvl, 50),
       'State ' || MOD(lvl, 20), 'Country ' || MOD(lvl, 10), NULL
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &passengers) x
WHERE NOT EXISTS (SELECT 1 FROM passengers p WHERE p.passenger_id = x.lvl);

INSERT INTO payments (payment_id, payment_status_code, payment_date, payment_amount)
SELECT lvl, CASE MOD(lvl, 3) WHEN 0 THEN 'PAID' WHEN 1 THEN 'PENDING' ELSE 'REFUNDED' END,
       TIMESTAMP '2026-07-01 00:00:00' + NUMTODSINTERVAL(MOD(lvl, 500), 'HOUR'),
       100 + MOD(lvl * 7, 900)
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &payments_n) x
WHERE NOT EXISTS (SELECT 1 FROM payments p WHERE p.payment_id = x.lvl);

INSERT INTO legs (leg_id, flight_number, origin_airport_code, destination_airport_code,
       actual_departure_time, actual_arrival_time)
SELECT lvl, 'FL' || LPAD(MOD(lvl, &flights_n) + 1, 5, '0'),
       'AP' || LPAD(MOD(lvl, &airports_n) + 1, 2, '0'),
       'AP' || LPAD(MOD(lvl + 5, &airports_n) + 1, 2, '0'),
       TIMESTAMP '2026-08-01 06:05:00' + NUMTODSINTERVAL(lvl, 'HOUR'),
       TIMESTAMP '2026-08-01 09:05:00' + NUMTODSINTERVAL(lvl, 'HOUR')
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &legs_n) x;

-- reservations (the aggregate root)
INSERT INTO itinerary_reservations (reservation_id, agent_id, passenger_id,
       reservation_status_code, ticket_type_code, travel_class_code,
       date_reservation_made, number_in_party)
SELECT lvl, MOD(lvl, &agents) + 1, MOD(lvl, &passengers) + 1,
       CASE MOD(lvl, 4) WHEN 0 THEN 'CANCELLED' WHEN 1 THEN 'PENDING' ELSE 'CONFIRMED' END,
       CASE MOD(lvl, 3) WHEN 0 THEN 'ONEWAY' ELSE 'RETURN' END,
       CASE MOD(lvl, 5) WHEN 0 THEN 'FIRST' WHEN 1 THEN 'BUSINESS' ELSE 'ECONOMY' END,
       TIMESTAMP '2026-07-01 00:00:00' + NUMTODSINTERVAL(MOD(lvl, 720), 'HOUR'),
       1 + MOD(lvl, 4)
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &reservations);

-- Junctions (composite PKs). FAN-OUT MATTERS: give every reservation exactly one leg and
-- one payment and the aggregate has nothing to aggregate — the join returns a single row,
-- so a consolidated design has nothing to save and the matrix is quietly rigged against
-- it. A real itinerary is a round trip, often with connections (2-6 legs), and is usually
-- paid in one or two instalments. Deterministic, not random: n consecutive ids mod the
-- pool size are distinct, so no composite-PK collision.
INSERT INTO reservation_payments (reservation_id, payment_id)
SELECT r.reservation_id, MOD(r.reservation_id * 2 + n.n, &payments_n) + 1
FROM itinerary_reservations r
CROSS JOIN (SELECT LEVEL AS n FROM dual CONNECT BY LEVEL <= 2) n
WHERE n.n <= 1 + MOD(r.reservation_id, 2);            -- 1-2 payments

INSERT INTO itinerary_legs (reservation_id, leg_id)
SELECT r.reservation_id, MOD(r.reservation_id * 6 + n.n, &legs_n) + 1
FROM itinerary_reservations r
CROSS JOIN (SELECT LEVEL AS n FROM dual CONNECT BY LEVEL <= 6) n
WHERE n.n <= 2 + MOD(r.reservation_id, 5);            -- 2-6 legs (return + connections)

COMMIT;

SELECT (SELECT COUNT(*) FROM itinerary_reservations) AS reservations,
       (SELECT COUNT(*) FROM passengers)             AS passengers,
       (SELECT COUNT(*) FROM reservation_payments)   AS res_payments,
       (SELECT COUNT(*) FROM itinerary_legs)         AS res_legs
FROM dual;

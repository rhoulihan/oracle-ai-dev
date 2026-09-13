# Airline reservations — full integration test (capstone)

An end-to-end, adversarial exercise of the whole plugin against **live** Oracle AI
Database 26ai Free, using a standard normalized airline-reservation model.

## What it covers
1. **Model** (`model.json`) — Passenger, Airport, Aircraft, Flight, Booking,
   Ticket, with the Booking aggregate projected to a document collection and a
   duality view.
2. **Schema + data** (`schema.sql`, `airline-seed.sql`) — deployed and loaded on a
   live Free container. The checked-in seed is 30,000 reservations (CI-friendly);
   the published matrix (`optimizer-result.txt`) is a **production-volume run:
   300,000 reservations / 200,000 passengers / 1.2M itinerary-leg rows** (seed
   DEFINEs ×10 — scale-safe: the flight-number pad is width 5, guarded by
   `tests/test_seed_scale_safety.py`), identical across all four shapes.
3. **Optimizer** (`optimizer-result.txt`) — the full 10-pattern × 4-design matrix
   measured on live data (median elapsed, per-cell CV, EXPLAIN-verified access
   paths), answer-validated per pattern, then `recommend_model` with
   reservation-workload rates. Run 2026-07-14 with the post-review engine.
4. **Data layer** (`datalayer/`) — generated for the chosen shape for all five
   runtimes, plus `schema.sql` + `deploy.sh`.
5. **Cross-runtime validation** (`harness/`, `RESULTS.md`) — a harness per runtime
   (python-oracledb, node-oracledb, ODP.NET, Oracle JDBC, go-ora) runs every
   generated method against the live schema; `canonical_hash` proves the results
   are identical across all five.

## Key findings (live, production volume, 2026-07-14)
- **Every design answers every pattern identically** — the answer gate passes 10/10
  patterns across all four designs with zero measurement-error exclusions.
- Point reads are index-served everywhere now: reservation point read = 3 logical
  reads on document, duality, AND relational. (The earlier published "document 191
  — full collection scan" was the missing-`_id`-index generator defect, fixed in
  the 2026-07-14 review; access-pattern-derived indexes now deploy with the design.)
- The itinerary aggregate read is where shapes separate: document IDX RANGE 3
  logical reads vs 21 for duality/relational (the join is pre-paid at write time).
- Verdict, stated the way the engine states it: real reservation mix — document
  leads by 7.4%, **inside the run's 17.7% noise floor → TIED** (document, relational,
  duality). Scenario splits: document wins every read-heavy mix (7–8%), relational
  wins the write-heavy booking engine (5.0%) and the shrunk dominant-read tail.
  Shape choice is a workload decision, not a dogma — which is the plugin's thesis.
- **All four datalayer methods return identical results across all five runtimes**
  (re-proven 2026-07-14 with the regenerated datalayer: ALL CONSISTENT).

## Bugs this test caught (all fixed)
- DDL: FK columns that are also projected columns were typed VARCHAR2 by name
  inference (ORA-02267). Now forced NUMBER.
- DDL: substring type inference false-positives (`country`→count,
  `tail_number`/`flight_number`→num, `fare_class`→fare, ORA-01722). Replaced with
  whole-token matching.
- Datalayer: the generated C# `Connect()` used escaped quotes inside an
  interpolated string (invalid C#). Now reads env vars into locals first.
- Harness drift (2026-07-14): the five runtime mains — and the embedded
  repositories in the compiled harnesses — still called the previous era's
  booking-named methods, so cross-runtime validation could not run against the
  checked-in datalayer at all. Mains updated, repositories propagated, re-proven.
- Seed: `LPAD(…, 4)` silently truncated flight numbers above 9,999 flights — at
  ×10 volume the PK collision zeroed out every leg (caught by the answer gate).
  Pad widened to 5 in the checked-in seed; regression-guarded by
  `tests/test_seed_scale_safety.py`.

## Re-running
Deploy the schema + seed on a live DB, then `harness/run.sh` (needs python3, node,
java+maven, go, dotnet, and the drivers). go-ora stands in for godror where Oracle
Instant Client is unavailable.

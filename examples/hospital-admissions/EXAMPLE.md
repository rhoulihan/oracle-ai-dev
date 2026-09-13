# Example: Hospital Admissions — a data layer, modeled by measurement

A real, end-to-end session (2026-07-15) where a developer handed the plugin a
product-management spec and a DBA's schema and asked it to design an optimized Oracle
26ai data layer. This directory is the **verbatim output** of that session — the
access-pattern catalog, the workload the optimizer ran, the measured cost matrix, the
elected DDL, a dual-surface (SQL vs MongoDB API) benchmark, a working Java data layer,
and a full [session log](./session-log.md). Nothing here was hand-tuned after the fact.

## What the developer asked for

> *"I am building a hospital admissions service and received a schema design doc and
> business rules from product management, plus a database schema from the DBA. Our
> backend target is Oracle 26ai — define the core access patterns we need to satisfy
> the business rules and optimize the data model."*

The attached ERD was a classic fully-normalized 11-table design (patients, a shared
addresses table with two junction tables, bills, bill-items, rooms, a polymorphic
records table…). Mid-session the developer added four more asks: **stand up a fresh
container, benchmark on both native SQL and the MongoDB API, and build a Java data
layer for both.**

## What the skill did

The prompt routed to **`oracle-data-modeling`**, whose thesis is that shape choice is
a *measurement*, not a matter of taste. Its brownfield path ran:

1. **Intake as gap analysis** → an [access-pattern catalog](./data_requirements.md):
   12 reads + 7 writes with frequency / cardinality / latency dials, ranked 70/20/10.
   The clinical hot path (patient chart, clinical-record writes) earns the optimized
   shape.
2. **Four candidate designs, from reasoning** — the DBA's normalized relational
   (baseline), relational + duality views, document collections, and a DynamoDB-style
   patient-anchored single-table projection.
3. **The winner, from measurement** — `oracle-ai-setup` brought up a real 26ai Free
   stack (DB + ORDS + MongoDB API); the optimizer deployed all four designs, seeded
   them identically (5,000 patients / 75,000 clinical records / 60,000 bill items /
   15,000 room stays), **validated every design returns the same answers before
   timing** (equivalence before speed), then measured reads *and writes* as
   first-class rows over 25 trials per cell.

Every failure along the way was a modeling lesson, logged: a composite natural key that
can't anchor a duality view (`ORA-42647`), document `null` vs key-absence semantics
caught by the equivalence gate, an aggregation index that needed the trailing-constant
covering trick. See [`data_model.md`](./data_model.md) §2 and the [session log](./session-log.md) §7.3.

## The result

**Keep the DBA's relational schema — corrected and indexed to the access patterns — as
the system of record, and serve document consumers through duality views / the MongoDB
API where they need them.** The full verdict, cost matrix, and severity-ranked schema
critique are in [`data_model.md`](./data_model.md). The headline measurements:

- **Relational and pure-document are statistically tied** on the estimated workload —
  38.51M vs 38.59M weighted µs, a **0.2% margin inside the noise floor**. The plugin
  refused to call a winner there and instead reported *when the tie breaks*: writes and
  reporting favor relational (analytics separates by **61.5%**), while a read-dominant
  patient-portal mix (everything but the chart read shrunk ≤0.3×) flips to document.
- **Documents win every patient-centered read** (~300µs vs ~510µs — one fetch of a
  pre-joined aggregate) but **lose every write** to amplification (rewriting an
  embedded-items bill: 1,326µs vs 1,147µs) and lose absence-state sweeps by 5–10×
  ("no discharge date yet" is key-absence, which has no B-tree path).
- **The 20× index lesson, across API surfaces.** A chart read via the MongoDB API first
  measured **38.6ms**; creating the index *through the Mongo API* dropped it to
  **1.9ms**. The SQL-created functional index didn't match the Mongo-translated
  predicate — the "index expression must match the query" rule holds across surfaces.
- **The Java data layer runs green.** `HospitalRepository` with JDBC and MongoDB-driver
  implementations; `mvn verify` is **13/13**, including cross-surface tests asserting
  both return *identical* results ([surefire report](./datalayer-java/surefire-reports/com.hospital.datalayer.RepositoryEquivalenceTest.txt)).

## What's in here

| Path | What it is |
|---|---|
| [`data_requirements.md`](./data_requirements.md) | The access-pattern catalog (deliverable 1) |
| [`data_model.md`](./data_model.md) | The verdict, cost matrix, schema critique, elected DDL, review-checklist gate |
| [`optimize/workload.json`](./optimize/workload.json) | The 11-entity model + 15 patterns + 4 candidate designs the optimizer ran |
| [`optimize/hospital-seed.sql`](./optimize/hospital-seed.sql), [`hospital-docs-seed.sql`](./optimize/hospital-docs-seed.sql) | Identical data seeded into every design (relational overlay → documents) |
| [`optimize/out/schema.relational.sql`](./optimize/out/schema.relational.sql) | The **elected DDL** (winning design, deployed and measured) |
| [`optimize/out/surface_results.json`](./optimize/out/surface_results.json) | Raw SQL-vs-Mongo-API measurements |
| [`optimize/surface_bench.py`](./optimize/surface_bench.py) | The dual-surface, equivalence-gated benchmark harness |
| [`datalayer-java/`](./datalayer-java/) | The Java data layer: shared interface + JDBC & Mongo implementations + equivalence tests |
| [`docker/`](./docker/) | The compose profile the session ran on (`.env.example` — set your own password) |
| [`session-log.md`](./session-log.md) | The full chronological session log, kept for a write-up |

## Reproduce

The exact commands are in [`data_model.md`](./data_model.md) §6. In short: bring up the
`docker/` compose profile, point `DB_USER`/`DB_PASSWORD`/`DB_DSN` at it, run
`python -m tooling.optimize optimize/workload.json --out optimize/out --fresh --trials 25`,
then `optimize/surface_bench.py` and `cd datalayer-java && mvn verify`.

> **These numbers are one run on one machine (Oracle 26ai Free, WSL2 Docker), on an
> *estimated* workload.** They demonstrate the method — measure your candidates on your
> data — not universal constants. The plugin says so too: the rates are assumptions to
> validate with product management, and the two schema corrections (surrogate stay key,
> billable-code linkage) are for the DBA to confirm.

# Session Log — Hospital Admissions Modeling on Oracle 26ai

Chronological log of the full Claude Code session, kept for a blog post on the
`oracle-ai-dev` skill. User inputs are verbatim; assistant actions and outputs are
recorded faithfully with the key content of each step. Appended to as the session
progresses.

Session date: 2026-07-15. Model: Claude Fable 5. Working directory:
`~/sandbox` (empty at session start).

---

## 1. Initial prompt (user, verbatim)

> I am building a hospital admissions service and received a schema design doc and
> these business rules from the product management team as well as a datbases schema
> from the DBA assigned to my project. Our backend target is Oracle 26ai and I need
> you to define the core set of access patterns we will need to satisfy those
> business rules and optimize the data model. Business Rules:
> A Patient can have one or many Addresses.
> A Patient can stay in one or many Rooms during a stay in the Hospital.
> A Patient can have one or many Bills.
> Each Patient Bill can have one or many Bill Items.
> Each Patient can have one or many Patient Records.
> Each Patient Record can be for a different Record Component, such as Admission, Diagnosis, Medication etc..
> A Patient can have one or many Methods of Payment.
> Staff can have one or many Addresses.

Attached: `admissions_schema.gif` — a classic fully-normalized ERD with 10 tables:
`Staff`, `Addresses`, `Patients`, `Patient_Payment_Methods`, `Staff_Addresses`,
`Patient_Addresses`, `Patient_Bills`, `Patient_Rooms`, `Record_Components`,
`Patient_Records`, `Patient_Bill_Items`. Junction tables link Staff/Patients to a
shared Addresses table; `Patient_Records` carries `component_code`,
`billable_item_code`, `updated_by_staff_id`, `admission_datetime`,
`medical_condition` on every row.

## 2. Skill routing (assistant)

- Recognized the task as a data-model design/review → invoked
  **`oracle-ai-dev:oracle-data-modeling`** (Unified Model Theory) before any other
  response, per the skill-first rule.
- Loaded shared memory index per global CLAUDE.md.

The skill's brownfield path applied: run the modeling intake as a gap analysis,
derive the access patterns, propose diverse candidate physical models, and let a
**measured benchmark** (`python -m tooling.optimize`) elect the winner — candidates
come from reasoning, the winner from measurement.

## 3. Research + plan mode (assistant)

Read the skill references:
- `umt-methodology.md` — canonical form / projected shapes; the three physical
  strategies (JSON collection, single collection + multivalue index, relational +
  duality); 70/20/10 frequency ranking; "duality views are read-time joins — wrong
  for write-heavy hot paths."
- `decision-rules.md` — embed bounded/owned/co-accessed children; reference
  unbounded/shared; write-hot short-circuits to single collection.
- `optimization.md` — the six-step measured loop; cost matrix with **writes as
  first-class rows**; equivalence before speed; "index the ACCESS PATTERN, not just
  its filters" (the trailing-constant covering-index trick); the document → duality
  → single-table → normalized walk as write pressure climbs.
- `patterns.md` — the 17-pattern catalog mapped to Oracle realizations.
- `review-checklist.md` — the 11-item gate for the final data model.

Entered plan mode (per Rick's plan-mode-default rule). Environment findings:
- Sandbox directory empty; no Oracle DB container running (only `soda-research-ords`,
  `workshop-app`, `ben-ten-server`).
- Image `container-registry.oracle.com/database/free:latest` already pulled.
- Optimizer tooling at `~/.claude/plugins/cache/oracle-ai-dev-marketplace/oracle-ai-dev/0.1.0/tooling/`;
  workload spec = `{"model": ModelSpec, "patterns": [QuerySpec...], "seed": sql}`.
- Host Python 3.12, `oracledb` not installed.

## 4. Clarifying questions (AskUserQuestion)

- **Depth**: reasoned design doc vs full measured benchmark → **Measured benchmark**
  (deploy all candidates, seed, benchmark reads AND writes, cost matrix elects).
- **Workload**: real rates vs estimated profile → **Estimate typical profile**
  (mid-size hospital, assumptions stated explicitly).

## 5. Mid-planning additions (user, verbatim)

While the plan was being written, four additions arrived:

> create a new container for this with the oracle skill

> benchmark with the mongodb api

> and native sql

> build a data layer library for both in Java

Plan updated: fresh 26ai Free stack via `oracle-ai-setup` with the ORDS + MongoDB API
profile; a dual-surface benchmark (native SQL vs Oracle API for MongoDB, equivalence-
checked); and a Java data layer with a shared repository interface and two
implementations (Oracle JDBC + MongoDB Java driver).

## 6. Plan approval (user, verbatim)

First ExitPlanMode was answered with:

> yes, and use auto mode. also please write out this entire conversation from the
> beginning to a log file including all history from the start of this session. Log
> all input and output so I can review later for a blog post on our new oracle skill

Added this session log as Deliverable 5; plan approved on resubmission. Full plan:
`~/.claude/plans/breezy-hugging-fern.md`.

### Approved deliverables
1. **Access-pattern catalog** (`data_requirements.md`) — 12 reads + 7 writes with
   frequency/cardinality/latency dials, 70/20/10-ranked.
2. **Candidate designs** — A: normalized relational (DBA baseline) + derived indexes;
   B: relational + duality views; C: document collections (patients embed
   addresses/payment-methods; records separate append-hot collection; bills embed
   items); D: single-collection patient-anchored with sparse type-filtered indexes.
3. **Dual-surface benchmark** — native SQL vs MongoDB API on the same seeded data.
4. **Java data layer** — shared interface, JDBC + Mongo-driver implementations,
   identical-results integration tests.
5. **This session log.**

---

## 7. Execution

### 7.1 Environment (oracle-ai-setup skill)
Deployed the `db+ords` compose profile as project `hospital-admissions`: Oracle AI
Database 26ai Free (port 1521) + ORDS with the MongoDB API (ports 8080/27017, TLS).
`enable-mongo-api.sh` → `ASSERT:mongo_api:PASS`. Created `hospital_dev` (USERS
tablespace, `SELECT_CATALOG_ROLE` for the benchmark counters), ORDS-enabled the schema.
Python venv + `oracledb` 4.0.2 + `pymongo` 4.17.0.

### 7.2 Workload authoring
`optimize/workload.json`: the full ERD as a ModelSpec (11 entities), 11 read + 4 write
patterns with rates, four candidate designs — relational (DBA baseline), duality,
document collections (patients/records/bills/room-stays), and a hand-declared
patient-anchored single-table projection (the auto-proposal would have anchored on
Record by rate; design D is the DynamoDB-style patient item-collection). Seeds:
`hospital-seed.sql` (relational, 5k patients / 75k records / 60k bill items) and
`hospital-docs-seed.sql` (documents populated FROM the relational overlay so every
design holds the same data).

### 7.3 Benchmark iterations (each failure is a modeling lesson)
1. **ORA-42647** — a duality view root needs `_id`; `Patient_Rooms`' composite natural
   key can't provide one → surrogate `stay_id` (now a schema-critique finding).
2. **ORA-00907 / ORA-00900** — seed SQL fixes (`WHERE` before `CONNECT BY`; the runner
   splits statements on every `;`, including inside comments — comments de-semicoloned).
3. **Answer-validation failures** — the equivalence gate caught: document timestamps
   serialized as ISO-`T` vs relational's space format; composite-PK columns not listed
   in `columns` (unreferenceable); `IS NULL` rendered as `NOT JSON_EXISTS` (key-absence)
   vs documents that serialized SQL NULL as JSON null → seeds switched to
   `ABSENT ON NULL`. Duality's null serialization can't be changed → its two IS-NULL
   cells stay excluded (reported, not hidden).
4. **Access-path warnings** — FK-join and covering indexes added (census needed the
   trailing-constant trick for `IS NULL`); single-table got non-sparse covering indexes
   (the generator appends the discriminator to non-sparse indexes — first attempt
   duplicated `type`, ORA-00957).
5. **Final run** (25 trials): all designs agree on every pattern except duality's two
   IS-NULL cells. Full matrix in `data_model.md`.

### 7.4 The verdict (measured)
Relational 38.51M weighted µs vs document 38.59M — **tied at 0.2%**, inside the noise
floor. Write-surge scenario → relational 2.8%; **analytics → relational separates at
61.5%**; flip analysis: a ≤0.3×-scaled read-dominant mix elects **document**. Chosen:
relational storage + duality projections for document consumers. Winning DDL:
`optimize/out/schema.relational.sql`.

### 7.5 Dual-surface benchmark (native SQL vs MongoDB API)
`optimize/surface_bench.py` — same collections, three surfaces, equivalence-gated.
Mongo API ≈ +0.6–0.9ms/op over native SQL. Star finding: the chart read via Mongo was
**38.6ms** until the index was created *through the Mongo API* — then **1.9ms** (20×).
The SQL-created functional index didn't match the Mongo-translated predicate: the
"index expression must match the query" rule holds across API surfaces.

### 7.6 Java data layer
`datalayer-java/`: `HospitalRepository` interface (one method per pattern) with JDBC and
MongoDB-driver implementations. Gotchas hit: Maven's default ancient compiler plugin
(pinned 3.13.0); the Mongo *Java* driver ignores `tlsAllowInvalidCertificates` in the
URI (needs an explicit SSLContext, unlike mongosh/pymongo); `$pop` cleanup wasn't
idempotent (switched to a shape-matched `$pull`). **`mvn verify`: 13/13 green** —
including the cross-surface identical-results equivalence tests.

### 7.7 Deliverables
- `data_requirements.md` — the access-pattern catalog (Deliverable 1)
- `optimize/workload.json` + seeds + `out/` — candidates & measurements (Deliverable 2)
- `optimize/surface_bench.py` + `out/surface_results.json` (Deliverable 3)
- `datalayer-java/` (Deliverable 4)
- `data_model.md` — verdict, matrix, severity-ranked DBA-schema critique, DDL, checklist
- this log (Deliverable 5)

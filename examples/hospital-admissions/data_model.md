# Hospital Admissions — Data Model (Oracle 26ai)

**Verdict: keep relational storage — the DBA's normalized schema, corrected and indexed
to the access patterns — as the system of record, and serve document consumers through
the MongoDB API where they need it.** On the estimated workload the relational and pure-
document designs are statistically tied (0.2% margin, inside the ~5% noise floor), but
relational wins every scenario that stresses the tie: the write-hot clinical feed, and
reporting, where it separates by **61.5%**. The flip analysis shows exactly when that
changes: a workload that is almost purely clinical point-reads elects document.

Everything below is **measured on a live Oracle 26ai Free instance** (5,000 patients,
75,000 clinical records, 60,000 bill items, 15,000 room stays seeded identically into
four candidate designs; 25 timed executions per cell; every design validated to return
the same answers before timing — equivalence before speed).

Method: `oracle-ai-dev:oracle-data-modeling` (Unified Model Theory) — access patterns in
`data_requirements.md`, workload spec in `optimize/workload.json`, runnable winning DDL
in `optimize/out/schema.relational.sql`.

## 1. The cost matrix (median µs, reads AND writes as first-class rows)

| pattern | kind | rate/day | document | duality | relational | single-table |
|---|---|---:|---:|---:|---:|---:|
| get_patient_chart | read | 15,000 | 354 | 375 | 507 | 490 |
| get_patient_snapshot | read | 10,000 | **317** | 365 | 533 | 539 |
| find_patient_by_number | read | 2,000 | 303 | 287 | 273 | 268 |
| get_room_history | read | 1,000 | **303** | 337 | 533 | 530 |
| ward_census | read | 500 | 5,356 | n/a | **1,057** | 8,056 |
| get_bill_with_items | read | 300 | **308** | 353 | 519 | 520 |
| get_payment_methods | read | 200 | 304 | 360 | 512 | 544 |
| admission_history | read | 100 | 301 | 304 | 264 | 269 |
| list_open_bills | read | 24 | 10,224 | n/a | **1,559** | 2,022 |
| charge_summary | read | 24 | 3,669 | 3,517 | 3,435 | 6,141 |
| records_by_staff | read | 20 | 1,605 | 3,744 | **1,003** | 1,255 |
| add_clinical_record | write | 12,000 | 1,259 | 1,303 | **1,179** | 1,256 |
| add_bill_item | write | 8,000 | 1,326 | 1,339 | **1,147** | 1,226 |
| admit_patient | write | 80 | 1,578 | 1,587 | **1,262** | 1,360 |
| settle_bill | write | 100 | 1,308 | 1,308 | **1,186** | 1,186 |

**Decision (rate-weighted):** relational 38.51M · document 38.59M (**0.2% — tied**) ·
single-table 43.45M. Driven by the two write-hot patterns and the chart read.

**Scenario sweep** (same cells, re-weighted): estimated mix → tied; device-integrated
charting (writes 3:1) → relational by 2.8%; **revenue-cycle analytics → relational by
61.5% (separates)**. **Flip point:** shrink everything except the chart read to ≤ 0.3×
and **document wins** — a read-dominant patient-portal workload is a document workload.

Reading the matrix:
- **Documents win every patient-centred read** (~300µs vs ~510µs): one indexed fetch of a
  pre-joined aggregate vs assembling joins. That 40% is real but small in absolute terms.
- **Relational wins every write** and never loses a read badly. Charge capture into an
  embedded-items bill document must rewrite the whole document (1,326µs vs 1,147µs) —
  write amplification, measured.
- **Documents lose absence-state sweeps by 5–10×** (ward_census, list_open_bills): "no
  discharge date yet" is key-absence in a document, and absence has no B-tree access path
  (`NOT JSON_EXISTS` full-scans). State-flag remodeling would be required.
- **Duality** matches document on point reads (365µs — storage stays relational, zero
  write amplification), making it the right *projection* for document consumers. Two
  caveats measured: the generator's key-absence predicate never matches a duality view's
  `null` serialization (its cells for the two IS-NULL patterns are excluded), and a
  JSON_VALUE filter on a non-key column did not push down to the base-table index
  (records_by_staff full-scanned at 3,744µs).
- **Single-table (DynamoDB-style)** is competitive nearly everywhere but wins nothing:
  the converged engine's relational and document shapes each beat it at its own game, and
  aggregations over one shared segment pay for the co-residents (charge_summary 6,141µs).

## 2. Severity-ranked critique of the DBA schema

**Blockers**
1. **No Encounter/Stay entity.** Rooms, bills, and records all hang directly off Patient;
   nothing groups "a stay in the Hospital", though the business rules are written around
   one. Billing across re-admissions is ambiguous today. Add `encounters(encounter_id,
   patient_id, admitted_at, discharged_at)` and re-parent room stays, bills, and admission
   records onto it as the service grows.
2. **`Patient_Rooms` has no single-column identity** (PK was patient_id + room_id +
   date_stay_from). A composite natural key cannot anchor a duality view (`ORA-42647:
   missing '_id'`), collides on same-day transfers, and makes the row unaddressable by
   APIs. Fixed in the elected DDL with surrogate `stay_id`.
3. **`Patient_Rooms.room_id` references nothing** — no Rooms table exists, so census
   integrity is unenforceable. Add a `rooms` reference table.

**Important**
4. **Charge capture is unlinked.** `Patient_Records.billable_item_code` and
   `Patient_Bill_Items` have no relationship — a clinical act cannot be traced to the
   bill line it generated. Add `patient_record_id` to bill items (or emit items from
   records).
5. **`Patient_Records` is a polymorphic grab-bag**: `admission_datetime` and
   `medical_condition` sit on every row regardless of component. Acceptable at this
   scale (measured: the chart read is fine); revisit with per-component detail tables or
   a JSON `details` column if components proliferate.
6. **Missing access-path indexes.** The FK joins and sweeps the patterns imply were
   unindexed; five indexes were added and verified in the plans (see §3). Notably the
   census covering index needs a **trailing constant** (`..., 0`) — with no NOT NULL
   column in the key, Oracle will not use an index for `IS NULL` otherwise.

**Minor**
7. Shared `Addresses` + two junction tables is over-normalized for owned, bounded
   addresses — measured cost is a modest join; keep for now, but a JSON `addresses`
   column on `patients` (or the duality projection) serves the same read in one fetch.
8. Three phone columns on Patients is the attribute pattern begging for one JSON column.
9. `total_amount_due`/`total_cost` should be `NUMBER(12,2)`; several `VARCHAR2(4000)`
   defaults deserve real sizes. Tighten in review of the generated DDL.

## 3. The elected physical model

Runnable DDL: **`optimize/out/schema.relational.sql`** (tables + FKs, deployed and
measured), plus the access-pattern indexes (deployed by the run; fold into the DDL for
production):

```sql
-- pattern-derived (generated by the optimizer)
--   patients(hospital_number), patient_records(patient_id),
--   patient_records(patient_id, component_code), patient_records(updated_by_staff_id),
--   patient_bills(patient_id), patient_bill_items covering aggregation index, ...
-- added during analysis (full-scan warnings -> fixed):
CREATE INDEX pr_patient_ix       ON patient_rooms (patient_id);
CREATE INDEX ppm_patient_ix      ON patient_payment_methods (patient_id);
CREATE INDEX prec_staff_cov_ix   ON patient_records (updated_by_staff_id, patient_record_id, component_code, updated_date);
CREATE INDEX pb_open_cov_ix      ON patient_bills (date_bill_paid, total_amount_due, patient_bill_id, patient_id);
CREATE INDEX prm_census_cov_ix   ON patient_rooms (date_stay_to, patient_id, room_id, date_stay_from, 0);
```

**Document consumers get projections, not copies:** expose `patients` (+ addresses,
payment methods, room stays) and `patient_bills` (+ items) as **duality views** for the
MongoDB API / JSON consumers — reads measured within ~50µs of the pure document design,
with zero write amplification because storage stays relational. Route the two
absence-state sweeps (census, open bills) through SQL, where they are indexed.

## 4. Native SQL vs MongoDB API (same data, same instance)

All reads returned identical results on every surface before timing (client-side
medians, 50 trials — includes driver + ORDS hop):

| pattern | SQL / relational | SQL / document | Mongo API / document |
|---|---:|---:|---:|
| get_patient_snapshot | 484µs | 482µs | 1,178µs |
| get_patient_chart | 500µs | 530µs | 1,253µs |
| find_patient_by_number | 253µs | 259µs | 1,101µs |
| get_room_history | 485µs | 499µs | 1,056µs |
| ward_census | 978µs | 4,124µs | 8,557µs |
| get_bill_with_items | 500µs | 537µs | 1,095µs |
| add_clinical_record (w) | 1,055µs | 1,162µs | 1,855µs |
| add_bill_item (w) | 1,045µs | 1,226µs | 3,371µs |

- The MongoDB API costs a consistent **~0.6–0.9ms per operation** over native SQL — the
  wire/ORDS translation premium. Fine for app traffic; use native SQL for hot loops.
- **Create indexes through the surface that queries them.** The chart read via Mongo
  first measured **38.6ms**; `createIndex()` through the Mongo API dropped it to
  **1.9ms** (20×). The SQL-created functional index expression did not match the
  Mongo-translated predicate — the same one-character-off rule, across API surfaces.
- Charge capture via Mongo `$push` (3,371µs) pays the document rewrite *plus* the wire
  premium — 3.2× native relational. Keep write-hot paths on SQL.

## 5. Java data layer

`datalayer-java/` — `mvn verify` **green (13/13)** against the live stack:
- `HospitalRepository` — one method per access pattern, domain records, binds only,
  credentials from `DB_USER`/`DB_PASSWORD`/`DB_DSN` (+ `MONGO_URI`/`MONGO_HOST`).
- `sql.SqlHospitalRepository` — Oracle JDBC over the elected relational schema.
- `mongo.MongoHospitalRepository` — MongoDB Java driver via the Oracle API for MongoDB
  (note: the Java driver needs an explicit trust-store/SSLContext for the dev
  container's self-signed TLS; `MONGO_TLS_INSECURE=false` for production).
- `RepositoryEquivalenceTest` — asserts both implementations return **identical** results
  for every read pattern, plus write round-trips per surface.

## 6. Reproduce

```bash
docker compose -p hospital-admissions -f docker/db-ords.compose.yml --env-file docker/.env up -d
export DB_USER=hospital_dev DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1
cd ~/.claude/plugins/cache/oracle-ai-dev-marketplace/oracle-ai-dev/0.1.0
python -m tooling.optimize <repo>/optimize/workload.json --out <repo>/optimize/out --fresh --trials 25
python <repo>/optimize/surface_bench.py --trials 50
cd <repo>/datalayer-java && mvn verify
```

## 7. Review checklist (gate)

- [x] Every access pattern enumerated with frequency, cardinality, latency, write intensity (`data_requirements.md`)
- [x] Patterns ranked 70/20/10; the chart read and clinical writes own the optimized shape
- [x] One physical strategy per entity, rule cited (relational storage + duality projections; UMT: "write-hot never pays a read-time join on write" — and here the writes dominate)
- [x] No write-hot pattern served by a duality view (W1/W2 land on base tables)
- [x] Embedded children bounded/owned in the document candidates; records never embedded (unbounded, append-hot)
- [x] Duality array children project their full PK (stay_id surrogate added for exactly this)
- [x] Indexes match the predicates; aggregation index carries the trailing constant; Mongo-surface indexes created through the Mongo API
- [x] No precomputed subset kept (none passed read-freq × read-cost > write-freq × maintenance-cost)
- [x] All features exercised are on 26ai Free (duality, JSON collections, Mongo API via ORDS)
- [x] Fits the Free envelope (seed ≈ 160k rows × 4 shapes ≪ 12 GB)
- [x] Runnable DDL provided; deployed into `hospital_dev` on USERS and smoke-tested on both surfaces

**Assumptions to validate with product management:** the workload rates (all estimated),
and the two modeling corrections (surrogate `stay_id`; billable-code linkage) which the
DBA should confirm.

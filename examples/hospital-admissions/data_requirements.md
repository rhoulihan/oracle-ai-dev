# Hospital Admissions — Data Requirements (Access Pattern Catalog)

Derived from the product-management business rules against the DBA's normalized ERD.
Workload profile is an **estimate** for a mid-size hospital (~300 beds, ~80
admissions/day, ~85% occupancy → ~250 inpatients at any time); every rate below is an
assumption to validate with product management before production sizing.

Entities (canonical form): `patient`, `address`, `payment_method`, `room_stay`,
`bill`, `bill_item`, `record` (patient record), `component` (record component),
`staff`.

Frequency ranking follows the 70/20/10 rule: the clinical hot path earns the
optimized shape.

## Reads — 70% tier (clinical hot path)

| # | Name | Returns (entity.property) | Predicates / ordering | Cardinality | Rate | Latency |
|---|------|---------------------------|-----------------------|-------------|------|---------|
| R1 | `get_patient_snapshot` | patient.* (demographics, next_of_kin, phones) + current address.* | patient.patient_id = :id; address current (date_address_to IS NULL) | 1 patient + 1 address | 10,000/day | <10 ms |
| R2 | `get_patient_chart` | record.component_code, record.updated_date, record.medical_condition, record.patient_record_component_details, record.updated_by_staff_id | record.patient_id = :id [AND record.component_code = :c]; ORDER BY updated_date DESC | 10–200 records/patient (unbounded over lifetime) | 15,000/day | <10 ms |
| R3 | `find_patient_by_number` | patient.* header | patient.hospital_number = :n OR patient.nhs_number = :n | 0–1 | 2,000/day | <10 ms |

## Reads — 20% tier (operational / billing)

| # | Name | Returns | Predicates | Cardinality | Rate |
|---|------|---------|------------|-------------|------|
| R4 | `get_room_history` | room_stay.room_id, date_stay_from, date_stay_to | room_stay.patient_id = :id | 1–6 stays/admission | 1,000/day |
| R5 | `ward_census` | patient.patient_id, patient_last_name, room_stay.room_id | room_stay.date_stay_to IS NULL [AND room_id = :r] — **cross-patient** | ~250 rows | 500/day |
| R6 | `get_bill_with_items` | bill.* + bill_item.item_seq_nr, quantity, total_cost | bill.patient_bill_id = :id (or patient_id = :p) | 1 bill + 5–200 items | 300/day |
| R7 | `get_payment_methods` | payment_method.payment_method_code, payment_method_details | payment_method.patient_id = :id | 1–4 | 200/day |
| R8 | `list_open_bills` | bill.patient_bill_id, patient_id, total_amount_due | bill.date_bill_paid IS NULL AND total_amount_due > 0 — cross-patient | 100s | 24/day (batch) |
| R9 | `charge_summary` | GROUP BY record.billable_item_code → COUNT(*), SUM(bill_item.total_cost) | date window; **aggregation** — needs covering group-key index in every shape | ~50 groups | 24/day (batch) |

## Reads — 10% tier

| # | Name | Returns | Predicates | Rate |
|---|------|---------|------------|------|
| R10 | `get_staff` | staff.* + address.* | staff.staff_id = :id | 50/day |
| R11 | `records_by_staff` | record.* (audit) | record.updated_by_staff_id = :id, date window | 20/day |
| R12 | `admission_history` | record.* where component = 'ADM' | record.patient_id = :id AND component_code = 'ADM' | 100/day |

## Writes (first-class patterns — they price denormalization)

| # | Name | Composition | Rate | Notes |
|---|------|-------------|------|-------|
| W1 | `add_clinical_record` | INSERT record (diagnosis/medication/notes) | **12,000/day** | write-hot; append-only; never embed records in the patient aggregate |
| W2 | `add_bill_item` | INSERT bill_item under an open bill | **8,000/day** | write-hot; in an embedded-items design this rewrites the whole bill document |
| W3 | `admit_patient` | txn: INSERT record('ADM') + room_stay + open bill | 80/day | multi-entity transaction |
| W4 | `transfer_room` | UPDATE room_stay.date_stay_to + INSERT room_stay | 40/day | |
| W5 | `upsert_patient_address` | INSERT/UPDATE patient + address (new address row, close previous) | 100/day | |
| W6 | `add_payment_method` | INSERT payment_method | 60/day | |
| W7 | `settle_bill` | UPDATE bill (total_amount_due, date_bill_paid) | 100/day | |

## Dial readings (per entity)

- **patient + address + payment_method**: bounded, owned, co-accessed (R1/R7),
  low write rate → embed candidates.
- **record**: unbounded, append-hot (W1 dominates all writes), read newest-first by
  patient → own container, keyed/indexed (patient_id, updated_date DESC).
- **bill + bill_item**: items bounded per bill and co-accessed at read (R6), but
  charge capture (W2) is write-hot → embed-vs-reference is exactly the tradeoff the
  cost matrix must price.
- **room_stay**: tiny bounded history per admission, but R5 is a **cross-patient**
  query — an embedded design needs a multivalue/functional index to avoid scanning
  every patient document.
- **staff**: low volume, low churn; relational is uncontroversial. The shared
  `Addresses` table splits on governance: patient addresses are patient-owned.

## Candidate designs to measure

A. **Normalized relational** (DBA baseline) + access-pattern-derived indexes — control.
B. **Relational + duality views** — `patient_dv`, `bill_dv` for document consumers;
   base tables absorb W1/W2.
C. **Document collections** — `patients` (embeds addresses, payment methods,
   next-of-kin, room history), `patient_records` (separate, append-hot), `bills`
   (embeds items).
D. **Single-collection, patient-anchored** — typed items (`patient`, `record`,
   `room_stay`, `bill`, `bill_item`) under a patient_id anchor; sparse type-filtered
   indexes; one item-collection scan serves R1+R2+R4.

Winner elected by the measured cost matrix (reads AND writes, rate-weighted), with
break-points and latency violations reported — not by rule.

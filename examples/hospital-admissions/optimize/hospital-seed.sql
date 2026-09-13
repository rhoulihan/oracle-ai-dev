-- Hospital admissions relational seed (DBA baseline overlay).
-- Sized per the sizing guidance: ~5k patients, 75k clinical records, 60k bill items —
-- big enough for real index depth and multi-block scans, well inside Free's 12 GB.
SET FEEDBACK OFF
DEFINE patients = 5000
DEFINE staff_n = 300
DEFINE second_addr = 500
DEFINE stays_per_patient = 3
DEFINE items_per_bill = 10
DEFINE records_per_patient = 15

DELETE FROM patient_records;
DELETE FROM patient_bill_items;
DELETE FROM patient_bills;
DELETE FROM patient_rooms;
DELETE FROM patient_payment_methods;
DELETE FROM patient_addresses;
DELETE FROM staff_addresses;
DELETE FROM addresses;
DELETE FROM record_components;
DELETE FROM staff;
DELETE FROM patients;

INSERT INTO record_components (component_code, component_description)
SELECT c, d FROM (
  SELECT 'ADM' c, 'Admission' d FROM dual UNION ALL
  SELECT 'DIAG', 'Diagnosis' FROM dual UNION ALL
  SELECT 'MED', 'Medication' FROM dual UNION ALL
  SELECT 'LAB', 'Lab Result' FROM dual UNION ALL
  SELECT 'NOTE', 'Progress Note' FROM dual UNION ALL
  SELECT 'VITALS', 'Vital Signs' FROM dual UNION ALL
  SELECT 'PROC', 'Procedure' FROM dual UNION ALL
  SELECT 'DISCH', 'Discharge' FROM dual);

INSERT INTO patients (patient_id, outpatient_yn, hospital_number, nhs_number, gender,
       date_of_birth, patient_first_name, patient_middle_name, patient_last_name,
       height, weight, next_of_kin, home_phone, work_phone, cell_mobile_phone,
       other_patient_details)
SELECT lvl, CASE MOD(lvl, 4) WHEN 0 THEN 'Y' ELSE 'N' END,
       'H' || LPAD(lvl, 7, '0'), 'NHS' || LPAD(lvl, 8, '0'),
       CASE MOD(lvl, 2) WHEN 0 THEN 'F' ELSE 'M' END,
       TIMESTAMP '1950-01-01 00:00:00' + NUMTODSINTERVAL(MOD(lvl * 37, 20000), 'DAY'),
       'First' || lvl, 'Mid' || lvl, 'Last' || lvl,
       150 + MOD(lvl, 50), 50 + MOD(lvl, 70),
       'NOK Last' || lvl, '555-1' || LPAD(lvl, 5, '0'), '555-2' || LPAD(lvl, 5, '0'),
       '555-3' || LPAD(lvl, 5, '0'), NULL
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &patients);

INSERT INTO staff (staff_id, staff_category_code, gender, staff_job_title,
       staff_first_name, staff_last_name, staff_qualifications, staff_birth_date)
SELECT lvl, CASE MOD(lvl, 3) WHEN 0 THEN 'MD' WHEN 1 THEN 'RN' ELSE 'ADMIN' END,
       CASE MOD(lvl, 2) WHEN 0 THEN 'F' ELSE 'M' END,
       CASE MOD(lvl, 3) WHEN 0 THEN 'Physician' WHEN 1 THEN 'Nurse' ELSE 'Clerk' END,
       'StaffFirst' || lvl, 'StaffLast' || lvl, 'Qual' || MOD(lvl, 5),
       TIMESTAMP '1960-01-01 00:00:00' + NUMTODSINTERVAL(MOD(lvl * 53, 12000), 'DAY')
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &staff_n);

-- patient addresses 1..5000 (address p belongs to patient p),
-- 5001..5500 second addresses for patients 1..500, 6001..6300 staff addresses
INSERT INTO addresses (address_id, line_1_number_building, line_2_number_street,
       line_3_area_locality, city, zip_postcode, state_province_county, country)
SELECT lvl, lvl || ' Main St', 'Unit ' || MOD(lvl, 20), 'Locality ' || MOD(lvl, 40),
       'City ' || MOD(lvl, 50), LPAD(MOD(lvl * 7, 100000), 5, '0'),
       'State ' || MOD(lvl, 20), 'Country ' || MOD(lvl, 5)
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &patients);

INSERT INTO addresses (address_id, line_1_number_building, line_2_number_street,
       line_3_area_locality, city, zip_postcode, state_province_county, country)
SELECT 5000 + lvl, lvl || ' Second Ave', 'Apt ' || MOD(lvl, 9), 'Locality ' || MOD(lvl, 40),
       'City ' || MOD(lvl, 50), LPAD(MOD(lvl * 11, 100000), 5, '0'),
       'State ' || MOD(lvl, 20), 'Country ' || MOD(lvl, 5)
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &second_addr);

INSERT INTO addresses (address_id, line_1_number_building, line_2_number_street,
       line_3_area_locality, city, zip_postcode, state_province_county, country)
SELECT 6000 + lvl, lvl || ' Staff Rd', NULL, NULL,
       'City ' || MOD(lvl, 50), LPAD(MOD(lvl * 13, 100000), 5, '0'),
       'State ' || MOD(lvl, 20), 'Country ' || MOD(lvl, 5)
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &staff_n);

INSERT INTO patient_addresses (patient_id, address_id, date_address_from, date_address_to)
SELECT lvl, lvl, TIMESTAMP '2020-01-01 00:00:00' + NUMTODSINTERVAL(MOD(lvl, 1000), 'DAY'), NULL
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &patients);

INSERT INTO patient_addresses (patient_id, address_id, date_address_from, date_address_to)
SELECT lvl, 5000 + lvl, TIMESTAMP '2023-01-01 00:00:00' + NUMTODSINTERVAL(MOD(lvl, 900), 'DAY'), NULL
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &second_addr);

INSERT INTO staff_addresses (staff_id, address_id, date_address_from, date_address_to)
SELECT lvl, 6000 + lvl, TIMESTAMP '2021-01-01 00:00:00', NULL
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &staff_n);

-- payment methods: one per patient, a second for every third patient
INSERT INTO patient_payment_methods (patient_method_id, patient_id, payment_method_code,
       payment_method_details)
SELECT lvl, lvl,
       CASE MOD(lvl, 3) WHEN 0 THEN 'CARD' WHEN 1 THEN 'INSURANCE' ELSE 'DIRECT' END,
       'details ' || lvl
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &patients);

INSERT INTO patient_payment_methods (patient_method_id, patient_id, payment_method_code,
       payment_method_details)
SELECT 5000 + lvl, lvl, 'CARD', 'card ending ' || LPAD(MOD(lvl, 10000), 4, '0')
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &patients)
WHERE MOD(lvl, 3) = 0;

-- room stays: 3 per patient — the 3rd stay of every 20th patient is CURRENT (date_stay_to NULL)
INSERT INTO patient_rooms (stay_id, patient_id, room_id, date_stay_from, date_stay_to)
SELECT (p.lvl - 1) * &stays_per_patient + j.lvl,
       p.lvl, 'RM' || LPAD(MOD(p.lvl * 3 + j.lvl, 300) + 1, 3, '0'),
       TIMESTAMP '2026-01-01 08:00:00' + NUMTODSINTERVAL(MOD(p.lvl, 150), 'DAY')
         + NUMTODSINTERVAL(j.lvl, 'DAY'),
       CASE WHEN j.lvl = &stays_per_patient AND MOD(p.lvl, 20) = 0 THEN NULL
            ELSE TIMESTAMP '2026-01-01 08:00:00' + NUMTODSINTERVAL(MOD(p.lvl, 150), 'DAY')
                 + NUMTODSINTERVAL(j.lvl + 1, 'DAY') END
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &patients) p,
     (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &stays_per_patient) j;

-- bills: bill N (1..5000) belongs to patient N — 5001..6000 are second bills for patients
-- 1..1000. Every 12th bill is OPEN: unpaid with a positive balance.
INSERT INTO patient_bills (patient_bill_id, patient_id, date_bill_paid, total_amount_due,
       other_bill_details)
SELECT lvl, CASE WHEN lvl <= &patients THEN lvl ELSE lvl - &patients END,
       CASE WHEN MOD(lvl, 12) = 0 THEN NULL
            ELSE TIMESTAMP '2026-03-01 00:00:00' + NUMTODSINTERVAL(MOD(lvl, 120), 'DAY') END,
       CASE WHEN MOD(lvl, 12) = 0 THEN 100 + MOD(lvl, 5000) ELSE 0 END,
       'bill details ' || lvl
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= 6000);

INSERT INTO patient_bill_items (patient_bill_id, item_seq_nr, quantity, total_cost)
SELECT b.lvl, j.lvl, MOD(b.lvl + j.lvl, 5) + 1, 25 + MOD(b.lvl * j.lvl, 975)
FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= 6000) b,
     (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &items_per_bill) j;

-- clinical records: 15 per patient with a realistic component mix — billables carry a code
INSERT INTO patient_records (patient_record_id, patient_id, billable_item_code,
       component_code, updated_by_staff_id, updated_date, admission_datetime,
       medical_condition, patient_record_component_details)
SELECT rid,
       pid,
       CASE WHEN comp IN ('MED', 'LAB') THEN 'BI' || LPAD(MOD(rid, 50) + 1, 2, '0') END,
       comp,
       MOD(rid, &staff_n) + 1,
       TIMESTAMP '2026-01-01 08:00:00' + NUMTODSINTERVAL(rid, 'MINUTE'),
       CASE WHEN comp = 'ADM'
            THEN TIMESTAMP '2026-01-01 08:00:00' + NUMTODSINTERVAL(rid, 'MINUTE') END,
       'condition ' || MOD(rid, 30),
       'component details for record ' || rid
FROM (
  SELECT (p.lvl - 1) * &records_per_patient + j.lvl AS rid, p.lvl AS pid,
         CASE WHEN j.lvl = 1 THEN 'ADM'
              WHEN j.lvl = 2 THEN 'DIAG'
              WHEN j.lvl <= 8 THEN 'MED'
              WHEN j.lvl <= 11 THEN 'LAB'
              WHEN j.lvl <= 14 THEN 'NOTE'
              ELSE 'VITALS' END AS comp
  FROM (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &patients) p,
       (SELECT LEVEL lvl FROM dual CONNECT BY LEVEL <= &records_per_patient) j
);

-- Access-path indexes the pattern-derived set misses: FK joins reached through a
-- parent-rooted read (never named in a filter), and covering indexes so the
-- IS-NULL sweeps and the audit read never touch the table.
CREATE INDEX pr_patient_ix ON patient_rooms (patient_id);
CREATE INDEX ppm_patient_ix ON patient_payment_methods (patient_id);
CREATE INDEX prec_staff_cov_ix ON patient_records (updated_by_staff_id, patient_record_id, component_code, updated_date);
CREATE INDEX pb_open_cov_ix ON patient_bills (date_bill_paid, total_amount_due, patient_bill_id, patient_id);
CREATE INDEX prm_census_cov_ix ON patient_rooms (date_stay_to, patient_id, room_id, date_stay_from, 0);

COMMIT;

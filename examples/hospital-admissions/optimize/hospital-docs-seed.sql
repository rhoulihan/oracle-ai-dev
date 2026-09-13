-- Populate the candidate DOCUMENT shape from the relational overlay, so every design holds
-- the same data and the measurement is apples-to-apples.
--
-- Document design (per data_requirements.md, candidate C):
--   patient_docs    — patient scalars + EMBEDDED addresses, payment methods, room stays
--                     (bounded, owned, co-accessed)
--   record_docs     — clinical records as their OWN collection (unbounded, append-hot —
--                     embedding them in the patient would rewrite a growing doc 12k/day)
--   bill_docs       — bill + EMBEDDED items (co-accessed at invoice — charge capture must
--                     rewrite the doc — that write amplification is exactly what the
--                     cost matrix prices)
--   room_stay_docs  — stays ALSO as standalone docs for the cross-patient ward census —
--                     the duplication (embedded + standalone) is honest document modeling,
--                     and admits/transfers pay to maintain both copies.
DELETE FROM patient_docs;
INSERT INTO patient_docs (data)
SELECT JSON_OBJECT(
         '_id' VALUE p.patient_id,
         'outpatient_yn' VALUE p.outpatient_yn,
         'hospital_number' VALUE p.hospital_number,
         'nhs_number' VALUE p.nhs_number,
         'gender' VALUE p.gender,
         'date_of_birth' VALUE TO_CHAR(p.date_of_birth, 'YYYY-MM-DD HH24:MI:SS'),
         'patient_first_name' VALUE p.patient_first_name,
         'patient_middle_name' VALUE p.patient_middle_name,
         'patient_last_name' VALUE p.patient_last_name,
         'height' VALUE p.height,
         'weight' VALUE p.weight,
         'next_of_kin' VALUE p.next_of_kin,
         'home_phone' VALUE p.home_phone,
         'work_phone' VALUE p.work_phone,
         'cell_mobile_phone' VALUE p.cell_mobile_phone,
         'addresses' VALUE (
           SELECT JSON_ARRAYAGG(JSON_OBJECT(
                    'address_id' VALUE a.address_id,
                    'line_1_number_building' VALUE a.line_1_number_building,
                    'line_2_number_street' VALUE a.line_2_number_street,
                    'city' VALUE a.city,
                    'zip_postcode' VALUE a.zip_postcode,
                    'state_province_county' VALUE a.state_province_county,
                    'country' VALUE a.country,
                    'date_address_from' VALUE TO_CHAR(pa.date_address_from, 'YYYY-MM-DD HH24:MI:SS')
                  RETURNING JSON) ABSENT ON NULL RETURNING JSON)
           FROM patient_addresses pa JOIN addresses a ON a.address_id = pa.address_id
           WHERE pa.patient_id = p.patient_id),
         'paymentmethods' VALUE (
           SELECT JSON_ARRAYAGG(JSON_OBJECT(
                    'patient_method_id' VALUE m.patient_method_id,
                    'payment_method_code' VALUE m.payment_method_code,
                    'payment_method_details' VALUE m.payment_method_details
                  RETURNING JSON) ABSENT ON NULL RETURNING JSON)
           FROM patient_payment_methods m WHERE m.patient_id = p.patient_id),
         'roomstays' VALUE (
           SELECT JSON_ARRAYAGG(JSON_OBJECT(
                    'room_id' VALUE r.room_id,
                    'date_stay_from' VALUE TO_CHAR(r.date_stay_from, 'YYYY-MM-DD HH24:MI:SS'),
                    'date_stay_to' VALUE TO_CHAR(r.date_stay_to, 'YYYY-MM-DD HH24:MI:SS')
                  RETURNING JSON) ABSENT ON NULL RETURNING JSON)
           FROM patient_rooms r WHERE r.patient_id = p.patient_id)
       ABSENT ON NULL RETURNING JSON)
FROM patients p;

DELETE FROM record_docs;
INSERT INTO record_docs (data)
SELECT JSON_OBJECT(
         '_id' VALUE r.patient_record_id,
         'patient_id' VALUE r.patient_id,
         'billable_item_code' VALUE r.billable_item_code,
         'component_code' VALUE r.component_code,
         'updated_by_staff_id' VALUE r.updated_by_staff_id,
         'updated_date' VALUE TO_CHAR(r.updated_date, 'YYYY-MM-DD HH24:MI:SS'),
         'admission_datetime' VALUE TO_CHAR(r.admission_datetime, 'YYYY-MM-DD HH24:MI:SS'),
         'medical_condition' VALUE r.medical_condition,
         'patient_record_component_details' VALUE r.patient_record_component_details
       ABSENT ON NULL RETURNING JSON)
FROM patient_records r;

DELETE FROM bill_docs;
INSERT INTO bill_docs (data)
SELECT JSON_OBJECT(
         '_id' VALUE b.patient_bill_id,
         'patient_id' VALUE b.patient_id,
         'date_bill_paid' VALUE TO_CHAR(b.date_bill_paid, 'YYYY-MM-DD HH24:MI:SS'),
         'total_amount_due' VALUE b.total_amount_due,
         'other_bill_details' VALUE b.other_bill_details,
         'billitems' VALUE (
           SELECT JSON_ARRAYAGG(JSON_OBJECT(
                    'patient_bill_id' VALUE i.patient_bill_id,
                    'item_seq_nr' VALUE i.item_seq_nr,
                    'quantity' VALUE i.quantity,
                    'total_cost' VALUE i.total_cost
                  RETURNING JSON) ABSENT ON NULL RETURNING JSON)
           FROM patient_bill_items i WHERE i.patient_bill_id = b.patient_bill_id)
       ABSENT ON NULL RETURNING JSON)
FROM patient_bills b;

DELETE FROM room_stay_docs;
INSERT INTO room_stay_docs (data)
SELECT JSON_OBJECT(
         '_id' VALUE r.stay_id,
         'patient_id' VALUE r.patient_id,
         'room_id' VALUE r.room_id,
         'date_stay_from' VALUE TO_CHAR(r.date_stay_from, 'YYYY-MM-DD HH24:MI:SS'),
         'date_stay_to' VALUE TO_CHAR(r.date_stay_to, 'YYYY-MM-DD HH24:MI:SS')
       ABSENT ON NULL RETURNING JSON)
FROM patient_rooms r;

COMMIT;

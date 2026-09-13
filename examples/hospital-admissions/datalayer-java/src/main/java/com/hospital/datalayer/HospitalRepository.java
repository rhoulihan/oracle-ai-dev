package com.hospital.datalayer;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Access-pattern-driven repository for the hospital admissions service.
 *
 * One method per access pattern from data_requirements.md (R = read, W = write).
 * Two implementations exist against the same Oracle 26ai database:
 * {@code sql.SqlHospitalRepository} (native SQL over JDBC, relational schema) and
 * {@code mongo.MongoHospitalRepository} (MongoDB Java driver via the Oracle API for
 * MongoDB, document collections). Both must return identical results for every read.
 */
public interface HospitalRepository extends AutoCloseable {

    // --- domain records -----------------------------------------------------

    record Address(String line1, String city, String zipPostcode) {}

    record PatientSnapshot(long patientId, String firstName, String lastName,
                           LocalDateTime dateOfBirth, String gender, String nextOfKin,
                           String cellPhone, List<Address> addresses) {}

    record PatientRef(long patientId, String firstName, String lastName,
                      String hospitalNumber) {}

    record ChartEntry(String componentCode, LocalDateTime updatedDate,
                      String medicalCondition, String details) {}

    record RoomStay(String roomId, LocalDateTime stayFrom, LocalDateTime stayTo) {}

    record CensusEntry(long patientId, String roomId, LocalDateTime stayFrom) {}

    record BillItem(long itemSeqNr, long quantity, long totalCost) {}

    record Bill(long billId, long totalAmountDue, LocalDateTime dateBillPaid,
                List<BillItem> items) {}

    record OpenBill(long billId, long patientId, long totalAmountDue) {}

    record PaymentMethod(String code, String details) {}

    record ChargeSummary(String billableItemCode, long count) {}

    record StaffRecordRef(long recordId, String componentCode, LocalDateTime updatedDate) {}

    record AdmissionEntry(LocalDateTime admissionDatetime, String medicalCondition,
                          LocalDateTime updatedDate) {}

    record NewClinicalRecord(long recordId, long patientId, String billableItemCode,
                             String componentCode, long staffId, String medicalCondition,
                             String details) {}

    // --- reads ---------------------------------------------------------------

    /** R1 — patient demographics + addresses, by patient id. */
    PatientSnapshot getPatientSnapshot(long patientId);

    /** R2 — the patient chart: clinical records newest-first. */
    List<ChartEntry> getPatientChart(long patientId);

    /** R3 — look a patient up by hospital number. */
    PatientRef findPatientByNumber(String hospitalNumber);

    /** R4 — room stay history for a patient. */
    List<RoomStay> getRoomHistory(long patientId);

    /** R5 — ward census: every currently-open room stay (cross-patient). */
    List<CensusEntry> wardCensus();

    /** R6 — a bill with all of its items. */
    Bill getBillWithItems(long billId);

    /** R7 — a patient's payment methods. */
    List<PaymentMethod> getPaymentMethods(long patientId);

    /** R8 — all open bills (unpaid, positive balance). */
    List<OpenBill> listOpenBills();

    /** R9 — record counts grouped by billable item code (null group included). */
    List<ChargeSummary> chargeSummary();

    /** R11 — records authored by a staff member (audit). */
    List<StaffRecordRef> recordsByStaff(long staffId);

    /** R12 — a patient's admission-component records. */
    List<AdmissionEntry> admissionHistory(long patientId);

    // --- writes ----------------------------------------------------------------

    /** W1 — append a clinical record (the write-hot path). */
    void addClinicalRecord(NewClinicalRecord rec);

    /** W2 — charge capture: add an item to an existing bill. */
    void addBillItem(long billId, long patientId, BillItem item);

    /** W3 — admit: admission record + open room stay + open bill, one transaction. */
    void admitPatient(long admissionId, long patientId, String roomId, long staffId);

    /** W7 — settle a bill: zero the balance and stamp the paid date. */
    void settleBill(long billId);

    @Override void close();
}

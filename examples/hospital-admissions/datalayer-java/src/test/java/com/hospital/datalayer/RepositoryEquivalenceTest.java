package com.hospital.datalayer;

import com.hospital.datalayer.mongo.MongoHospitalRepository;
import com.hospital.datalayer.sql.SqlHospitalRepository;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Both implementations must return IDENTICAL results for every read pattern —
 * the same equivalence gate the shape benchmark applies, at the data-layer level.
 *
 * Requires a live stack (skipped otherwise): DB_USER / DB_PASSWORD / DB_DSN set and
 * the benchmark schema seeded (patient 42, bill 500, staff 7).
 */
class RepositoryEquivalenceTest {

    static SqlHospitalRepository sql;
    static MongoHospitalRepository mongo;

    @BeforeAll
    static void connect() {
        assumeTrue(System.getenv("DB_USER") != null && System.getenv("DB_DSN") != null,
                "DB_USER/DB_DSN not set — skipping live integration tests");
        sql = new SqlHospitalRepository();
        mongo = new MongoHospitalRepository();
    }

    @AfterAll
    static void close() {
        if (sql != null) sql.close();
        if (mongo != null) mongo.close();
    }

    @Test
    void patientSnapshotMatches() {
        var a = sql.getPatientSnapshot(42);
        var b = mongo.getPatientSnapshot(42);
        assertEquals(a, b);
        assertEquals(2, a.addresses().size(), "patient 42 has two addresses in the seed");
    }

    @Test
    void patientChartMatches() {
        List<HospitalRepository.ChartEntry> a = sql.getPatientChart(42);
        List<HospitalRepository.ChartEntry> b = mongo.getPatientChart(42);
        assertEquals(a, b);
        assertEquals(15, a.size(), "15 records per patient in the seed");
    }

    @Test
    void findByNumberMatches() {
        assertEquals(sql.findPatientByNumber("H0000042"), mongo.findPatientByNumber("H0000042"));
    }

    @Test
    void roomHistoryMatches() {
        assertEquals(sql.getRoomHistory(42), mongo.getRoomHistory(42));
    }

    @Test
    void wardCensusMatches() {
        var a = sql.wardCensus();
        var b = mongo.wardCensus();
        assertEquals(a, b);
        assertTrue(a.size() >= 250, "the seed leaves ~250 stays open");
    }

    @Test
    void billWithItemsMatches() {
        var a = sql.getBillWithItems(500);
        var b = mongo.getBillWithItems(500);
        assertEquals(a, b);
        assertEquals(10, a.items().size());
    }

    @Test
    void paymentMethodsMatch() {
        assertEquals(sql.getPaymentMethods(42), mongo.getPaymentMethods(42));
    }

    @Test
    void openBillsMatch() {
        assertEquals(sql.listOpenBills(), mongo.listOpenBills());
    }

    @Test
    void chargeSummaryMatches() {
        assertEquals(sql.chargeSummary(), mongo.chargeSummary());
    }

    @Test
    void recordsByStaffMatch() {
        assertEquals(sql.recordsByStaff(7), mongo.recordsByStaff(7));
    }

    @Test
    void admissionHistoryMatches() {
        assertEquals(sql.admissionHistory(42), mongo.admissionHistory(42));
    }

    // --- writes: each surface applies its own write, is read back, then cleaned up ---

    @Test
    void sqlWritesRoundTrip() {
        long id = 9_500_001L;
        long recId = id + 10;
        try {
            sql.addClinicalRecord(new HospitalRepository.NewClinicalRecord(
                    recId, 44, null, "NOTE", 7, "stable", "progress note"));
            assertTrue(sql.recordsByStaff(7).stream().anyMatch(r -> r.recordId() == recId));
            sql.admitPatient(id, 44, "RM102", 7);
            assertTrue(sql.getRoomHistory(44).stream().anyMatch(s -> s.roomId().equals("RM102")));
            sql.addBillItem(500, 500, new HospitalRepository.BillItem(9500, 1, 125));
            assertTrue(sql.getBillWithItems(500).items().stream()
                    .anyMatch(i -> i.itemSeqNr() == 9500));
            sql.settleBill(id);
            assertEquals(0, sql.getBillWithItems(id).totalAmountDue());
            assertNotNull(sql.getBillWithItems(id).dateBillPaid());
        } finally {
            sql.deleteAdmissionArtifacts(id);
            sql.deleteAdmissionArtifacts(id + 10);
        }
    }

    @Test
    void mongoWritesRoundTrip() {
        long id = 9_500_002L;
        long recId = id + 10;
        try {
            mongo.addClinicalRecord(new HospitalRepository.NewClinicalRecord(
                    recId, 45, null, "NOTE", 7, "stable", "progress note"));
            assertTrue(mongo.recordsByStaff(7).stream().anyMatch(r -> r.recordId() == recId));
            mongo.admitPatient(id, 45, "RM103", 7);
            assertTrue(mongo.getRoomHistory(45).stream().anyMatch(s -> s.roomId().equals("RM103")));
            mongo.addBillItem(500, 500, new HospitalRepository.BillItem(9501, 1, 125));
            assertTrue(mongo.getBillWithItems(500).items().stream()
                    .anyMatch(i -> i.itemSeqNr() == 9501));
            mongo.settleBill(id);
            assertEquals(0, mongo.getBillWithItems(id).totalAmountDue());
            assertNotNull(mongo.getBillWithItems(id).dateBillPaid());
        } finally {
            mongo.deleteAdmissionArtifacts(id, 45, "RM103");
            mongo.deleteAdmissionArtifacts(id + 10, 45, "RM103");
        }
    }
}

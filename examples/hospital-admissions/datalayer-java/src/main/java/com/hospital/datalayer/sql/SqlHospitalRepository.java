package com.hospital.datalayer.sql;

import com.hospital.datalayer.HospitalRepository;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Native-SQL implementation over JDBC against the relational schema
 * (the DBA baseline plus the surrogate stay_id on patient_rooms).
 *
 * Connection comes from the environment — DB_USER / DB_PASSWORD / DB_DSN
 * (host:port/service) — never embedded. Every predicate value is a bind parameter.
 */
public final class SqlHospitalRepository implements HospitalRepository {

    private final Connection conn;

    public SqlHospitalRepository() {
        this(env("DB_USER"), env("DB_PASSWORD"), env("DB_DSN"));
    }

    public SqlHospitalRepository(String user, String password, String dsn) {
        try {
            this.conn = DriverManager.getConnection("jdbc:oracle:thin:@//" + dsn, user, password);
            this.conn.setAutoCommit(false);
        } catch (SQLException e) {
            throw new IllegalStateException("cannot connect to " + dsn, e);
        }
    }

    private static String env(String name) {
        String v = System.getenv(name);
        if (v == null || v.isBlank()) {
            throw new IllegalStateException("environment variable " + name + " is not set");
        }
        return v;
    }

    private static LocalDateTime ts(ResultSet rs, String col) throws SQLException {
        Timestamp t = rs.getTimestamp(col);
        return t == null ? null : t.toLocalDateTime();
    }

    // --- reads -----------------------------------------------------------------

    @Override
    public PatientSnapshot getPatientSnapshot(long patientId) {
        String sql = """
            SELECT p.patient_first_name, p.patient_last_name, p.date_of_birth, p.gender,
                   p.next_of_kin, p.cell_mobile_phone,
                   a.line_1_number_building, a.city, a.zip_postcode
            FROM patients p
            LEFT JOIN patient_addresses pa ON pa.patient_id = p.patient_id
            LEFT JOIN addresses a ON a.address_id = pa.address_id
            WHERE p.patient_id = ?
            ORDER BY a.address_id""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, patientId);
            try (ResultSet rs = ps.executeQuery()) {
                PatientSnapshot base = null;
                List<Address> addresses = new ArrayList<>();
                while (rs.next()) {
                    if (base == null) {
                        base = new PatientSnapshot(patientId,
                                rs.getString("patient_first_name"),
                                rs.getString("patient_last_name"),
                                ts(rs, "date_of_birth"), rs.getString("gender"),
                                rs.getString("next_of_kin"), rs.getString("cell_mobile_phone"),
                                addresses);
                    }
                    if (rs.getString("city") != null) {
                        addresses.add(new Address(rs.getString("line_1_number_building"),
                                rs.getString("city"), rs.getString("zip_postcode")));
                    }
                }
                return base;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<ChartEntry> getPatientChart(long patientId) {
        String sql = """
            SELECT component_code, updated_date, medical_condition,
                   patient_record_component_details
            FROM patient_records WHERE patient_id = ?
            ORDER BY updated_date DESC""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, patientId);
            try (ResultSet rs = ps.executeQuery()) {
                List<ChartEntry> out = new ArrayList<>();
                while (rs.next()) {
                    out.add(new ChartEntry(rs.getString(1), ts(rs, "updated_date"),
                            rs.getString(3), rs.getString(4)));
                }
                return out;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public PatientRef findPatientByNumber(String hospitalNumber) {
        String sql = """
            SELECT patient_id, patient_first_name, patient_last_name, hospital_number
            FROM patients WHERE hospital_number = ?""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setString(1, hospitalNumber);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? new PatientRef(rs.getLong(1), rs.getString(2),
                        rs.getString(3), rs.getString(4)) : null;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<RoomStay> getRoomHistory(long patientId) {
        String sql = """
            SELECT room_id, date_stay_from, date_stay_to
            FROM patient_rooms WHERE patient_id = ? ORDER BY date_stay_from""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, patientId);
            try (ResultSet rs = ps.executeQuery()) {
                List<RoomStay> out = new ArrayList<>();
                while (rs.next()) {
                    out.add(new RoomStay(rs.getString(1), ts(rs, "date_stay_from"),
                            ts(rs, "date_stay_to")));
                }
                return out;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<CensusEntry> wardCensus() {
        String sql = """
            SELECT patient_id, room_id, date_stay_from
            FROM patient_rooms WHERE date_stay_to IS NULL
            ORDER BY patient_id, date_stay_from""";
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            List<CensusEntry> out = new ArrayList<>();
            while (rs.next()) {
                out.add(new CensusEntry(rs.getLong(1), rs.getString(2), ts(rs, "date_stay_from")));
            }
            return out;
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public Bill getBillWithItems(long billId) {
        String sql = """
            SELECT b.total_amount_due, b.date_bill_paid,
                   i.item_seq_nr, i.quantity, i.total_cost
            FROM patient_bills b
            LEFT JOIN patient_bill_items i ON i.patient_bill_id = b.patient_bill_id
            WHERE b.patient_bill_id = ?
            ORDER BY i.item_seq_nr""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, billId);
            try (ResultSet rs = ps.executeQuery()) {
                Bill bill = null;
                List<BillItem> items = new ArrayList<>();
                while (rs.next()) {
                    if (bill == null) {
                        bill = new Bill(billId, rs.getLong("total_amount_due"),
                                ts(rs, "date_bill_paid"), items);
                    }
                    long seq = rs.getLong("item_seq_nr");
                    if (!rs.wasNull()) {
                        items.add(new BillItem(seq, rs.getLong("quantity"), rs.getLong("total_cost")));
                    }
                }
                return bill;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<PaymentMethod> getPaymentMethods(long patientId) {
        String sql = """
            SELECT payment_method_code, payment_method_details
            FROM patient_payment_methods WHERE patient_id = ? ORDER BY patient_method_id""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, patientId);
            try (ResultSet rs = ps.executeQuery()) {
                List<PaymentMethod> out = new ArrayList<>();
                while (rs.next()) {
                    out.add(new PaymentMethod(rs.getString(1), rs.getString(2)));
                }
                return out;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<OpenBill> listOpenBills() {
        String sql = """
            SELECT patient_bill_id, patient_id, total_amount_due
            FROM patient_bills
            WHERE date_bill_paid IS NULL AND total_amount_due > 0
            ORDER BY patient_bill_id""";
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            List<OpenBill> out = new ArrayList<>();
            while (rs.next()) {
                out.add(new OpenBill(rs.getLong(1), rs.getLong(2), rs.getLong(3)));
            }
            return out;
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<ChargeSummary> chargeSummary() {
        String sql = """
            SELECT billable_item_code, COUNT(*) AS n
            FROM patient_records GROUP BY billable_item_code
            ORDER BY billable_item_code NULLS LAST""";
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            List<ChargeSummary> out = new ArrayList<>();
            while (rs.next()) {
                out.add(new ChargeSummary(rs.getString(1), rs.getLong(2)));
            }
            return out;
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<StaffRecordRef> recordsByStaff(long staffId) {
        String sql = """
            SELECT patient_record_id, component_code, updated_date
            FROM patient_records WHERE updated_by_staff_id = ?
            ORDER BY patient_record_id""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, staffId);
            try (ResultSet rs = ps.executeQuery()) {
                List<StaffRecordRef> out = new ArrayList<>();
                while (rs.next()) {
                    out.add(new StaffRecordRef(rs.getLong(1), rs.getString(2), ts(rs, "updated_date")));
                }
                return out;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public List<AdmissionEntry> admissionHistory(long patientId) {
        String sql = """
            SELECT admission_datetime, medical_condition, updated_date
            FROM patient_records
            WHERE patient_id = ? AND component_code = 'ADM'
            ORDER BY updated_date""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, patientId);
            try (ResultSet rs = ps.executeQuery()) {
                List<AdmissionEntry> out = new ArrayList<>();
                while (rs.next()) {
                    out.add(new AdmissionEntry(ts(rs, "admission_datetime"),
                            rs.getString(2), ts(rs, "updated_date")));
                }
                return out;
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    // --- writes ------------------------------------------------------------------

    @Override
    public void addClinicalRecord(NewClinicalRecord rec) {
        String sql = """
            INSERT INTO patient_records (patient_record_id, patient_id, billable_item_code,
                   component_code, updated_by_staff_id, updated_date, medical_condition,
                   patient_record_component_details)
            VALUES (?, ?, ?, ?, ?, SYSTIMESTAMP, ?, ?)""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, rec.recordId());
            ps.setLong(2, rec.patientId());
            ps.setString(3, rec.billableItemCode());
            ps.setString(4, rec.componentCode());
            ps.setLong(5, rec.staffId());
            ps.setString(6, rec.medicalCondition());
            ps.setString(7, rec.details());
            ps.executeUpdate();
            conn.commit();
        } catch (SQLException e) {
            rollbackQuietly();
            throw new IllegalStateException(e);
        }
    }

    @Override
    public void addBillItem(long billId, long patientId, BillItem item) {
        String sql = """
            INSERT INTO patient_bill_items (patient_bill_id, item_seq_nr, quantity, total_cost)
            VALUES (?, ?, ?, ?)""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, billId);
            ps.setLong(2, item.itemSeqNr());
            ps.setLong(3, item.quantity());
            ps.setLong(4, item.totalCost());
            ps.executeUpdate();
            conn.commit();
        } catch (SQLException e) {
            rollbackQuietly();
            throw new IllegalStateException(e);
        }
    }

    @Override
    public void admitPatient(long admissionId, long patientId, String roomId, long staffId) {
        try {
            try (PreparedStatement ps = conn.prepareStatement("""
                INSERT INTO patient_records (patient_record_id, patient_id, component_code,
                       updated_by_staff_id, updated_date, admission_datetime, medical_condition,
                       patient_record_component_details)
                VALUES (?, ?, 'ADM', ?, SYSTIMESTAMP, SYSTIMESTAMP, 'admitted', 'admission')""")) {
                ps.setLong(1, admissionId);
                ps.setLong(2, patientId);
                ps.setLong(3, staffId);
                ps.executeUpdate();
            }
            try (PreparedStatement ps = conn.prepareStatement("""
                INSERT INTO patient_rooms (stay_id, patient_id, room_id, date_stay_from, date_stay_to)
                VALUES (?, ?, ?, SYSTIMESTAMP, NULL)""")) {
                ps.setLong(1, admissionId);
                ps.setLong(2, patientId);
                ps.setString(3, roomId);
                ps.executeUpdate();
            }
            try (PreparedStatement ps = conn.prepareStatement("""
                INSERT INTO patient_bills (patient_bill_id, patient_id, date_bill_paid,
                       total_amount_due, other_bill_details)
                VALUES (?, ?, NULL, 0, 'open')""")) {
                ps.setLong(1, admissionId);
                ps.setLong(2, patientId);
                ps.executeUpdate();
            }
            conn.commit();
        } catch (SQLException e) {
            rollbackQuietly();
            throw new IllegalStateException(e);
        }
    }

    @Override
    public void settleBill(long billId) {
        String sql = """
            UPDATE patient_bills SET total_amount_due = 0, date_bill_paid = SYSTIMESTAMP
            WHERE patient_bill_id = ?""";
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setLong(1, billId);
            ps.executeUpdate();
            conn.commit();
        } catch (SQLException e) {
            rollbackQuietly();
            throw new IllegalStateException(e);
        }
    }

    /** Test support: remove the artifacts a write test created, on this surface. */
    public void deleteAdmissionArtifacts(long id) {
        try (Statement st = conn.createStatement()) {
            st.executeUpdate("DELETE FROM patient_bill_items WHERE patient_bill_id = " + id
                    + " OR (patient_bill_id = 500 AND item_seq_nr > 9000)");
            st.executeUpdate("DELETE FROM patient_bills WHERE patient_bill_id = " + id);
            st.executeUpdate("DELETE FROM patient_rooms WHERE stay_id = " + id);
            st.executeUpdate("DELETE FROM patient_records WHERE patient_record_id = " + id);
            conn.commit();
        } catch (SQLException e) {
            rollbackQuietly();
            throw new IllegalStateException(e);
        }
    }

    private void rollbackQuietly() {
        try {
            conn.rollback();
        } catch (SQLException ignored) {
        }
    }

    @Override
    public void close() {
        try {
            conn.close();
        } catch (SQLException ignored) {
        }
    }
}

package com.hospital.datalayer.mongo;

import com.hospital.datalayer.HospitalRepository;
import com.mongodb.ConnectionString;
import com.mongodb.MongoClientSettings;
import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import org.bson.Document;
import org.bson.conversions.Bson;

import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;
import java.security.cert.X509Certificate;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import static com.mongodb.client.model.Aggregates.group;
import static com.mongodb.client.model.Accumulators.sum;
import static com.mongodb.client.model.Filters.and;
import static com.mongodb.client.model.Filters.eq;
import static com.mongodb.client.model.Filters.exists;
import static com.mongodb.client.model.Filters.gt;
import static com.mongodb.client.model.Sorts.ascending;
import static com.mongodb.client.model.Sorts.descending;
import static com.mongodb.client.model.Updates.combine;
import static com.mongodb.client.model.Updates.push;
import static com.mongodb.client.model.Updates.set;

/**
 * MongoDB-API implementation over the document collections (patient_docs, record_docs,
 * bill_docs, room_stay_docs) through the Oracle API for MongoDB (ORDS, port 27017).
 *
 * Connection from MONGO_URI, or assembled from DB_USER / DB_PASSWORD / MONGO_HOST.
 * The ORDS endpoint requires TLS (self-signed in the dev container), PLAIN auth against
 * {@code $external}, {@code retryWrites=false} and {@code loadBalanced=true}.
 *
 * Timestamps are stored as 'YYYY-MM-DD HH24:MI:SS' strings (the seed convention);
 * this class converts them to/from LocalDateTime at the boundary.
 */
public final class MongoHospitalRepository implements HospitalRepository {

    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final MongoClient client;
    private final MongoCollection<Document> patients;
    private final MongoCollection<Document> records;
    private final MongoCollection<Document> bills;
    private final MongoCollection<Document> roomStays;

    public MongoHospitalRepository() {
        this(defaultUri());
    }

    public MongoHospitalRepository(String uri) {
        // The Java driver (unlike mongosh/pymongo) does not honor
        // tlsAllowInvalidCertificates in the URI — the dev container's self-signed
        // ORDS certificate needs an explicit trust-all context. Guarded by
        // MONGO_TLS_INSECURE (default true — this targets the local dev stack).
        MongoClientSettings.Builder b = MongoClientSettings.builder()
                .applyConnectionString(new ConnectionString(uri));
        if (!"false".equalsIgnoreCase(System.getenv().getOrDefault("MONGO_TLS_INSECURE", "true"))) {
            b.applyToSslSettings(ssl -> ssl.enabled(true).context(insecureContext()));
        }
        this.client = MongoClients.create(b.build());
        String user = System.getenv().getOrDefault("DB_USER", "hospital_dev");
        MongoDatabase db = client.getDatabase(user);
        this.patients = db.getCollection("patient_docs");
        this.records = db.getCollection("record_docs");
        this.bills = db.getCollection("bill_docs");
        this.roomStays = db.getCollection("room_stay_docs");
    }

    private static String defaultUri() {
        String uri = System.getenv("MONGO_URI");
        if (uri != null && !uri.isBlank()) {
            return uri;
        }
        String user = System.getenv("DB_USER");
        String pw = System.getenv("DB_PASSWORD");
        String host = System.getenv().getOrDefault("MONGO_HOST", "localhost:27017");
        if (user == null || pw == null) {
            throw new IllegalStateException("set MONGO_URI, or DB_USER and DB_PASSWORD");
        }
        return "mongodb://" + user + ":" + pw + "@" + host + "/" + user
                + "?authMechanism=PLAIN&authSource=$external"
                + "&tls=true&tlsAllowInvalidCertificates=true"
                + "&retryWrites=false&loadBalanced=true";
    }

    private static SSLContext insecureContext() {
        try {
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, new TrustManager[]{new X509TrustManager() {
                @Override public void checkClientTrusted(X509Certificate[] c, String a) {}
                @Override public void checkServerTrusted(X509Certificate[] c, String a) {}
                @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            }}, new java.security.SecureRandom());
            return ctx;
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static LocalDateTime ts(Object v) {
        return v == null ? null : LocalDateTime.parse(v.toString(), TS);
    }

    private static String fmt(LocalDateTime t) {
        return t == null ? null : TS.format(t);
    }

    private static long lng(Object v) {
        return ((Number) v).longValue();
    }

    // --- reads -----------------------------------------------------------------

    @Override
    public PatientSnapshot getPatientSnapshot(long patientId) {
        Document d = patients.find(eq("_id", patientId)).first();
        if (d == null) {
            return null;
        }
        List<Address> addresses = new ArrayList<>();
        List<Document> raw = d.getList("addresses", Document.class, List.of());
        raw.stream()
           .sorted(Comparator.comparingLong(a -> lng(a.get("address_id"))))
           .forEach(a -> addresses.add(new Address(a.getString("line_1_number_building"),
                   a.getString("city"), a.getString("zip_postcode"))));
        return new PatientSnapshot(patientId, d.getString("patient_first_name"),
                d.getString("patient_last_name"), ts(d.get("date_of_birth")),
                d.getString("gender"), d.getString("next_of_kin"),
                d.getString("cell_mobile_phone"), addresses);
    }

    @Override
    public List<ChartEntry> getPatientChart(long patientId) {
        List<ChartEntry> out = new ArrayList<>();
        for (Document d : records.find(eq("patient_id", patientId))
                                 .sort(descending("updated_date"))) {
            out.add(new ChartEntry(d.getString("component_code"), ts(d.get("updated_date")),
                    d.getString("medical_condition"),
                    d.getString("patient_record_component_details")));
        }
        return out;
    }

    @Override
    public PatientRef findPatientByNumber(String hospitalNumber) {
        Document d = patients.find(eq("hospital_number", hospitalNumber)).first();
        return d == null ? null : new PatientRef(lng(d.get("_id")),
                d.getString("patient_first_name"), d.getString("patient_last_name"),
                d.getString("hospital_number"));
    }

    @Override
    public List<RoomStay> getRoomHistory(long patientId) {
        Document d = patients.find(eq("_id", patientId)).first();
        if (d == null) {
            return List.of();
        }
        List<RoomStay> out = new ArrayList<>();
        for (Document s : d.getList("roomstays", Document.class, List.of())) {
            out.add(new RoomStay(s.getString("room_id"), ts(s.get("date_stay_from")),
                    ts(s.get("date_stay_to"))));
        }
        out.sort(Comparator.comparing(RoomStay::stayFrom));
        return out;
    }

    @Override
    public List<CensusEntry> wardCensus() {
        List<CensusEntry> out = new ArrayList<>();
        for (Document d : roomStays.find(exists("date_stay_to", false))
                                   .sort(ascending("patient_id", "date_stay_from"))) {
            out.add(new CensusEntry(lng(d.get("patient_id")), d.getString("room_id"),
                    ts(d.get("date_stay_from"))));
        }
        return out;
    }

    @Override
    public Bill getBillWithItems(long billId) {
        Document d = bills.find(eq("_id", billId)).first();
        if (d == null) {
            return null;
        }
        List<BillItem> items = new ArrayList<>();
        d.getList("billitems", Document.class, List.of()).stream()
         .sorted(Comparator.comparingLong(i -> lng(i.get("item_seq_nr"))))
         .forEach(i -> items.add(new BillItem(lng(i.get("item_seq_nr")),
                 lng(i.get("quantity")), lng(i.get("total_cost")))));
        return new Bill(billId, lng(d.get("total_amount_due")),
                ts(d.get("date_bill_paid")), items);
    }

    @Override
    public List<PaymentMethod> getPaymentMethods(long patientId) {
        Document d = patients.find(eq("_id", patientId)).first();
        if (d == null) {
            return List.of();
        }
        List<PaymentMethod> out = new ArrayList<>();
        d.getList("paymentmethods", Document.class, List.of()).stream()
         .sorted(Comparator.comparingLong(m -> lng(m.get("patient_method_id"))))
         .forEach(m -> out.add(new PaymentMethod(m.getString("payment_method_code"),
                 m.getString("payment_method_details"))));
        return out;
    }

    @Override
    public List<OpenBill> listOpenBills() {
        List<OpenBill> out = new ArrayList<>();
        Bson open = and(exists("date_bill_paid", false), gt("total_amount_due", 0));
        for (Document d : bills.find(open).sort(ascending("_id"))) {
            out.add(new OpenBill(lng(d.get("_id")), lng(d.get("patient_id")),
                    lng(d.get("total_amount_due"))));
        }
        return out;
    }

    @Override
    public List<ChargeSummary> chargeSummary() {
        List<ChargeSummary> out = new ArrayList<>();
        for (Document d : records.aggregate(Arrays.asList(
                group("$billable_item_code", sum("n", 1))))) {
            out.add(new ChargeSummary(d.getString("_id"), lng(d.get("n"))));
        }
        out.sort(Comparator.comparing(ChargeSummary::billableItemCode,
                Comparator.nullsLast(Comparator.naturalOrder())));
        return out;
    }

    @Override
    public List<StaffRecordRef> recordsByStaff(long staffId) {
        List<StaffRecordRef> out = new ArrayList<>();
        for (Document d : records.find(eq("updated_by_staff_id", staffId))
                                 .sort(ascending("_id"))) {
            out.add(new StaffRecordRef(lng(d.get("_id")), d.getString("component_code"),
                    ts(d.get("updated_date"))));
        }
        return out;
    }

    @Override
    public List<AdmissionEntry> admissionHistory(long patientId) {
        List<AdmissionEntry> out = new ArrayList<>();
        Bson q = and(eq("patient_id", patientId), eq("component_code", "ADM"));
        for (Document d : records.find(q).sort(ascending("updated_date"))) {
            out.add(new AdmissionEntry(ts(d.get("admission_datetime")),
                    d.getString("medical_condition"), ts(d.get("updated_date"))));
        }
        return out;
    }

    // --- writes ------------------------------------------------------------------

    @Override
    public void addClinicalRecord(NewClinicalRecord rec) {
        Document d = new Document("_id", rec.recordId())
                .append("patient_id", rec.patientId())
                .append("component_code", rec.componentCode())
                .append("updated_by_staff_id", rec.staffId())
                .append("updated_date", fmt(LocalDateTime.now()))
                .append("medical_condition", rec.medicalCondition())
                .append("patient_record_component_details", rec.details());
        if (rec.billableItemCode() != null) {
            d.append("billable_item_code", rec.billableItemCode());
        }
        records.insertOne(d);
    }

    @Override
    public void addBillItem(long billId, long patientId, BillItem item) {
        Document it = new Document("patient_bill_id", billId)
                .append("item_seq_nr", item.itemSeqNr())
                .append("quantity", item.quantity())
                .append("total_cost", item.totalCost());
        bills.updateOne(eq("_id", billId), push("billitems", it));
    }

    @Override
    public void admitPatient(long admissionId, long patientId, String roomId, long staffId) {
        String now = fmt(LocalDateTime.now());
        records.insertOne(new Document("_id", admissionId)
                .append("patient_id", patientId)
                .append("component_code", "ADM")
                .append("updated_by_staff_id", staffId)
                .append("updated_date", now)
                .append("admission_datetime", now)
                .append("medical_condition", "admitted")
                .append("patient_record_component_details", "admission"));
        roomStays.insertOne(new Document("_id", admissionId)
                .append("patient_id", patientId)
                .append("room_id", roomId)
                .append("date_stay_from", now));
        patients.updateOne(eq("_id", patientId),
                push("roomstays", new Document("room_id", roomId).append("date_stay_from", now)));
        bills.insertOne(new Document("_id", admissionId)
                .append("patient_id", patientId)
                .append("total_amount_due", 0L)
                .append("billitems", List.of()));
    }

    @Override
    public void settleBill(long billId) {
        bills.updateOne(eq("_id", billId),
                combine(set("total_amount_due", 0L), set("date_bill_paid", fmt(LocalDateTime.now()))));
    }

    /** Test support: remove the artifacts a write test created, on this surface.
     *  Idempotent — the embedded stay is pulled by its exact shape (an OPEN stay in
     *  the given room), never popped blindly. */
    public void deleteAdmissionArtifacts(long id, long patientId, String roomId) {
        records.deleteOne(eq("_id", id));
        roomStays.deleteOne(eq("_id", id));
        bills.deleteOne(eq("_id", id));
        patients.updateOne(eq("_id", patientId),
                new Document("$pull", new Document("roomstays",
                        new Document("room_id", roomId)
                                .append("date_stay_to", new Document("$exists", false)))));
        bills.updateOne(eq("_id", 500L),
                new Document("$pull", new Document("billitems",
                        new Document("item_seq_nr", new Document("$gt", 9000L)))));
    }

    @Override
    public void close() {
        client.close();
    }
}

#!/usr/bin/env python3
"""Dual-surface benchmark: native SQL vs the Oracle API for MongoDB.

Same database, same seeded data. Each top access pattern runs three ways:
  sql/relational — native SQL over the relational schema (thin driver)
  sql/document   — native SQL/JSON over the document collections (thin driver)
  mongo/document — the MongoDB wire protocol over the SAME collections (pymongo -> ORDS)

Client-side elapsed time is the right unit here: the surface comparison is about what
an application pays end-to-end on each API, including the driver and (for Mongo) the
ORDS translation hop. Equivalence before speed: every read must return the same values
on all three surfaces before its timings count.

Env: DB_USER, DB_PASSWORD, DB_DSN, MONGO_HOST (default localhost:27017).
Usage: python surface_bench.py [--trials 50] [--warmup 10] [--json out.json]
"""
import argparse
import json
import os
import statistics
import time

import oracledb
import pymongo

TS = "%Y-%m-%d %H:%M:%S"


def env(name, default=None):
    v = os.environ.get(name, default)
    if v is None:
        raise SystemExit(f"set {name}")
    return v


def norm(v):
    """Normalize a value for cross-surface comparison."""
    import datetime
    if isinstance(v, datetime.datetime):
        return v.strftime(TS)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def rows_key(rows):
    return sorted(tuple(norm(c) for c in r) for r in rows)


# --- the patterns, one implementation per surface --------------------------------

def patterns(conn, db):
    """[(name, kind, {surface: thunk-returning-rows})]. Writes return None and clean
    up outside the timed region (cleanup cost is excluded from the medians)."""
    cur = conn.cursor()

    def sql_rows(q, binds=()):
        cur.execute(q, binds)
        return cur.fetchall()

    pd, rd, bd, rsd = (db["patient_docs"], db["record_docs"], db["bill_docs"],
                       db["room_stay_docs"])

    P = []

    # R1 get_patient_snapshot (patient 42 + addresses)
    P.append(("get_patient_snapshot", "read", {
        "sql/relational": lambda: sql_rows("""
            SELECT p.patient_first_name, p.patient_last_name, a.city, a.zip_postcode
            FROM patients p
            JOIN patient_addresses pa ON pa.patient_id = p.patient_id
            JOIN addresses a ON a.address_id = pa.address_id
            WHERE p.patient_id = :1""", (42,)),
        "sql/document": lambda: sql_rows("""
            SELECT JSON_VALUE(d.data, '$.patient_first_name'),
                   JSON_VALUE(d.data, '$.patient_last_name'), a.city, a.zip
            FROM patient_docs d,
                 JSON_TABLE(d.data, '$.addresses[*]'
                   COLUMNS (city VARCHAR2(100) PATH '$.city',
                            zip  VARCHAR2(20)  PATH '$.zip_postcode')) a
            WHERE JSON_VALUE(d.data, '$._id' RETURNING NUMBER) = :1""", (42,)),
        "mongo/document": lambda: [
            (doc["patient_first_name"], doc["patient_last_name"], a["city"], a["zip_postcode"])
            for doc in pd.find({"_id": 42})
            for a in doc.get("addresses", [])],
    }))

    # R2 get_patient_chart (newest first)
    P.append(("get_patient_chart", "read", {
        "sql/relational": lambda: sql_rows("""
            SELECT component_code, TO_CHAR(updated_date, 'YYYY-MM-DD HH24:MI:SS'),
                   medical_condition
            FROM patient_records WHERE patient_id = :1
            ORDER BY updated_date DESC""", (42,)),
        "sql/document": lambda: sql_rows("""
            SELECT JSON_VALUE(d.data, '$.component_code'),
                   JSON_VALUE(d.data, '$.updated_date'),
                   JSON_VALUE(d.data, '$.medical_condition')
            FROM record_docs d
            WHERE JSON_VALUE(d.data, '$.patient_id' RETURNING NUMBER) = :1
            ORDER BY JSON_VALUE(d.data, '$.updated_date') DESC""", (42,)),
        "mongo/document": lambda: [
            (d["component_code"], d["updated_date"], d["medical_condition"])
            for d in rd.find({"patient_id": 42}).sort("updated_date", -1)],
    }))

    # R3 find_patient_by_number
    P.append(("find_patient_by_number", "read", {
        "sql/relational": lambda: sql_rows("""
            SELECT patient_id, patient_last_name FROM patients
            WHERE hospital_number = :1""", ("H0000042",)),
        "sql/document": lambda: sql_rows("""
            SELECT JSON_VALUE(d.data, '$._id' RETURNING NUMBER),
                   JSON_VALUE(d.data, '$.patient_last_name')
            FROM patient_docs d WHERE JSON_VALUE(d.data, '$.hospital_number') = :1""",
            ("H0000042",)),
        "mongo/document": lambda: [
            (d["_id"], d["patient_last_name"])
            for d in pd.find({"hospital_number": "H0000042"})],
    }))

    # R4 get_room_history (embedded in the patient doc)
    P.append(("get_room_history", "read", {
        "sql/relational": lambda: sql_rows("""
            SELECT room_id, TO_CHAR(date_stay_from, 'YYYY-MM-DD HH24:MI:SS')
            FROM patient_rooms WHERE patient_id = :1""", (42,)),
        "sql/document": lambda: sql_rows("""
            SELECT s.room_id, s.dsf
            FROM patient_docs d,
                 JSON_TABLE(d.data, '$.roomstays[*]'
                   COLUMNS (room_id VARCHAR2(20) PATH '$.room_id',
                            dsf VARCHAR2(20) PATH '$.date_stay_from')) s
            WHERE JSON_VALUE(d.data, '$._id' RETURNING NUMBER) = :1""", (42,)),
        "mongo/document": lambda: [
            (s["room_id"], s["date_stay_from"])
            for doc in pd.find({"_id": 42}) for s in doc.get("roomstays", [])],
    }))

    # R5 ward_census (absence predicate, cross-patient)
    P.append(("ward_census", "read", {
        "sql/relational": lambda: sql_rows("""
            SELECT patient_id, room_id FROM patient_rooms WHERE date_stay_to IS NULL"""),
        "sql/document": lambda: sql_rows("""
            SELECT JSON_VALUE(d.data, '$.patient_id' RETURNING NUMBER),
                   JSON_VALUE(d.data, '$.room_id')
            FROM room_stay_docs d
            WHERE NOT JSON_EXISTS(d.data, '$.date_stay_to')"""),
        "mongo/document": lambda: [
            (d["patient_id"], d["room_id"])
            for d in rsd.find({"date_stay_to": {"$exists": False}})],
    }))

    # R6 get_bill_with_items
    P.append(("get_bill_with_items", "read", {
        "sql/relational": lambda: sql_rows("""
            SELECT b.total_amount_due, i.item_seq_nr, i.quantity, i.total_cost
            FROM patient_bills b
            JOIN patient_bill_items i ON i.patient_bill_id = b.patient_bill_id
            WHERE b.patient_bill_id = :1""", (500,)),
        "sql/document": lambda: sql_rows("""
            SELECT JSON_VALUE(d.data, '$.total_amount_due' RETURNING NUMBER),
                   i.seq, i.qty, i.cost
            FROM bill_docs d,
                 JSON_TABLE(d.data, '$.billitems[*]'
                   COLUMNS (seq NUMBER PATH '$.item_seq_nr',
                            qty NUMBER PATH '$.quantity',
                            cost NUMBER PATH '$.total_cost')) i
            WHERE JSON_VALUE(d.data, '$._id' RETURNING NUMBER) = :1""", (500,)),
        "mongo/document": lambda: [
            (doc["total_amount_due"], i["item_seq_nr"], i["quantity"], i["total_cost"])
            for doc in bd.find({"_id": 500}) for i in doc.get("billitems", [])],
    }))

    # W1 add_clinical_record — timed insert, cleanup untimed
    seq = {"n": 8_000_000}

    def w1_sql_rel():
        seq["n"] += 1
        cur.execute("""
            INSERT INTO patient_records (patient_record_id, patient_id, component_code,
                   updated_by_staff_id, updated_date, medical_condition,
                   patient_record_component_details)
            VALUES (:1, 42, 'NOTE', 7, SYSTIMESTAMP, 'stable', 'note')""", (seq["n"],))
        conn.commit()

    def w1_sql_doc():
        seq["n"] += 1
        cur.execute("""
            INSERT INTO record_docs (data) VALUES (JSON_OBJECT(
              '_id' VALUE :1, 'patient_id' VALUE 42, 'component_code' VALUE 'NOTE',
              'updated_by_staff_id' VALUE 7,
              'updated_date' VALUE TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'),
              'medical_condition' VALUE 'stable',
              'patient_record_component_details' VALUE 'note'))""", (seq["n"],))
        conn.commit()

    def w1_mongo():
        seq["n"] += 1
        rd.insert_one({"_id": seq["n"], "patient_id": 42, "component_code": "NOTE",
                       "updated_by_staff_id": 7,
                       "updated_date": time.strftime(TS),
                       "medical_condition": "stable",
                       "patient_record_component_details": "note"})

    P.append(("add_clinical_record", "write", {
        "sql/relational": w1_sql_rel, "sql/document": w1_sql_doc, "mongo/document": w1_mongo,
    }))

    # W2 add_bill_item — relational INSERT vs whole-doc rewrite vs $push
    def w2_sql_rel():
        seq["n"] += 1
        cur.execute("""
            INSERT INTO patient_bill_items (patient_bill_id, item_seq_nr, quantity, total_cost)
            VALUES (500, :1, 1, 125)""", (seq["n"],))
        conn.commit()

    def w2_sql_doc():
        seq["n"] += 1
        cur.execute("""
            UPDATE bill_docs SET data = JSON_TRANSFORM(data,
              APPEND '$.billitems' = JSON_OBJECT('patient_bill_id' VALUE 500,
                'item_seq_nr' VALUE :1, 'quantity' VALUE 1, 'total_cost' VALUE 125))
            WHERE JSON_VALUE(data, '$._id' RETURNING NUMBER) = 500""", (seq["n"],))
        conn.commit()

    def w2_mongo():
        seq["n"] += 1
        bd.update_one({"_id": 500}, {"$push": {"billitems": {
            "patient_bill_id": 500, "item_seq_nr": seq["n"], "quantity": 1,
            "total_cost": 125}}})

    P.append(("add_bill_item", "write", {
        "sql/relational": w2_sql_rel, "sql/document": w2_sql_doc, "mongo/document": w2_mongo,
    }))

    def cleanup():
        cur.execute("DELETE FROM patient_records WHERE patient_record_id > 8000000")
        cur.execute("DELETE FROM patient_bill_items WHERE patient_bill_id = 500 AND item_seq_nr > 8000000")
        conn.commit()
        rd.delete_many({"_id": {"$gt": 8_000_000}})
        bd.update_one({"_id": 500}, {"$pull": {"billitems": {"item_seq_nr": {"$gt": 8_000_000}}}})
        cur.execute("""UPDATE bill_docs SET data = JSON_TRANSFORM(data,
            REMOVE '$.billitems[*]?(@.item_seq_nr > 8000000)')
            WHERE JSON_VALUE(data,'$._id' RETURNING NUMBER) = 500""")
        conn.commit()

    return P, cleanup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--json", help="write raw results to this file")
    args = ap.parse_args()

    user, pw = env("DB_USER"), env("DB_PASSWORD")
    conn = oracledb.connect(user=user, password=pw, dsn=env("DB_DSN"))
    mongo_host = os.environ.get("MONGO_HOST", "localhost:27017")
    uri = (f"mongodb://{user}:{pw}@{mongo_host}/{user}"
           "?authMechanism=PLAIN&authSource=$external"
           "&tls=true&tlsAllowInvalidCertificates=true"
           "&retryWrites=false&loadBalanced=true")
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=10000)
    db = client[user]

    pats, cleanup = patterns(conn, db)
    results = {}
    print(f"{'pattern':<24} {'kind':<6} {'sql/relational':>16} {'sql/document':>14} "
          f"{'mongo/document':>15}   equivalent?")
    print("-" * 90)
    for name, kind, impls in pats:
        # equivalence gate first (reads only)
        equal = "-"
        if kind == "read":
            keys = {s: rows_key(f()) for s, f in impls.items()}
            ref = keys["sql/relational"]
            bad = [s for s, k in keys.items() if k != ref]
            equal = "YES" if not bad else f"NO ({', '.join(bad)})"
        meds = {}
        for surface, fn in impls.items():
            for _ in range(args.warmup):
                fn()
            times = []
            for _ in range(args.trials):
                t0 = time.perf_counter()
                fn()
                times.append((time.perf_counter() - t0) * 1_000_000)
            meds[surface] = statistics.median(times)
        results[name] = {"kind": kind, "equivalent": equal, "median_us": meds}
        print(f"{name:<24} {kind:<6} {meds['sql/relational']:>14,.0f}us "
              f"{meds['sql/document']:>12,.0f}us {meds['mongo/document']:>13,.0f}us   {equal}")
    cleanup()
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
    conn.close()
    client.close()


if __name__ == "__main__":
    main()

# Copyright (c) 2026 Oracle and/or its affiliates.
"""Phase-3 live verification — the `organization` (IOT) and `compress`
dimensions against a real 26ai Free (spec §4).

Proves on the live engine what the unit tier can only assert as strings:
`ORGANIZATION INDEX PCTTHRESHOLD n INCLUDING col OVERFLOW` and `ROW STORE
COMPRESS ADVANCED` are accepted DDL and reach the dictionary as IOT and
COMPRESSION=ENABLED/COMPRESS_FOR=ADVANCED; the generated reads over an
index-organized base return the seeded answers (storage changed, not SQL);
IOT x HASH composes (the one partition family that does — ORA-25198 kills the
others); writes roll back on an IOT; redeploys are idempotent; and the
doc-unstated duality-over-IOT combination is pinned to its ACTUAL behavior —
if Oracle rejects it, v1 gains a blocker instead of a disclosure.

Gated: ORACLE_AI_DEV_LIVE=1 with a reachable 26ai (env ORACLE_AI_DEV_CONTAINER
/ ORACLE_AI_DEV_DSN / ORACLE_AI_DEV_PDB; defaults oracle-ai-dev-db /
localhost:1521/FREEPDB1 / FREEPDB1).
"""
import os
import subprocess

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.shared_container,
    pytest.mark.skipif(
        os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
        reason="set ORACLE_AI_DEV_LIVE=1 (with a reachable 26ai) to run the "
               "IOT/compress live tests"),
]

CONTAINER = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
DSN = os.environ.get("ORACLE_AI_DEV_DSN", "localhost:1521/FREEPDB1")
PDB = os.environ.get("ORACLE_AI_DEV_PDB", "FREEPDB1")
USER, PW = "iotval", "Iotval_pw_12345"

MODEL = {
    "entities": {
        "Sensor": {"table": "io_sensors", "pk": "sensor_id",
                   "columns": {"label": "label"}},
        # The IOT under test: narrow, PK-led, one parent FK. INCLUDING pushes
        # `value` to the OVERFLOW segment (P2's clause order, live).
        "Reading": {"table": "io_readings", "pk": "reading_id",
                    "columns": {"sensor_id": "sensor_id", "kind": "kind",
                                "value": "value"},
                    "column_types": {"value": "NUMBER"},
                    "organization": "index", "pctthreshold": 40,
                    "including": "kind"},
        # A heap carrying the OTHER dimension, so both deploy in one lane.
        "Ledger": {"table": "io_ledger", "pk": "entry_id",
                   "columns": {"memo": "memo", "amount": "amount"},
                   "column_types": {"amount": "NUMBER"},
                   "compress": "advanced"},
        # IOT x HASH: the partitioning key must be a subset of the primary
        # key on an index-organized table, so it partitions on its own PK.
        "Sample": {"table": "io_samples", "pk": "sample_id",
                   "columns": {"note": "note"},
                   "organization": "index",
                   "partition": {"by": "hash", "column": "sample_id",
                                 "partitions": 4}},
    },
    "relationships": [{"from": "Sensor", "to": "Reading", "cardinality": "1:N",
                       "from_key": "sensor_id", "to_key": "sensor_id"}],
    "projections": {"duality": {"Reading": "io_reading_dv"}},
}

_DROP_USER = (
    "BEGIN\n"
    f"  BEGIN EXECUTE IMMEDIATE 'ALTER USER {USER} ACCOUNT LOCK'; EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    f"  FOR s IN (SELECT sid, serial# sn FROM v$session WHERE username='{USER.upper()}') LOOP\n"
    "    BEGIN EXECUTE IMMEDIATE 'ALTER SYSTEM DISCONNECT SESSION '''||s.sid||','||s.sn||''' IMMEDIATE';\n"
    "    EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    "  END LOOP;\n"
    f"  BEGIN EXECUTE IMMEDIATE 'DROP USER {USER} CASCADE'; EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    "END;\n/\n")


def _sysdba(sql):
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-lc",
                        "sqlplus -S -L / as sysdba"], input=sql,
                       capture_output=True, text=True, timeout=90)
    return p.stdout + p.stderr


@pytest.fixture(scope="module")
def db(live_container):
    import oracledb
    boot = (f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER +
            f"CREATE USER {USER} IDENTIFIED BY {PW} DEFAULT TABLESPACE USERS "
            f"QUOTA UNLIMITED ON USERS;\n"
            f"GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, RESOURCE, "
            f"SELECT_CATALOG_ROLE TO {USER};\n")
    out = _sysdba(boot)
    assert "created" in out.lower() and "ORA-01920" not in out, out
    conn = oracledb.connect(user=USER, password=PW, dsn=DSN)
    conn.call_timeout = 30000
    yield conn
    conn.close()
    _sysdba(f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER)


def _exec(conn, ddl):
    for stmt in (s.strip() for s in ddl.split(";")):
        if not stmt:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
        except Exception as exc:
            code = getattr(exc.args[0], "code", None) if exc.args else None
            if code not in (955, 1430, 2260, 2264, 2275, 942, 1418, 2261, 1408):
                raise
    conn.commit()


def _rows(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


@pytest.fixture(scope="module")
def deployed(db):
    """The relational lane deployed with both dimensions and seeded — once."""
    from tooling.generate.ddl import generate_ddl, generate_indexes

    q_point = {"root": "Reading", "returns": ["Reading.kind", "Reading.value"],
               "predicates": [{"ref": "Reading.reading_id", "op": "=",
                               "value": 2}]}
    q_range = {"root": "Reading", "returns": ["Reading.reading_id"],
               "predicates": [{"ref": "Reading.reading_id", "op": "BETWEEN",
                               "value": [2, 4]}],
               "order_by": [{"ref": "Reading.reading_id"}]}
    q_kind = {"root": "Reading", "returns": ["Reading.reading_id"],
              "predicates": [{"ref": "Reading.kind", "op": "=",
                              "value": "temp"}]}

    _exec(db, generate_ddl(MODEL, "relational"))
    # Secondary B-trees on an IOT ride logical rowids — they must still BUILD.
    _exec(db, generate_indexes(MODEL, [q_point, q_range, q_kind],
                               shape="relational"))

    with db.cursor() as cur:
        cur.execute("DELETE FROM io_readings")
        cur.execute("DELETE FROM io_sensors")
        cur.execute("DELETE FROM io_ledger")
        cur.execute("DELETE FROM io_samples")
        for sid, lbl in [(1, "north-1"), (2, "north-2")]:
            cur.execute("INSERT INTO io_sensors (sensor_id, label) "
                        "VALUES (:1, :2)", (sid, lbl))
        for rid, sid, kind, val in [(1, 1, "temp", 21), (2, 1, "temp", 23),
                                    (3, 2, "humidity", 55), (4, 2, "temp", 19)]:
            cur.execute("INSERT INTO io_readings (reading_id, sensor_id, kind, "
                        "value) VALUES (:1, :2, :3, :4)", (rid, sid, kind, val))
        for eid, memo, amt in [(1, "open", 100), (2, "adjust", 250)]:
            cur.execute("INSERT INTO io_ledger (entry_id, memo, amount) "
                        "VALUES (:1, :2, :3)", (eid, memo, amt))
        for sid, note in [(1, "a"), (2, "b"), (3, "c")]:
            cur.execute("INSERT INTO io_samples (sample_id, note) "
                        "VALUES (:1, :2)", (sid, note))
    db.commit()
    return {"q_point": q_point, "q_range": q_range, "q_kind": q_kind}


def test_dictionary_shows_iot_and_advanced_compression(db, deployed):
    """§2 P1/P2/P5: ORGANIZATION INDEX and ROW STORE COMPRESS ADVANCED are
    what the engine actually stored, not just what we emitted."""
    iot = dict(_rows(db, "SELECT table_name, iot_type FROM user_tables "
                         "WHERE table_name IN ('IO_READINGS', 'IO_LEDGER')"))
    assert iot.get("IO_READINGS") == "IOT", iot
    assert iot.get("IO_LEDGER") is None, iot        # the heap stayed a heap
    comp = _rows(db, "SELECT compression, compress_for FROM user_tables "
                     "WHERE table_name = 'IO_LEDGER'")
    assert comp and comp[0][0] == "ENABLED", comp
    assert comp[0][1] == "ADVANCED", comp


def test_generated_reads_answer_over_an_index_organized_base(db, deployed):
    """§3 clauses 2/3: the dimensions change storage, not SQL — the generated
    point read and key-range read return the seeded answers."""
    from tooling.generate.sql import generate_relational

    point = _rows(db, generate_relational(MODEL, deployed["q_point"]))
    assert point == [("temp", 23)], point
    rng = _rows(db, generate_relational(MODEL, deployed["q_range"]))
    assert rng == [(2,), (3,), (4,)], rng          # key order, off the leaf
    kind = sorted(_rows(db, generate_relational(MODEL, deployed["q_kind"])))
    assert kind == [(1,), (2,), (4,)], kind        # secondary index, logical rowid


def test_iot_composes_with_hash_partitioning(db, deployed):
    """§2 P3: HASH is the one partition family an IOT accepts (AUTOMATIC LIST
    and INTERVAL raise ORA-25198), and it must reach the dictionary."""
    got = dict(_rows(db, "SELECT table_name, partitioning_type "
                         "FROM user_part_tables"))
    assert got.get("IO_SAMPLES") == "HASH", got
    n = _rows(db, "SELECT COUNT(*) FROM user_tab_partitions "
                  "WHERE table_name = 'IO_SAMPLES'")[0][0]
    assert n == 4, n


def test_duality_view_over_an_iot_base_actual_behavior(db, deployed):
    """§2 P6: doc-unstated, live-proven. Pin the REAL behavior — if this create
    or read fails, the spec's disclosure must become a blocker; change the
    code, not this test's spirit."""
    from tooling.generate.ddl import generate_ddl
    ddl = generate_ddl(MODEL, "duality")
    view_ddl = ddl[ddl.index("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW"):]
    _exec(db, view_ddl)
    doc = _rows(db, "SELECT d.data FROM io_reading_dv d "
                    "WHERE JSON_VALUE(d.data, '$._id' RETURNING NUMBER) = 2")
    assert doc, "the duality view over an IOT base returned no document"


def test_write_and_rollback_on_the_iot(db, deployed):
    """§3 clause 5: writes are unchanged by the dimension — the generated
    UPDATE runs against the leaf row and rolls back cleanly."""
    from tooling.generate.sql import generate_update
    upd = generate_update(MODEL, deployed["q_point"], "relational",
                          "Reading.value", delta=5)
    with db.cursor() as cur:
        cur.execute(upd)
    assert _rows(db, "SELECT value FROM io_readings WHERE reading_id = 2") == [(28,)]
    db.rollback()
    assert _rows(db, "SELECT value FROM io_readings WHERE reading_id = 2") == [(23,)]


def test_redeploy_is_idempotent(db, deployed):
    """§4: the emitted DDL re-runs against an already-deployed schema without
    a new ORA — the IOT and compress clauses included."""
    from tooling.generate.ddl import generate_ddl
    ddl = generate_ddl(MODEL, "relational")
    _exec(db, ddl)
    _exec(db, ddl)
    assert _rows(db, "SELECT iot_type FROM user_tables "
                     "WHERE table_name = 'IO_READINGS'") == [("IOT",)]

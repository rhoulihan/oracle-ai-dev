# Copyright (c) 2026 Oracle and/or its affiliates.
"""Final stack-validation test — exercises the whole stack against a LIVE Oracle AI
Database 26ai deployment and asserts the results, one capability per skill.

This is the test we maintain as the project grows: every new shape, generator,
optimizer step, or path should add (or extend) a check here so a single gated run
proves the stack still deploys and behaves end to end.

Gated: set ORACLE_AI_DEV_LIVE=1 (and a reachable DB). Connection comes from env:
  ORACLE_AI_DEV_CONTAINER  docker container for the sysdba bootstrap (default oracle-ai-dev-db)
  ORACLE_AI_DEV_DSN        oracledb DSN                              (default localhost:1521/FREEPDB1)
The pure-Python logic is covered by the fast suite; this validates the LIVE stack.

Skill coverage (12 skills): oracle-data-modeling (generators/DDL/decide/compare/
hierarchy), sql-json-dev, json-duality-dev, soda-dev, mongodb-api-dev (Mongo API CRUD),
vector-rag-dev (exact + IVF ANN + server-side VECTOR_EMBEDDING), ai-agent-dev
(agent-memory pattern), query-craft (SQL/PGQ + CONNECT BY), query-tuning (EXPLAIN plan),
oracle-ai-setup (the embedding-model configurator runs in the fixture). Two skills can't
run in a pure-SQL harness and are covered elsewhere: sqlcl-mcp-setup (the MCP stdio
server, exercised by the MCP wiring path) and ai-agent-dev's in-database Select AI
(needs external LLM credentials). No capability is silently skipped.
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.shared_container,
    pytest.mark.skipif(
        os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
        reason="set ORACLE_AI_DEV_LIVE=1 (with a reachable 26ai) to run the stack validation"),
]

CONTAINER = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
DSN = os.environ.get("ORACLE_AI_DEV_DSN", "localhost:1521/FREEPDB1")
PDB = os.environ.get("ORACLE_AI_DEV_PDB", "FREEPDB1")
USER, PW = "stackval", "Stackval_pw_12345"

# Robustly drop the schema even after the Mongo API ran: ORDS keeps a pooled
# connection open, so a plain DROP hits ORA-01940. Lock the account (block ORDS from
# re-authenticating), disconnect live sessions, then drop.
_DROP_STACKVAL = (
    "BEGIN\n"
    f"  BEGIN EXECUTE IMMEDIATE 'ALTER USER {USER} ACCOUNT LOCK'; EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    f"  FOR s IN (SELECT sid, serial# sn FROM v$session WHERE username='{USER.upper()}') LOOP\n"
    "    BEGIN EXECUTE IMMEDIATE 'ALTER SYSTEM DISCONNECT SESSION '''||s.sid||','||s.sn||''' IMMEDIATE';\n"
    "    EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    "  END LOOP;\n"
    f"  BEGIN EXECUTE IMMEDIATE 'DROP USER {USER} CASCADE'; EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    "END;\n/\n")


def _sysdba(sql):
    # stdout+stderr: a failed `docker exec` (e.g. container absent) must surface in
    # fixture assertions instead of reading as an empty, message-less output.
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-lc",
                        "sqlplus -S -L / as sysdba"], input=sql,
                       capture_output=True, text=True, timeout=90)
    return p.stdout + p.stderr


def _install_embedding_model():
    """Best-effort: run the ONNX auto-installer so server-side VECTOR_EMBEDDING is
    exercised (not skipped). Offline / rotated URL -> the server-side test skips.
    Cached after the first download; exercises setup-embedding-model.sh itself."""
    script = Path(__file__).resolve().parent.parent / "assets/tooling/configure/setup-embedding-model.sh"
    try:
        subprocess.run(["bash", str(script), CONTAINER, PDB, USER, PW],
                       capture_output=True, text=True, timeout=600)
    except Exception:
        pass


@pytest.fixture(scope="module")
def db(live_container):
    import oracledb
    boot = (f"ALTER SESSION SET CONTAINER = {PDB};\n"
            + _DROP_STACKVAL +
            f"CREATE USER {USER} IDENTIFIED BY {PW} DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS;\n"
            f"GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE SEQUENCE, CREATE MINING MODEL, "
            f"RESOURCE, SODA_APP, SELECT_CATALOG_ROLE TO {USER};\n")
    out = _sysdba(boot)
    assert "ORA-01920" not in out and "created" in out.lower(), out
    _install_embedding_model()   # exercise the AI stack's server-side embedding path
    conn = oracledb.connect(user=USER, password=PW, dsn=DSN)
    yield conn
    conn.close()
    _sysdba(f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_STACKVAL)


def _deploy(conn, ddl):
    """Execute a multi-statement DDL string (';'-separated), tolerating already-exists."""
    for stmt in (s.strip() for s in ddl.split(";")):
        if not stmt:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
        except Exception as exc:
            code = getattr(exc.args[0], "code", None) if exc.args else None
            if code not in (955, 1430, 2260, 2264, 2275, 942, 1418, 2261):
                raise
    conn.commit()


def _rows(conn, sql, binds=None):
    with conn.cursor() as cur:
        cur.execute(sql, binds or {})
        return cur.fetchall()


def _scalar(conn, sql, binds=None):
    r = _rows(conn, sql, binds)
    return r[0][0] if r else None


def _drop(conn, *objs):
    for kind, name in objs:
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP {kind} {name}" + (" PURGE" if kind == "TABLE" else ""))
        except Exception:
            pass
    conn.commit()


# --------------------------------------------------------------------------
# oracle-data-modeling / generators — every shape generates, deploys, and runs
# --------------------------------------------------------------------------
def test_generators_all_shapes_run_live(db, repo_root):
    from tooling.generate.sql import generate_relational, generate_document, generate_duality
    _drop(db, ("VIEW", "sv_dv"), ("TABLE", "sv_orders"), ("TABLE", "sv_docs"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_orders (order_id NUMBER PRIMARY KEY, total NUMBER)")
        cur.execute("INSERT INTO sv_orders VALUES (1000, 42)")
        cur.execute("CREATE JSON COLLECTION TABLE sv_docs")
        cur.execute("INSERT INTO sv_docs (data) VALUES (JSON('{\"_id\":1000,\"total\":42}'))")
        cur.execute("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW sv_dv AS "
                    "sv_orders @insert @update @delete { _id : order_id  total : total }")
    db.commit()
    model = {"entities": {"Order": {"table": "sv_orders", "pk": "order_id",
             "columns": {"total": "total"}}}, "relationships": [],
             "projections": {"duality": {"Order": "sv_dv"},
                             "document": {"Order": {"collection": "sv_docs", "id_path": "$._id"}}}}
    q = {"root": "Order", "returns": ["Order.total"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1000}]}
    assert _rows(db, generate_relational(model, q))[0][0] == 42
    assert _rows(db, generate_document(model, q))            # returns the doc
    assert _rows(db, generate_duality(model, q))             # duality doc
    _drop(db, ("VIEW", "sv_dv"), ("TABLE", "sv_orders"), ("TABLE", "sv_docs"))


# --------------------------------------------------------------------------
# DDL generator — relational (typed/composite PK) + single_table (sparse/partition)
# --------------------------------------------------------------------------
def test_ddl_real_airline_model_deploys(db, repo_root):
    from tooling.generate.ddl import generate_ddl
    model = json.loads((repo_root / "tests/integration/airline/model.json").read_text())
    ddl = generate_ddl(model, "relational")
    for t in ("passengers", "airports", "flight_costs", "itinerary_legs"):
        _drop(db, ("TABLE", t))
    _deploy(db, ddl)
    # composite PK + typed code PK deployed
    assert _scalar(db, "SELECT COUNT(*) FROM user_tab_columns WHERE table_name='AIRPORTS' AND column_name='AIRPORT_CODE' AND data_type='VARCHAR2'") == 1
    assert _scalar(db, "SELECT COUNT(*) FROM user_constraints WHERE table_name='ITINERARY_LEGS' AND constraint_type='P'") >= 1
    for t in ("itinerary_legs", "reservation_payments", "tickets", "flight_costs",
              "bookings", "legs", "flights", "orders", "menu_item", "review", "address",
              "passengers", "airports", "aircraft", "customer", "restaurant"):
        _drop(db, ("TABLE", t))


def test_single_table_sparse_partitioned_uses_sparse_index(db, repo_root):
    from tooling.generate.ingest import model_from_dynamodb
    from tooling.generate.ddl import generate_ddl
    from tooling.generate.sql import generate_single_table
    ff = json.loads((repo_root / "tests/fixtures/dynamodb_flightsfares.json").read_text())
    model, _ = model_from_dynamodb(ff)
    _drop(db, ("TABLE", "reservations"))
    _deploy(db, generate_ddl(model, "single_table"))
    # automatic list-partitioning by type
    assert _scalar(db, "SELECT partitioning_type FROM user_part_tables WHERE table_name='RESERVATIONS'") == "LIST"
    with db.cursor() as cur:
        for i in range(1, 200):
            cur.execute("INSERT INTO reservations (type,pk0,depart,flight,segId,seat) "
                        "VALUES ('assignment', :p, SYSTIMESTAMP, :f, 1, '1A')",
                        {"p": f"Pax{i}", "f": i})
    db.commit()
    with db.cursor() as cur:
        cur.execute("BEGIN DBMS_STATS.GATHER_TABLE_STATS(USER,'RESERVATIONS'); END;")
    sql = generate_single_table(model, {"type": "assignment", "returns": ["assignment.seat"],
        "predicates": [{"ref": "assignment.pk0", "op": "=", "value": "Pax100"}]})
    assert _rows(db, sql)          # returns the seat
    _drop(db, ("TABLE", "reservations"))


# --------------------------------------------------------------------------
# Index derivation — derived indexes deploy and are usable
# --------------------------------------------------------------------------
def test_generate_indexes_deploy(db, repo_root):
    from tooling.generate.ddl import generate_ddl, generate_indexes
    model = {"entities": {"B": {"table": "sv_book", "pk": "id",
             "columns": {"passengerId": "passenger_id", "status": "status"}}}, "relationships": []}
    q = [{"root": "B", "returns": ["B.id"], "predicates": [
        {"ref": "B.passengerId", "op": "="}, {"ref": "B.status", "op": "="}]}]
    _drop(db, ("TABLE", "sv_book"))
    _deploy(db, generate_ddl(model, "relational"))
    _deploy(db, generate_indexes(model, q))
    # a composite index on (passenger_id, status) exists
    assert _scalar(db, "SELECT COUNT(*) FROM user_ind_columns ic JOIN user_indexes i "
                       "ON i.index_name=ic.index_name WHERE i.table_name='SV_BOOK' AND ic.column_name='PASSENGER_ID'") >= 1
    _drop(db, ("TABLE", "sv_book"))


# --------------------------------------------------------------------------
# Optimizer — live measurements fuel recommend_model / decide_model
# --------------------------------------------------------------------------
def test_optimizer_decides_from_live_measurements(db):
    from tooling.optimize.decide import decide_model
    # measure a point read two ways: an indexed table vs a full scan
    _drop(db, ("TABLE", "sv_fast"), ("TABLE", "sv_slow"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_fast (k NUMBER PRIMARY KEY, v NUMBER)")
        cur.execute("CREATE TABLE sv_slow (k NUMBER, v NUMBER)")
        cur.executemany("INSERT INTO sv_fast VALUES (:1,:2)", [(i, i) for i in range(1, 5000)])
        cur.executemany("INSERT INTO sv_slow VALUES (:1,:2)", [(i, i) for i in range(1, 5000)])
    db.commit()

    def lreads(sql):
        base = _scalar(db, "SELECT value FROM v$mystat s JOIN v$statname n ON n.statistic#=s.statistic# WHERE n.name='consistent gets'")
        for _ in range(20):
            _rows(db, sql)
        after = _scalar(db, "SELECT value FROM v$mystat s JOIN v$statname n ON n.statistic#=s.statistic# WHERE n.name='consistent gets'")
        return (after - base) / 20
    fast = lreads("SELECT v FROM sv_fast WHERE k = 2500")
    slow = lreads("SELECT v FROM sv_slow WHERE k = 2500")
    assert fast < slow                                        # the PK lookup is cheaper
    d = decide_model({"read": {"kind": "read", "rate": 1000}},
                     {"read": {"indexed": fast, "scan": slow}})
    assert d["chosen"] == "indexed"                           # matrix elects the cheaper design
    _drop(db, ("TABLE", "sv_fast"), ("TABLE", "sv_slow"))


# --------------------------------------------------------------------------
# Datalayer — generated Python DAO + ensure_schema deploy and run live
# --------------------------------------------------------------------------
def test_datalayer_python_runs_live(db, repo_root, tmp_path):
    import importlib.util
    from tooling.datalayer.platforms import write_datalayer
    model = {"entities": {"Widget": {"table": "sv_widget", "pk": "widget_id",
             "columns": {"name": "name", "qty": "qty"}}}, "relationships": []}
    spec = {"model": model, "platforms": ["python"], "patterns": [
        {"name": "get_widget", "shape": "relational", "query": {"root": "Widget",
         "returns": ["Widget.widget_id", "Widget.name", "Widget.qty"],
         "predicates": [{"ref": "Widget.widget_id", "op": "=", "value": 0}]}}]}
    write_datalayer(spec, str(tmp_path))
    spec_mod = importlib.util.spec_from_file_location("sv_repo", tmp_path / "repository.py")
    repo = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(repo)
    _drop(db, ("TABLE", "sv_widget"))
    assert repo.ensure_schema(db) is True                     # auto-deploys the schema
    with db.cursor() as cur:
        cur.execute("INSERT INTO sv_widget (widget_id, name, qty) VALUES (7, 'bolt', 42)")
    db.commit()
    rows = repo.get_widget(db, b0=7)                          # the generated bind-by-name method
    assert rows and rows[0]["QTY"] == 42
    _drop(db, ("TABLE", "sv_widget"))


# --------------------------------------------------------------------------
# Document paths — SODA-style collection, duality read/write, SQL/JSON, vector
# --------------------------------------------------------------------------
def test_json_collection_and_sql_json(db):
    _drop(db, ("TABLE", "sv_jcoll"))
    with db.cursor() as cur:
        cur.execute("CREATE JSON COLLECTION TABLE sv_jcoll")
        cur.execute("INSERT INTO sv_jcoll (data) VALUES (JSON('{\"_id\":1,\"tags\":[\"a\",\"b\"],\"n\":5}'))")
    db.commit()
    # JSON_VALUE + JSON_TABLE unnest
    assert _scalar(db, "SELECT JSON_VALUE(data,'$.n' RETURNING NUMBER) FROM sv_jcoll") == 5
    tags = _rows(db, "SELECT jt.tag FROM sv_jcoll, JSON_TABLE(data,'$.tags[*]' COLUMNS(tag PATH '$')) jt")
    assert {t[0] for t in tags} == {"a", "b"}
    _drop(db, ("TABLE", "sv_jcoll"))


def test_duality_view_is_updatable(db):
    _drop(db, ("VIEW", "sv_wdv"), ("TABLE", "sv_w"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_w (id NUMBER PRIMARY KEY, qty NUMBER)")
        cur.execute("INSERT INTO sv_w VALUES (1, 10)")
        cur.execute("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW sv_wdv AS "
                    "sv_w @insert @update @delete { _id : id  qty : qty }")
    db.commit()
    doc = _scalar(db, "SELECT JSON_VALUE(data,'$.qty' RETURNING NUMBER) FROM sv_wdv WHERE JSON_VALUE(data,'$._id' RETURNING NUMBER)=1")
    assert doc == 10
    # write through the duality view -> base table changes
    with db.cursor() as cur:
        cur.execute("UPDATE sv_wdv d SET d.data = JSON_TRANSFORM(d.data, SET '$.qty' = 99) "
                    "WHERE JSON_VALUE(d.data,'$._id' RETURNING NUMBER) = 1")
    db.commit()
    assert _scalar(db, "SELECT qty FROM sv_w WHERE id = 1") == 99
    _drop(db, ("VIEW", "sv_wdv"), ("TABLE", "sv_w"))


def test_vector_search(db):
    _drop(db, ("TABLE", "sv_vec"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_vec (id NUMBER PRIMARY KEY, embedding VECTOR(3, FLOAT32))")
        cur.execute("INSERT INTO sv_vec VALUES (1, TO_VECTOR('[1,0,0]'))")
        cur.execute("INSERT INTO sv_vec VALUES (2, TO_VECTOR('[0,1,0]'))")
        cur.execute("INSERT INTO sv_vec VALUES (3, TO_VECTOR('[0.9,0.1,0]'))")
    db.commit()
    # exact nearest to [1,0,0] is id 1, then id 3
    nearest = _rows(db, "SELECT id FROM sv_vec ORDER BY VECTOR_DISTANCE(embedding, TO_VECTOR('[1,0,0]'), COSINE) "
                        "FETCH FIRST 2 ROWS ONLY")
    assert [r[0] for r in nearest] == [1, 3]
    _drop(db, ("TABLE", "sv_vec"))


def test_vector_ivf_index_approximate_search(db):
    # the AI stack's retrieval engine: an IVF vector index + APPROX (ANN) search, live
    _drop(db, ("TABLE", "sv_ann"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_ann (id NUMBER PRIMARY KEY, embedding VECTOR(8, FLOAT32))")
        for i in range(1, 400):                       # enough rows for IVF to build real centroids
            vec = "[" + ",".join("1" if j == (i % 8) else "0" for j in range(8)) + "]"
            cur.execute("INSERT INTO sv_ann VALUES (:1, TO_VECTOR(:2))", (i, vec))
    db.commit()
    with db.cursor() as cur:
        cur.execute("CREATE VECTOR INDEX sv_ann_ix ON sv_ann (embedding) "
                    "ORGANIZATION NEIGHBOR PARTITIONS DISTANCE COSINE")
    assert _scalar(db, "SELECT index_type FROM user_indexes WHERE index_name='SV_ANN_IX'") == "VECTOR"
    hits = _rows(db, "SELECT id FROM sv_ann ORDER BY VECTOR_DISTANCE(embedding, TO_VECTOR('[1,0,0,0,0,0,0,0]'), COSINE) "
                     "FETCH APPROX FIRST 5 ROWS ONLY")
    # every neighbour the ANN index returns is a true dim-0 vector (id % 8 == 0)
    assert hits and all(r[0] % 8 == 0 for r in hits)
    _drop(db, ("TABLE", "sv_ann"))


# --------------------------------------------------------------------------
# ai-agent-dev — the Oracle agent-memory pattern (the "agent memory labs" shape):
# memory rows with vector embeddings, an updatable JSON duality view over the
# normalized record, superseded_by fact revision, and COSINE recall.
# --------------------------------------------------------------------------
def test_agent_memory_duality_and_vector_recall(db):
    _drop(db, ("VIEW", "am_facts"), ("TABLE", "am_tags"), ("TABLE", "am_memories"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE am_memories ("
                    "id VARCHAR2(64) PRIMARY KEY, session_id VARCHAR2(64) NOT NULL, "
                    "content VARCHAR2(4000) NOT NULL, embedding VECTOR(384, FLOAT32), "
                    "superseded_by VARCHAR2(64))")
        cur.execute("CREATE TABLE am_tags ("
                    "tag_id VARCHAR2(64) PRIMARY KEY, "
                    "mem_id VARCHAR2(64) NOT NULL REFERENCES am_memories(id) ON DELETE CASCADE, "
                    "tag VARCHAR2(64) NOT NULL)")
        # the updatable memory record (embedding stays out of the view; written server-side after)
        cur.execute("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW am_facts AS "
                    "am_memories @insert @update @delete "
                    "{ _id: id, sessionId: session_id, content, supersededBy: superseded_by, "
                    "  tags: am_tags @insert @update @delete { tagId: tag_id, tag } }")
    db.commit()

    def emb(dim):  # a 384-dim one-hot vector literal
        return "[" + ",".join("1" if j == dim else "0" for j in range(384)) + "]"

    # insert two memories THROUGH the duality view (parent + nested child tags in one JSON write)
    with db.cursor() as cur:
        cur.execute("INSERT INTO am_facts (data) VALUES ('"
                    '{"_id":"m1","sessionId":"s1","content":"user prefers window seats",'
                    '"tags":[{"tagId":"t1","tag":"seating"}]}\')')
        cur.execute("INSERT INTO am_facts (data) VALUES ('"
                    '{"_id":"m2","sessionId":"s1","content":"user is vegetarian",'
                    '"tags":[{"tagId":"t2","tag":"meal"}]}\')')
        # embeddings written server-side, on the base table (as the labs' write pipeline does)
        cur.execute("UPDATE am_memories SET embedding = TO_VECTOR(:v) WHERE id='m1'", {"v": emb(0)})
        cur.execute("UPDATE am_memories SET embedding = TO_VECTOR(:v) WHERE id='m2'", {"v": emb(1)})
    db.commit()

    # the child tag arrived through the JSON write, and the record reads back as a document
    assert _scalar(db, "SELECT COUNT(*) FROM am_tags WHERE mem_id='m1'") == 1
    doc = _scalar(db, "SELECT JSON_VALUE(data,'$.tags[0].tag') FROM am_facts WHERE JSON_VALUE(data,'$._id')='m1'")
    assert doc == "seating"

    # COSINE recall over live memories, excluding superseded facts (the labs' recall query)
    def recall(dim, k=1):
        return [r[0] for r in _rows(db,
            "SELECT id FROM am_memories WHERE session_id='s1' AND superseded_by IS NULL "
            "ORDER BY VECTOR_DISTANCE(embedding, TO_VECTOR(:q), COSINE) FETCH FIRST :k ROWS ONLY",
            {"q": emb(dim), "k": k})]
    assert recall(0) == ["m1"]        # nearest to the seating embedding
    assert recall(1) == ["m2"]        # nearest to the meal embedding

    # supersede m1 (a fact revision) — recall must stop returning it
    with db.cursor() as cur:
        cur.execute("UPDATE am_memories SET superseded_by='m3' WHERE id='m1'")
    db.commit()
    assert recall(0) == ["m2"]        # m1 is retired; the next-nearest live memory wins
    _drop(db, ("VIEW", "am_facts"), ("TABLE", "am_tags"), ("TABLE", "am_memories"))


def test_server_side_vector_embedding(db):
    # Server-side VECTOR_EMBEDDING needs a loaded ONNX model. The fixture pre-warms
    # the cache and loads it, so three states are distinct:
    #   loaded            -> run the real embedding assertion
    #   cache present but not loaded -> the load FAILED: a real defect, not a skip
    #   cold cache + offline (URL rotated/unreachable) -> the ONE sanctioned skip
    model = _scalar(db, "SELECT model_name FROM all_mining_models "
                        "WHERE mining_function='EMBEDDING' FETCH FIRST 1 ROWS ONLY")
    if not model:
        cache_zip = (Path(os.environ.get("XDG_CACHE_HOME",
                     str(Path.home() / ".cache"))) / "oracle-ai-dev"
                     / "all_MiniLM_L12_v2_augmented.zip")
        if cache_zip.is_file() and cache_zip.stat().st_size > 0:
            raise AssertionError(
                "ONNX model cached but not loaded — setup-embedding-model.sh failed "
                f"to install it (cache: {cache_zip}). This is an install defect, "
                "not a missing-model skip.")
        pytest.skip("cold ONNX cache and the rotating model URL is unreachable — run "
                    "setup-embedding-model.sh once online (or set ONNX_MODEL_URL) to "
                    "exercise server-side VECTOR_EMBEDDING")
    v = _scalar(db, f"SELECT VECTOR_EMBEDDING({model} USING 'hello world' AS DATA) FROM dual")
    assert v is not None


# --------------------------------------------------------------------------
# soda-dev — the SODA document API (create / insert / QBE find)
# --------------------------------------------------------------------------
def test_soda_qbe(db):
    # thin-mode driver -> exercise SODA through PL/SQL DBMS_SODA (create/insert/QBE find)
    with db.cursor() as cur:
        cnt, qbe = cur.var(int), cur.var(int)
        cur.execute("""
        DECLARE coll SODA_COLLECTION_T; s NUMBER; BEGIN
          BEGIN s := DBMS_SODA.drop_collection('sv_soda'); EXCEPTION WHEN OTHERS THEN NULL; END;
          coll := DBMS_SODA.create_collection('sv_soda');
          s := coll.insert_one(SODA_DOCUMENT_T(b_content => UTL_RAW.cast_to_raw('{"name":"widget","qty":5}')));
          s := coll.insert_one(SODA_DOCUMENT_T(b_content => UTL_RAW.cast_to_raw('{"name":"gadget","qty":9}')));
          :cnt := coll.find().count();
          :qbe := coll.find().filter('{"qty":{"$gte":6}}').count();
        END;""", {"cnt": cnt, "qbe": qbe})
        assert cnt.getvalue() == 2                # both inserted
        assert qbe.getvalue() == 1                # QBE: only qty>=6
    db.commit()                                   # commit inserts before dropping (else ORA-40626)
    with db.cursor() as cur:
        cur.execute("DECLARE s NUMBER; BEGIN s := DBMS_SODA.drop_collection('sv_soda'); END;")
    db.commit()


# --------------------------------------------------------------------------
# query-craft — SQL/PGQ property graph traversal
# --------------------------------------------------------------------------
def test_property_graph_traversal(db):
    _drop(db, ("PROPERTY GRAPH", "sv_org_g"), ("TABLE", "sv_emp"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_emp (emp_id NUMBER PRIMARY KEY, name VARCHAR2(40), manager_id NUMBER)")
        for i, (nm, mgr) in enumerate([("CEO", None), ("VP", 1), ("Mgr", 2)], start=1):
            cur.execute("INSERT INTO sv_emp VALUES (:1,:2,:3)", (i, nm, mgr))
        db.commit()
        cur.execute("CREATE PROPERTY GRAPH sv_org_g "
                    "VERTEX TABLES (sv_emp KEY (emp_id) PROPERTIES (emp_id, name)) "
                    "EDGE TABLES (sv_emp AS reports_to KEY (emp_id) "
                    "SOURCE KEY (emp_id) REFERENCES sv_emp (emp_id) "
                    "DESTINATION KEY (manager_id) REFERENCES sv_emp (emp_id) "
                    "PROPERTIES (emp_id))")
    db.commit()
    rows = _rows(db, "SELECT emp_name, mgr_name FROM GRAPH_TABLE (sv_org_g "
                     "MATCH (e)-[r IS reports_to]->(m) "
                     "COLUMNS (e.name AS emp_name, m.name AS mgr_name))")
    pairs = {(a, b) for a, b in rows}
    assert ("VP", "CEO") in pairs and ("Mgr", "VP") in pairs
    _drop(db, ("PROPERTY GRAPH", "sv_org_g"), ("TABLE", "sv_emp"))


# --------------------------------------------------------------------------
# oracle-data-modeling — hierarchy generation (CONNECT BY) runs a subtree
# --------------------------------------------------------------------------
def test_hierarchy_connect_by(db):
    from tooling.generate.sql import generate_connect_by
    org = {"entities": {"Employee": {"table": "sv_org", "pk": "emp_id",
           "columns": {"name": "name", "managerId": "manager_id"}}},
           "relationships": [{"from": "Employee", "to": "Employee", "from_key": "emp_id",
                              "to_key": "manager_id", "kind": "hierarchy"}], "projections": {}}
    _drop(db, ("TABLE", "sv_org"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_org (emp_id NUMBER PRIMARY KEY, name VARCHAR2(40), manager_id NUMBER)")
        for i, (nm, mgr) in enumerate([("CEO", None), ("VP", 1), ("Mgr", 2), ("IC", 3)], start=1):
            cur.execute("INSERT INTO sv_org VALUES (:1,:2,:3)", (i, nm, mgr))
    db.commit()
    q = {"root": "Employee", "returns": ["Employee.name"],
         "traversal": {"start": {"ref": "Employee.name", "op": "=", "value": "VP"}, "direction": "down"}}
    names = {r[0] for r in _rows(db, generate_connect_by(org, q))}
    assert names == {"VP", "Mgr", "IC"}     # the VP subtree
    _drop(db, ("TABLE", "sv_org"))


# --------------------------------------------------------------------------
# Write DML generation (write amplification path) runs and rolls back cleanly
# --------------------------------------------------------------------------
def test_write_dml_generation_runs(db):
    from tooling.generate.sql import generate_update
    model = {"entities": {
        "Order": {"table": "sv_o", "pk": "order_id", "columns": {"total": "total"}},
        "OrderItem": {"table": "sv_oi", "pk": "item_id", "columns": {"qty": "qty"}}},
        "relationships": [{"from": "Order", "to": "OrderItem", "from_key": "order_id",
                           "to_key": "order_id", "cardinality": "1:N"}], "projections": {}}
    _drop(db, ("TABLE", "sv_oi"), ("TABLE", "sv_o"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_o (order_id NUMBER PRIMARY KEY, total NUMBER)")
        cur.execute("CREATE TABLE sv_oi (item_id NUMBER PRIMARY KEY, order_id NUMBER, qty NUMBER)")
        cur.execute("INSERT INTO sv_o VALUES (1, 10)")
        cur.execute("INSERT INTO sv_oi VALUES (1, 1, 5)")
    db.commit()
    q = {"root": "Order", "returns": ["Order.total"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}
    upd = generate_update(model, q, "relational", "OrderItem.qty", delta=3)
    with db.cursor() as cur:
        cur.execute(upd)
    assert _scalar(db, "SELECT qty FROM sv_oi WHERE item_id = 1") == 8   # 5 + 3
    db.rollback()
    assert _scalar(db, "SELECT qty FROM sv_oi WHERE item_id = 1") == 5   # rolled back
    _drop(db, ("TABLE", "sv_oi"), ("TABLE", "sv_o"))


# --------------------------------------------------------------------------
# The cost matrix, live — compare measures shapes and elects a design
# --------------------------------------------------------------------------
def test_compare_cost_matrix_live(db):
    from tooling.optimize.compare import compare
    _drop(db, ("TABLE", "sv_idx"), ("TABLE", "sv_noidx"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_idx (k NUMBER PRIMARY KEY, v NUMBER)")
        cur.execute("CREATE TABLE sv_noidx (k NUMBER, v NUMBER)")
        cur.executemany("INSERT INTO sv_idx VALUES (:1,:2)", [(i, i) for i in range(1, 3000)])
        cur.executemany("INSERT INTO sv_noidx VALUES (:1,:2)", [(i, i) for i in range(1, 3000)])
    db.commit()

    def lr(sql):
        b = _scalar(db, "SELECT value FROM v$mystat s JOIN v$statname n ON n.statistic#=s.statistic# WHERE n.name='consistent gets'")
        for _ in range(10):
            _rows(db, sql)
        return (_scalar(db, "SELECT value FROM v$mystat s JOIN v$statname n ON n.statistic#=s.statistic# WHERE n.name='consistent gets'") - b) / 10
    read = {"lookup": {"indexed": lr("SELECT v FROM sv_idx WHERE k=1500"),
                       "scan": lr("SELECT v FROM sv_noidx WHERE k=1500")}}
    model = {"entities": {"X": {"table": "sv_idx", "pk": "k", "columns": {"v": "v"}}},
             "relationships": [], "projections": {}}
    r = compare(model,
                {"lookup": {"read_rate": 1000, "write_rate": 0,
                            "query": {"root": "X", "returns": ["X.v"],
                                      "predicates": [{"ref": "X.k", "op": "=", "value": 1}]}}},
                read, read)
    # writes are first-class rows; the decision engine ran on the live matrix
    assert r["decision"] is not None and r["decision"]["chosen"] == "indexed"
    _drop(db, ("TABLE", "sv_idx"), ("TABLE", "sv_noidx"))


# --------------------------------------------------------------------------
# query-tuning — capture an execution plan (EXPLAIN PLAN + DBMS_XPLAN): the
# baseline step of the measure-driven tuning loop.
# --------------------------------------------------------------------------
def test_execution_plan_capture(db):
    _drop(db, ("TABLE", "sv_plan"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sv_plan (id NUMBER PRIMARY KEY, v NUMBER)")
        cur.executemany("INSERT INTO sv_plan VALUES (:1,:2)", [(i, i) for i in range(1, 2000)])
    db.commit()
    with db.cursor() as cur:
        cur.execute("BEGIN DBMS_STATS.GATHER_TABLE_STATS(USER,'SV_PLAN'); END;")
        cur.execute("EXPLAIN PLAN FOR SELECT v FROM sv_plan WHERE id = 500")
    plan = "\n".join(r[0] for r in _rows(db, "SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY())"))
    # the primary-key equality predicate plans as an index access on SV_PLAN, not a full scan
    assert "SV_PLAN" in plan and "INDEX" in plan and "FULL" not in plan
    _drop(db, ("TABLE", "sv_plan"))


# --------------------------------------------------------------------------
# mongodb-api-dev — the MongoDB-compatible API, live (ORDS-enabled schema)
# --------------------------------------------------------------------------
def test_mongo_api_crud(db):
    import socket
    pymongo = pytest.importorskip("pymongo")
    from pymongo.errors import PyMongoError
    from live_helpers import ORDS_CONTAINER, ords_logtail, wait_ords_ready

    # The one honest skip: a pre-provisioned db-ONLY container (the demo workflow)
    # has no ORDS, so the Mongo API genuinely does not exist. When the session
    # fixture booted the db-ords stack, ORDS_CONTAINER is running and the API MUST
    # work — every failure below is then a real defect, asserted, not skipped.
    running = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", ORDS_CONTAINER],
        capture_output=True, text=True).stdout.strip()
    if running != "true":
        pytest.skip("no ORDS container — reusing a pre-provisioned db-only container; "
                    "bring up the db-ords profile to exercise the Mongo API")

    # The fixture yields on DB-healthy without blocking DB-only tests on ORDS; this
    # is the point where the Mongo test itself waits for ORDS to compile VALID.
    wait_ords_ready(os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db"))

    host = os.environ.get("ORACLE_AI_DEV_MONGO_HOST", "localhost")
    port = int(os.environ.get("ORACLE_AI_DEV_MONGO_PORT", "27017"))
    # ORDS is now VALID; the mapped port must open.
    for _ in range(24):
        try:
            socket.create_connection((host, port), timeout=3).close()
            break
        except OSError:
            time.sleep(5)
    else:
        raise AssertionError(
            f"Mongo API port {host}:{port} never opened though ORDS is running.\n"
            + ords_logtail())
    # ORDS-enable this schema as its owner (idempotent). Right after the ORDS package
    # compiles VALID it is not yet fully finalized — ENABLE_SCHEMA can transiently fail
    # to resolve (PLS-00201) or raise ORA-01403, so retry until it takes (the same
    # finalization window the standalone Mongo tests guard against).
    last_exc = None
    for _ in range(24):
        try:
            with db.cursor() as cur:
                cur.execute("BEGIN ORDS.ENABLE_SCHEMA; COMMIT; END;")
            last_exc = None
            break
        except Exception as exc:                       # noqa: BLE001 — transient ORDS finalization
            last_exc = exc
            time.sleep(5)
    assert last_exc is None, f"ORDS.ENABLE_SCHEMA never succeeded:\n{last_exc}\n{ords_logtail()}"

    base = (f"mongodb://{USER}:{PW}@{host}:{port}/{USER}?"
            "authMechanism=PLAIN&authSource=$external&retryWrites=false&loadBalanced=true")
    override = os.environ.get("ORACLE_AI_DEV_MONGO_URI")
    # the shipped db-ords profile serves TLS (self-signed); some labs serve plaintext — try both
    candidates = [override] if override else [
        base + "&tls=true&tlsAllowInvalidCertificates=true",
        base + "&tls=false"]
    # ORDS does not surface a just-enabled schema to the Mongo API instantly — it
    # refreshes its mapping on a cycle, so the first pings fail with "schema is
    # enabled" guidance even though ENABLE_SCHEMA already succeeded. Retry the whole
    # handshake for ~2 min; a persistent failure past that is a real defect.
    client, errs = None, []
    for _ in range(24):
        for uri in candidates:
            c = pymongo.MongoClient(uri, serverSelectionTimeoutMS=6000)
            try:
                c.admin.command("ping")
                client = c
                break
            except PyMongoError as exc:
                errs.append(str(exc))
                c.close()
        if client is not None:
            break
        time.sleep(5)
    assert client is not None, (
        "Mongo API never authenticated the enabled schema within ~2 min:\n"
        + "\n".join(errs[-4:]) + "\n" + ords_logtail())

    try:
        coll = client[USER]["sv_mongo"]
        coll.delete_many({})
        coll.insert_one({"_id": 1, "name": "widget", "qty": 5})
        coll.insert_one({"_id": 2, "name": "gadget", "qty": 9})
        assert coll.find_one({"_id": 1})["qty"] == 5
        assert coll.count_documents({"qty": {"$gte": 6}}) == 1        # QBE over the API
        assert coll.update_one({"_id": 1}, {"$set": {"qty": 7}}).modified_count == 1
        assert coll.find_one({"_id": 1})["qty"] == 7
        coll.drop()
    finally:
        client.close()

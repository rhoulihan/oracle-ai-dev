# Copyright (c) 2026 Oracle and/or its affiliates.
"""Pattern-catalog empirical backing — gated live tests (spec §4.1/§4.4).

Grouped mini-domains, one per realization family, each proving that *every*
generated realization of the pattern deploys, runs, and returns consistent results
on a live 26ai, and that the ranked options name the generic pattern. Together the
five domains cover all 17 catalog patterns. No realization is favoured — the winner
varies with the read/write knob.

Gated: ORACLE_AI_DEV_LIVE=1 with a reachable DB (env ORACLE_AI_DEV_CONTAINER /
ORACLE_AI_DEV_DSN / ORACLE_AI_DEV_PDB; defaults oracle-ai-dev-db / localhost:1521/
FREEPDB1 / FREEPDB1).
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.shared_container,
    pytest.mark.skipif(
        os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
        reason="set ORACLE_AI_DEV_LIVE=1 (with a reachable 26ai) to run the pattern-catalog live tests"),
]

CONTAINER = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
DSN = os.environ.get("ORACLE_AI_DEV_DSN", "localhost:1521/FREEPDB1")
PDB = os.environ.get("ORACLE_AI_DEV_PDB", "FREEPDB1")
USER, PW = "patval", "Patval_pw_12345"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "patterns"

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
    # stdout+stderr: a failed `docker exec` (e.g. container absent) must surface in
    # fixture assertions instead of reading as an empty, message-less output.
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-lc",
                        "sqlplus -S -L / as sysdba"], input=sql,
                       capture_output=True, text=True, timeout=90)
    return p.stdout + p.stderr


@pytest.fixture(scope="module")
def db(live_container):
    import oracledb
    boot = (f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER +
            f"CREATE USER {USER} IDENTIFIED BY {PW} DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS;\n"
            f"GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, CREATE SEQUENCE, "
            f"CREATE PROPERTY GRAPH, RESOURCE, SODA_APP, SELECT_CATALOG_ROLE TO {USER};\n")
    out = _sysdba(boot)
    assert "created" in out.lower() and "ORA-01920" not in out, out
    conn = oracledb.connect(user=USER, password=PW, dsn=DSN)
    conn.call_timeout = 30000
    yield conn
    conn.close()
    _sysdba(f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER)


def _model(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _exec(conn, ddl):
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


def _rows(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def _drop(conn, *objs):
    for kind, name in objs:
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP {kind} {name}" + (" PURGE" if kind == "TABLE" else ""))
        except Exception:
            pass
    conn.commit()


# --------------------------------------------------------------------------
# Tree / Hierarchy mini-domain — Adjacency (CONNECT BY), Materialized Path
# (recursive CTE), and Graph (GRAPH_TABLE) all agree on the same subtree.
# --------------------------------------------------------------------------
def test_tree_domain_all_realizations_agree(db):
    from tooling.generate.sql import (generate_candidates, generate_property_graph_ddl)
    from tooling.optimize.equivalence import results_equivalent
    from tooling.optimize.patterns import pattern_name
    model = _model("org_chart")
    _drop(db, ("PROPERTY GRAPH", "employee_graph"), ("TABLE", "employee"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE employee (emp_id NUMBER PRIMARY KEY, name VARCHAR2(120), "
                    "manager_id NUMBER REFERENCES employee(emp_id))")
        for i, (nm, mgr) in enumerate([("CEO", None), ("VP Eng", 1), ("VP Sales", 1),
                                       ("Eng Mgr", 2), ("Engineer", 4), ("Sales Rep", 3)], 1):
            cur.execute("INSERT INTO employee VALUES (:1,:2,:3)", (i, nm, mgr))
    db.commit()
    _exec(db, generate_property_graph_ddl(model, "Employee"))

    q = {"root": "Employee", "returns": ["Employee.name"],
         "traversal": {"start": {"ref": "Employee.name", "op": "=", "value": "CEO"}, "direction": "down"}}
    cands = generate_candidates(model, q)
    assert set(cands) == {"connect_by", "recursive_cte", "graph_table"}
    # Compare the projected descendant set (the returns); CONNECT BY / recursive CTE
    # carry an extra realization-specific `lvl` column, so compare on the name column.
    named = {shape: sorted(r[0] for r in _rows(db, sql)) for shape, sql in cands.items()}
    base = named["connect_by"]
    assert len(base) == 6                              # the whole CEO subtree
    for shape, names in named.items():
        assert names == base, f"{shape} disagrees: {names} != {base}"
    assert results_equivalent([(n,) for n in named["graph_table"]],
                              [(n,) for n in base])    # order/type-invariant, too
    # each realization names a Tree pattern; the graph realization names the Graph variant
    assert "Tree" in pattern_name("connect_by", q)
    assert pattern_name("graph_table", q) == "Tree / Hierarchy — Graph"
    _drop(db, ("PROPERTY GRAPH", "employee_graph"), ("TABLE", "employee"))


# --------------------------------------------------------------------------
# Bucket mini-domain — time-series: every read/write realization runs; the
# bucket append names "Bucket"; the ranked options are pattern-named and the
# winner flips with the read/write knob.
# --------------------------------------------------------------------------
def test_bucket_domain_realizations_and_ranking(db):
    from tooling.generate.sql import generate_candidates, generate_array_append
    from tooling.optimize.analyze import recommend_design_options
    from tooling.optimize.patterns import pattern_name
    model = _model("timeseries_sensor")
    _drop(db, ("TABLE", "readings"), ("TABLE", "sensors"), ("TABLE", "sensor_docs"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE sensors (sensor_id NUMBER PRIMARY KEY, location VARCHAR2(60))")
        cur.execute("CREATE TABLE readings (reading_id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
                    "sensor_id NUMBER REFERENCES sensors(sensor_id), ts VARCHAR2(30), val NUMBER)")
        cur.execute("CREATE INDEX readings_sensor_ix ON readings(sensor_id)")
        cur.execute("CREATE JSON COLLECTION TABLE sensor_docs")
        cur.execute("INSERT INTO sensors VALUES (1, 'roof')")
        for ts, v in (("t1", 21), ("t2", 22), ("t3", 23)):
            cur.execute("INSERT INTO readings (sensor_id, ts, val) VALUES (1, :1, :2)", (ts, v))
        cur.execute("INSERT INTO sensor_docs (data) VALUES (JSON('"
                    '{"_id":1,"location":"roof","readings":[{"ts":"t1","val":21},{"ts":"t2","val":22},{"ts":"t3","val":23}]}'
                    "'))")
    db.commit()

    # READ: get sensor 1's readings — every generated realization runs and returns data.
    read = {"root": "Sensor", "returns": ["Reading.val"],
            "predicates": [{"ref": "Sensor.sensor_id", "op": "=", "value": 1}]}
    cands = generate_candidates(model, read)
    assert "relational" in cands and "document" in cands       # + sql_view fallback
    for shape, sql in cands.items():
        assert _rows(db, sql), f"read realization {shape} returned nothing"

    # WRITE (append a reading): relational inserts a child row; document rewrites the
    # bucket. Both run (rolled back). The append names the Bucket pattern.
    wq = {"root": "Sensor", "returns": ["Sensor.sensor_id"],
          "predicates": [{"ref": "Sensor.sensor_id", "op": "=", "value": 1}], "write": "array_append"}
    for shape in ("relational", "document"):
        sql = generate_array_append(model, wq, shape, "$.readings", {"ts": "t4", "val": 24})
        with db.cursor() as cur:
            cur.execute(sql)
        db.rollback()
    assert pattern_name("document", wq) == "Bucket"

    # RANK: fed representative measured costs, the winner flips with the knob and each
    # option is named. Bucket read is co-located (cheap); its append rewrites the doc.
    rm = {"bucket": {"relational": 6, "document": 2}}
    wmeas = {"bucket": {"relational": 4, "document": 40}}
    read_heavy = recommend_design_options(rm, wmeas, {"bucket": 100}, {"bucket": 1}, wq, model)
    write_heavy = recommend_design_options(rm, wmeas, {"bucket": 1}, {"bucket": 100}, wq, model)
    assert all(o.get("pattern") for o in read_heavy)           # options are pattern-named
    assert read_heavy[0]["assignment"]["bucket"] == "document"   # reads dominate -> bucket doc
    assert write_heavy[0]["assignment"]["bucket"] == "relational"  # writes dominate -> normalized
    _drop(db, ("TABLE", "readings"), ("TABLE", "sensors"), ("TABLE", "sensor_docs"))


# --------------------------------------------------------------------------
# Product-catalog mini-domain — Attribute (uniform array search + multivalue
# index), Computed (derived value -> SQL view), Approximation (counter write).
# --------------------------------------------------------------------------
def test_catalog_domain_attribute_computed_approximation(db):
    from tooling.generate.sql import generate_document, generate_sql_view
    from tooling.optimize.patterns import pattern_name
    model = _model("product_catalog")
    _drop(db, ("TABLE", "products"), ("TABLE", "product_docs"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE products (product_id NUMBER PRIMARY KEY, name VARCHAR2(60), "
                    "price NUMBER, views NUMBER DEFAULT 0)")
        cur.execute("INSERT INTO products VALUES (1, 'widget', 10, 0)")
        cur.execute("INSERT INTO products VALUES (2, 'gadget', 20, 0)")
        cur.execute("CREATE JSON COLLECTION TABLE product_docs")
        cur.execute("""INSERT INTO product_docs (data) VALUES (JSON('{"_id":1,"name":"widget","price":10,"tags":["red","small"]}'))""")
        cur.execute("""INSERT INTO product_docs (data) VALUES (JSON('{"_id":2,"name":"gadget","price":20,"tags":["blue"]}'))""")
    db.commit()
    # the Attribute realization's index: a multivalue index over the tag array
    try:
        with db.cursor() as cur:
            cur.execute("CREATE MULTIVALUE INDEX prod_tags_ix ON product_docs t (t.data.tags[*].string())")
    except Exception:
        pass

    # ATTRIBUTE — uniform search over the attribute array (array-contains via JSON_EXISTS)
    aq = {"root": "Product", "returns": ["Product.name"],
          "predicates": [{"ref": "Product.tags", "op": "=", "value": "red"}], "attribute_kv": True}
    hits = _rows(db, generate_document(model, aq))
    assert len(hits) == 1, f"expected the one red-tagged product, got {hits}"
    assert pattern_name("document", aq) == "Attribute"

    # COMPUTED — a derived tax-inclusive price → read-only SQL view (JSON_OBJECT-wrapped)
    cq = {"root": "Product", "returns": ["Product.name"],
          "computed": [{"name": "price_tax", "expr": "price * 1.1"}],
          "predicates": [{"ref": "Product.product_id", "op": "=", "value": 1}]}
    doc = _rows(db, generate_sql_view(model, cq))
    assert doc and "price_tax" in str(doc[0][0])
    assert pattern_name("sql_view", cq) == "Computed / SQL View"

    # APPROXIMATION — a counter increment (rolled back); the write names Approximation
    with db.cursor() as cur:
        cur.execute("UPDATE products SET views = views + 1 WHERE product_id = 1")
        assert _rows(db, "SELECT views FROM products WHERE product_id = 1")[0][0] == 1
    db.rollback()
    assert pattern_name("relational", {"returns": ["Product.views"], "write": "counter_increment"}) == "Approximation"
    _drop(db, ("TABLE", "products"), ("TABLE", "product_docs"))


# --------------------------------------------------------------------------
# Orders/customer mini-domain — Embedded Document, Subset (top-n), Extended
# Reference (embed a referenced subset), Pre-allocation (fixed-slot update).
# --------------------------------------------------------------------------
def test_orders_domain_embedded_subset_extref_prealloc(db):
    from tooling.generate.sql import (generate_document, generate_relational,
                                      generate_multi_field_update)
    from tooling.optimize.patterns import pattern_name
    model = _model("orders_customer")
    _drop(db, ("TABLE", "orders"), ("TABLE", "customers"), ("TABLE", "order_docs"))
    with db.cursor() as cur:
        cur.execute("CREATE TABLE customers (customer_id NUMBER PRIMARY KEY, name VARCHAR2(60))")
        cur.execute("CREATE TABLE orders (order_id NUMBER PRIMARY KEY, customer_id NUMBER "
                    "REFERENCES customers(customer_id), total NUMBER, cust_name VARCHAR2(60))")
        cur.execute("INSERT INTO customers VALUES (1, 'Alice')")
        for oid, tot in ((1, 100), (2, 200), (3, 300)):
            cur.execute("INSERT INTO orders VALUES (:1, 1, :2, 'Alice')", (oid, tot))
        cur.execute("CREATE JSON COLLECTION TABLE order_docs")
        cur.execute("INSERT INTO order_docs (data) VALUES (JSON('"
                    '{"_id":1,"customer_id":1,"total":100,"cust_name":"Alice","slots":[0,0,0]}'
                    "'))")
    db.commit()

    # EMBEDDED DOCUMENT — read the aggregate order document.
    eq = {"root": "Order", "returns": ["Order.total"],
          "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}
    assert _rows(db, generate_document(model, eq))
    assert pattern_name("document", eq) == "Embedded Document"

    # SUBSET — top-n most-recent orders for a customer (FETCH FIRST).
    sq = {"root": "Customer", "returns": ["Order.total"],
          "predicates": [{"ref": "Customer.customer_id", "op": "=", "value": 1}],
          "order_by": [{"ref": "Order.order_id", "dir": "DESC"}], "limit": 2}
    top = _rows(db, generate_relational(model, sq))
    assert len(top) == 2 and top[0][0] == 300           # the 2 most-recent orders
    assert pattern_name("document", {"returns": ["Order.total"], "limit": 2}) == "Subset"

    # EXTENDED REFERENCE — the order embeds a subset of the referenced customer.
    xq = {"root": "Order", "returns": ["Order.custName"],
          "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}], "extended_reference": True}
    assert _rows(db, generate_document(model, xq))
    assert pattern_name("document", xq) == "Extended Reference"

    # PRE-ALLOCATION — update a fixed slot in the pre-sized array (rolled back).
    pq = {"root": "Order", "returns": ["Order.total"],
          "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}], "write": "slot_update"}
    with db.cursor() as cur:
        cur.execute(generate_multi_field_update(model, pq, "document", [{"path": "$.slots[0]", "expr": "99"}]))
    assert _rows(db, "SELECT JSON_VALUE(data,'$.slots[0]' RETURNING NUMBER) FROM order_docs "
                     "WHERE JSON_VALUE(data,'$._id' RETURNING NUMBER)=1")[0][0] == 99
    db.rollback()
    assert pattern_name("document", pq) == "Pre-allocation"
    _drop(db, ("TABLE", "orders"), ("TABLE", "customers"), ("TABLE", "order_docs"))


# --------------------------------------------------------------------------
# Events-log mini-domain — Polymorphic (discriminator), Schema Versioning,
# Outlier, Document Versioning (versions[] — no Flashback dependency).
# --------------------------------------------------------------------------
def test_events_domain_polymorphic_versioning_outlier(db):
    from tooling.generate.sql import generate_document
    from tooling.optimize.patterns import pattern_name
    model = _model("events_log")
    _drop(db, ("TABLE", "event_docs"))
    with db.cursor() as cur:
        cur.execute("CREATE JSON COLLECTION TABLE event_docs")
        cur.execute("INSERT INTO event_docs (data) VALUES (JSON('"
                    '{"_id":1,"type":"click","schema_version":2,"is_outlier":false,'
                    '"versions":[{"v":1},{"v":2}],"payload":"a"}'
                    "'))")
        cur.execute("INSERT INTO event_docs (data) VALUES (JSON('"
                    '{"_id":2,"type":"purchase","schema_version":1,"is_outlier":true,'
                    '"versions":[{"v":1}],"payload":"b"}'
                    "'))")
    db.commit()

    # Each pattern is a document read distinguished by the field it touches; every
    # realization runs live and names the corresponding generic pattern.
    poly = {"root": "Event", "returns": ["Event.payload"],
            "predicates": [{"ref": "Event.type", "op": "=", "value": "click"}]}
    assert len(_rows(db, generate_document(model, poly))) == 1     # only the click events
    assert pattern_name("document", poly, model) == "Polymorphic"

    for prop, expected in [("schema_version", "Schema Versioning"),
                           ("is_outlier", "Outlier"),
                           ("versions", "Document Versioning")]:
        q = {"root": "Event", "returns": [f"Event.{prop}"],
             "predicates": [{"ref": "Event.event_id", "op": "=", "value": 1}]}
        assert _rows(db, generate_document(model, q))              # the record reads back
        assert pattern_name("document", q, model) == expected
    _drop(db, ("TABLE", "event_docs"))

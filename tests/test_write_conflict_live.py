# Copyright (c) 2026 Oracle and/or its affiliates.
"""Gate 16's own CHECK, run for real: a deliberately stale etag raises
ORA-42699 through the GENERATED data layer, and a stripped _metadata is
refused. A concurrency test that never sees ORA-42699 proves nothing — this
one sees it on a live 26ai, through the code users will actually run.

Named *_live.py (not test_live_*): session-stack riders must collect after the
per-module compose booters — see test_plancheck_live.py.
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
        reason="set ORACLE_AI_DEV_LIVE=1 (with a reachable 26ai) to run the etag round-trip test"),
]

CONTAINER = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
DSN = os.environ.get("ORACLE_AI_DEV_DSN", "localhost:1521/FREEPDB1")
PDB = os.environ.get("ORACLE_AI_DEV_PDB", "FREEPDB1")
USER, PW = "etagrt", "Etagrt_pw_12345"

_DROP_USER = (
    "BEGIN\n"
    f"  BEGIN EXECUTE IMMEDIATE 'DROP USER {USER} CASCADE'; EXCEPTION WHEN OTHERS THEN NULL; END;\n"
    "END;\n/\n")


def _sysdba(sql):
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-lc",
                        "sqlplus -S -L / as sysdba"], input=sql,
                       capture_output=True, text=True, timeout=90)
    return p.stdout + p.stderr


@pytest.fixture(scope="module")
def repo_ns(live_container):
    """A live connection + the generated repository module, schema deployed."""
    import oracledb
    boot = (f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER +
            f"CREATE USER {USER} IDENTIFIED BY {PW} DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS;\n"
            f"GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, RESOURCE TO {USER};\n")
    out = _sysdba(boot)
    assert "created" in out.lower() and "ORA-01920" not in out, out
    conn = oracledb.connect(user=USER, password=PW, dsn=DSN)
    conn.call_timeout = 30000

    from tooling.datalayer.platforms import render_all
    model = json.loads(Path("tests/fixtures/restaurant_model.json").read_text())
    spec = {"model": model, "platforms": ["python"], "patterns": [
        {"name": "get_order", "shape": "duality",
         "query": {"root": "Order", "returns": ["Order.total"],
                   "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}}]}
    files = render_all(spec)
    ns = {}
    exec(compile(files["repository.py"], "repository.py", "exec"), ns)
    assert ns["ensure_schema"](conn) in (True, False)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM order_item")
        cur.execute("DELETE FROM orders")
        cur.execute("INSERT INTO orders (order_id, total) VALUES (1, 10)")
    conn.commit()
    yield conn, ns
    conn.close()
    _sysdba(f"ALTER SESSION SET CONTAINER = {PDB};\n" + _DROP_USER)


def test_etag_round_trips_and_a_stale_write_conflicts(repo_ns):
    conn, ns = repo_ns
    doc = ns["get_order_doc"](conn, 1)
    assert doc and "_metadata" in doc, "the read must include _metadata"
    etag_before = doc["_metadata"]["etag"]

    doc["total"] = 99
    assert ns["replace_order_doc"](conn, doc) == 1
    fresh = ns["get_order_doc"](conn, 1)
    assert fresh["total"] == 99
    assert fresh["_metadata"]["etag"] != etag_before, "a write must move the etag"

    # the STALE write: the pre-write document carries the superseded etag
    doc["total"] = 42
    with pytest.raises(ns["StaleDocumentError"]):
        ns["replace_order_doc"](conn, doc)


def test_a_stripped_metadata_is_refused_not_silently_unchecked(repo_ns):
    conn, ns = repo_ns
    doc = ns["get_order_doc"](conn, 1)
    del doc["_metadata"]
    with pytest.raises(ValueError):
        ns["replace_order_doc"](conn, doc)

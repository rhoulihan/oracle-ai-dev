import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from live_helpers import ords_logtail, wait_db_login, wait_ords_ready


def _port_open(host, port, timeout=2):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live Mongo-API smoke test",
)

CONTAINER_DB = "oracle-ai-dev-db"
ORDS_HOST = "oracle-ai-dev-ords"  # container name on the compose network
PROJ = "oadmongo"
# lab-oracle holds host 27017/8181, so map alternate host ports for this stack.
ENV = {**os.environ, "DB_HOST_PORT": "1598", "MONGO_PORT": "27117", "ORDS_HTTP_PORT": "8099"}

# Create the Mongo user as SYSTEM (needs no ORDS).
CREATE_USER = """
DECLARE n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM all_users WHERE username = 'MONGO_DEV';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER mongo_dev IDENTIFIED BY Mongo_pw_12345 '
      || 'DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS';
    EXECUTE IMMEDIATE 'GRANT CONNECT, RESOURCE, SODA_APP TO mongo_dev';
  END IF;
END;
/
"""
# Enable ORDS for the schema AS ITS OWNER — running it as SYSTEM fails with
# ORA-06598 (insufficient INHERIT PRIVILEGES on ORDS_METADATA.ORDS). The owner
# enabling its own schema is the idiomatic, working path.
ENABLE_SCHEMA = """
BEGIN ORDS.ENABLE_SCHEMA(p_enabled => TRUE); COMMIT; END;
/
"""
# Readiness: ORDS is installed once its package is VALID in the DB.
ORDS_READY = ("SET HEAD OFF PAGES 0 FEED OFF\n"
              "SELECT status FROM all_objects "
              "WHERE object_name='ORDS' AND object_type='PACKAGE';")
URI = ("mongodb://mongo_dev:Mongo_pw_12345@" + ORDS_HOST + ":27017/mongo_dev?"
       "authMechanism=PLAIN&authSource=$external&tls=true&retryWrites=false&loadBalanced=true")


def _sql(text, user="system/devpassword"):
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER_DB, "sqlplus", "-S",
         f"{user}@localhost:1521/FREEPDB1"],
        input=text, capture_output=True, text=True).stdout


def _mongosh(eval_js):
    return subprocess.run(
        ["docker", "run", "--rm", "--network", f"{PROJ}_default", "mongo:8.2",
         "mongosh", URI, "--tlsAllowInvalidCertificates", "--quiet", "--eval", eval_js],
        capture_output=True, text=True)


@pytest.mark.live
def test_mongo_api_crud_roundtrip(repo_root: Path):
    compose = str(repo_root / "assets/compose/db-ords.compose.yml")
    subprocess.run(["docker", "compose", "-p", PROJ, "-f", compose, "up", "-d"],
                   check=True, env=ENV)
    try:
        for _ in range(72):
            h = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER_DB],
                               capture_output=True, text=True).stdout.strip()
            if h == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db did not become healthy")

        # Create the Mongo user (SYSTEM), then wait for ORDS to install+compile in
        # the DB (minutes on first boot), then enable the schema AS ITS OWNER.
        # Healthy is not logged-in: wait out the first-boot ORA-01017 window.
        wait_db_login(CONTAINER_DB)
        assert "ORA-" not in _sql(CREATE_USER), "failed to create mongo_dev"
        wait_ords_ready(CONTAINER_DB, timeout=600)

        # Retry: ORDS.ENABLE_SCHEMA can raise a transient ORA-01403 while ORDS
        # finishes populating its metadata right after the package compiles.
        out = ""
        for _ in range(24):
            out = _sql(ENABLE_SCHEMA, user="mongo_dev/Mongo_pw_12345")
            if "successfully" in out:
                break
            time.sleep(5)
        assert "successfully" in out, f"ENABLE_SCHEMA failed:\n{out}"

        # Wait for the Mongo listener to open on the mapped host port.
        for _ in range(60):
            if _port_open("localhost", ENV["MONGO_PORT"]):
                break
            time.sleep(5)
        else:
            raise AssertionError(
                "Mongo listener never opened on "
                f"localhost:{ENV['MONGO_PORT']} after ENABLE_SCHEMA succeeded.\n"
                + ords_logtail())

        # CRUD round-trip via mongosh.
        last = ""
        for _ in range(24):
            r = _mongosh('db.t.insertOne({x:1}); print("COUNT:" + db.t.countDocuments({}));')
            last = (r.stdout + r.stderr)[-800:]
            if "COUNT:1" in r.stdout:
                break
            time.sleep(5)
        assert "COUNT:1" in last, f"Mongo CRUD round-trip never completed:\n{last}"
    finally:
        subprocess.run(["docker", "compose", "-p", PROJ, "-f", compose, "down", "-v"], env=ENV)

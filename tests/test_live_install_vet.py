import os
import subprocess
import time
from pathlib import Path

import pytest

from live_helpers import wait_db_login, wait_ords_ready

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live install-vetting test",
)

DB = "oracle-ai-dev-db"
ORDS = "oracle-ai-dev-ords"
PROJ = "oadvet"
ENV = {**os.environ, "DB_HOST_PORT": "1595", "MONGO_PORT": "27119", "ORDS_HTTP_PORT": "8096"}

CREATE_USERS = """
DECLARE
  PROCEDURE mk(u VARCHAR2, extra VARCHAR2) IS n INTEGER; BEGIN
    SELECT COUNT(*) INTO n FROM all_users WHERE username = UPPER(u);
    IF n = 0 THEN
      EXECUTE IMMEDIATE 'CREATE USER '||u||' IDENTIFIED BY Vet_pw_12345 '
        ||'DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS';
      EXECUTE IMMEDIATE 'GRANT CREATE SESSION'||extra||' TO '||u;
    END IF;
  END;
BEGIN
  mk('plugin_dev', '');
  mk('mongo_dev', ', CONNECT, RESOURCE, SODA_APP');
END;
/
"""
ENABLE_MONGO = "BEGIN ORDS.ENABLE_SCHEMA(p_enabled => TRUE); COMMIT; END;\n/\n"
ORDS_READY = ("SET HEAD OFF PAGES 0 FEED OFF\n"
              "SELECT status FROM all_objects WHERE object_name='ORDS' AND object_type='PACKAGE';")


def _sql(text, user="system/devpassword"):
    p = subprocess.run(["docker", "exec", "-i", DB, "sqlplus", "-S",
                        f"{user}@localhost:1521/FREEPDB1"],
                       input=text, capture_output=True, text=True)
    return p.stdout + p.stderr


def _mongosh_on_net(uri, js):
    return subprocess.run(
        ["docker", "run", "--rm", "--network", f"{PROJ}_default", "mongo:8.2",
         "mongosh", uri, "--tlsAllowInvalidCertificates", "--quiet", "--eval", js],
        capture_output=True, text=True)


@pytest.mark.live
def test_install_is_complete_and_all_apis_reachable(repo_root: Path, tmp_path):
    compose = str(repo_root / "assets/compose/db-ords.compose.yml")
    subprocess.run(["docker", "compose", "-p", PROJ, "-f", compose, "up", "-d"], check=True, env=ENV)
    try:
        for _ in range(72):
            if subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", DB],
                              capture_output=True, text=True).stdout.strip() == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db not healthy")

        # Configure: create users, wait for ORDS, enable the Mongo schema as owner.
        # Healthy is not logged-in: first-boot init may still be setting the
        # password on a slow runner (ORA-01017 window) — wait for a real login.
        wait_db_login(DB)
        assert "ORA-" not in _sql(CREATE_USERS), "user creation failed"
        wait_ords_ready(DB, timeout=600)
        # ORDS.ENABLE_SCHEMA can raise ORA-01403 transiently while ORDS finishes
        # populating its metadata after the package compiles — retry until it takes.
        enabled = ""
        for _ in range(24):  # up to ~2 min
            enabled = _sql(ENABLE_MONGO, user="mongo_dev/Vet_pw_12345")
            if "successfully" in enabled:
                break
            time.sleep(5)
        assert "successfully" in enabled, f"ENABLE_SCHEMA never succeeded:\n{enabled}"

        # (1) SQL API reachable.
        sql_out = _sql("SET HEAD OFF PAGES 0 FEED OFF\nSELECT 'SQLOK:'||1 FROM dual;",
                       user="plugin_dev/Vet_pw_12345")
        assert "SQLOK:1" in sql_out, f"SQL not reachable:\n{sql_out}"

        # (2) MongoDB API reachable (CRUD).
        uri = ("mongodb://mongo_dev:Vet_pw_12345@" + ORDS + ":27017/mongo_dev?"
               "authMechanism=PLAIN&authSource=$external&tls=true&retryWrites=false&loadBalanced=true")
        crud = None
        for _ in range(24):
            r = _mongosh_on_net(uri, 'db.t.insertOne({x:1}); print("MONGOOK:"+db.t.countDocuments({}));')
            if "MONGOOK:1" in r.stdout:
                crud = r
                break
            time.sleep(5)
        assert crud is not None, "Mongo API CRUD did not complete"

        # (3) REST (ORDS) reachable on the mapped host port.
        code = subprocess.run(
            ["bash", "-c", f'curl -sk -o /dev/null -w "%{{http_code}}" '
                           f'http://localhost:{ENV["ORDS_HTTP_PORT"]}/ords/'],
            capture_output=True, text=True).stdout.strip()
        assert code and code != "000", f"ORDS REST not reachable (curl code={code!r})"

        # (4) Connection kit delivered + a generated snippet connects.
        kit = tmp_path / "kit"
        genenv = {**os.environ, "HOST": ORDS, "MONGO_PORT": "27017",
                  "DB_USER": "mongo_dev", "DB_PASSWORD": "Vet_pw_12345",
                  "PORT": "1521", "SERVICE": "FREEPDB1"}
        g = subprocess.run(["bash", str(repo_root / "scripts/gen-connection-kit.sh"), str(kit)],
                           capture_output=True, text=True, env=genenv)
        assert g.returncode == 0, g.stdout + g.stderr
        assert (kit / "README.md").is_file() and (kit / "MANIFEST").is_file()
        # run the GENERATED mongosh snippet inside a mongo container on the net
        gen = subprocess.run(
            ["docker", "run", "--rm", "--network", f"{PROJ}_default", "-v", f"{kit}:/kit",
             "mongo:8.2", "bash", "/kit/mongosh.sh"], capture_output=True, text=True)
        assert "1" in gen.stdout, f"generated mongosh snippet did not connect:\n{gen.stdout}\n{gen.stderr}"
    finally:
        subprocess.run(["docker", "compose", "-p", PROJ, "-f", compose, "down", "-v"], env=ENV)

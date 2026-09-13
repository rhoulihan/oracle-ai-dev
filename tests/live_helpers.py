# Copyright (c) 2026 Oracle and/or its affiliates.
"""Shared helpers for the live tier — ORDS readiness above all.

The ords compose service has no Docker healthcheck, and ORDS installs itself INTO
the database on first boot (minutes). Polling only the DB-side package status races
that install on a slow host — the flake the old `pytest.xfail` escapes papered over.
These helpers wait on readiness explicitly and fail with real diagnostics, so a
genuine failure reads as itself instead of a green xfail.
"""
import subprocess
import time

ORDS_CONTAINER = "oracle-ai-dev-ords"

# The same probe every Mongo-API live test uses: ORDS is usable once its package
# compiles VALID in the connected database.
ORDS_READY_SQL = (
    "SET HEAD OFF PAGES 0 FEED OFF\n"
    "SELECT status FROM all_objects "
    "WHERE object_name='ORDS' AND object_type='PACKAGE';")


# Connect through the PDB service, NOT a bare `system/devpassword`: a bare common-user
# connection lands in CDB$ROOT, where the ORDS package (installed into FREEPDB1) is
# invisible — the probe would poll forever. Every self-managing live test uses this
# same @service form.
_DEFAULT_CONN = "system/devpassword@localhost:1521/FREEPDB1"


def sqlplus(container_db: str, sql: str, conn: str = _DEFAULT_CONN) -> str:
    return subprocess.run(
        ["docker", "exec", "-i", container_db, "sqlplus", "-S", "-L", conn],
        input=sql, capture_output=True, text=True, timeout=90).stdout


def ords_logtail(lines: int = 40) -> str:
    out = subprocess.run(["docker", "logs", "--tail", str(lines), ORDS_CONTAINER],
                         capture_output=True, text=True)
    return (out.stdout + out.stderr).strip()


# Oracle's DEFAULT profile locks an account after this many failed logins. SYSTEM
# boots OPEN under DEFAULT, so a poller that retries a PASSWORD login through the
# first-boot ORA-01017 window locks the very account it is waiting for — and every
# later attempt then fails ORA-28000, including ones carrying the right password.
# Measured on database/free:latest (23.26.0): ORA-01017 x10, then ORA-28000, and
# the correct password rejected from then on. That is what turned an unchanged
# commit from green (2026-09-05) to red (09-06, 09-07).
FAILED_LOGIN_ATTEMPTS = 10
_PASSWORD_ATTEMPTS = 5          # comfortably under the limit, with room to spare

DB_OPEN_SQL = ("SET HEAD OFF PAGES 0 FEED OFF\n"
               "SELECT 'DB_OPEN' FROM v$instance WHERE status='OPEN';")


def sqlplus_sysdba(container_db: str, sql: str) -> str:
    """Bequeath connection inside the container — no password crosses the wire.

    Used for readiness polling precisely because it CANNOT increment the failed
    login counter, however long first boot takes.
    """
    return subprocess.run(
        ["docker", "exec", "-i", container_db, "sqlplus", "-S", "/", "as", "sysdba"],
        input=sql, capture_output=True, text=True, timeout=90).stdout


def wait_db_login(container_db: str, conn: str = _DEFAULT_CONN,
                  timeout: int = 300, probe=None, open_probe=None) -> None:
    """Block until the credentials actually WORK, or raise with the last output.

    Healthy is necessary, not sufficient: on a slow runner the container reports
    healthy while first-boot init is still setting ORACLE_PWD, and an immediate
    system login gets ORA-01017. So wait out that window WITHOUT spending password
    attempts — poll `/ as sysdba`, which needs no password — and only then try the
    real login, a handful of times, bailing out at once on ORA-28000 because a
    locked account cannot be retried into working. Both probes are injectable for
    offline tests.
    """
    deadline = time.time() + timeout
    if open_probe is None and probe is None:
        open_probe = lambda: sqlplus_sysdba(container_db, DB_OPEN_SQL)   # noqa: E731
    if open_probe is not None:
        while time.time() < deadline:
            if "DB_OPEN" in open_probe():
                break
            time.sleep(5)

    run = probe or (lambda: sqlplus(
        container_db, "SET HEAD OFF PAGES 0 FEED OFF\nSELECT 'LOGIN_OK' FROM dual;", conn))
    last = ""
    for _ in range(_PASSWORD_ATTEMPTS):
        if time.time() >= deadline:
            break
        last = run()
        if "LOGIN_OK" in last:
            return
        if "ORA-28000" in last:
            raise AssertionError(
                "database account is LOCKED (ORA-28000) — retrying cannot help. "
                f"Oracle's DEFAULT profile locks after {FAILED_LOGIN_ATTEMPTS} "
                "failed logins, so this is usually a poller that hammered the "
                f"first-boot window. last output:\n{last[-500:]}")
        time.sleep(5)
    raise AssertionError(
        f"database login not accepted within {timeout}s — first-boot init may "
        f"have failed. last output:\n{last[-500:]}")


def wait_ords_ready(container_db: str, conn: str = _DEFAULT_CONN,
                    timeout: int = 600) -> None:
    """Block until the Mongo API is serviceable, or raise with diagnostics.

    Two gates: the ords container is running, and the ORDS package is VALID in the
    database. `conn` is the connection the caller reaches the DB with (the modules
    connect as `system@…/FREEPDB1`).
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        running = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", ORDS_CONTAINER],
            capture_output=True, text=True).stdout.strip()
        if running == "true":
            last = sqlplus(container_db, ORDS_READY_SQL, conn).strip()
            if last == "VALID":
                return
        time.sleep(5)
    raise AssertionError(
        f"ORDS did not become ready within {timeout}s "
        f"(last package status {last!r}). ords logs:\n{ords_logtail()}")

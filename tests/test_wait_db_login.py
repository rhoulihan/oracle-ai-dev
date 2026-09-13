# Copyright (c) 2026 Oracle and/or its affiliates.
"""Healthy is necessary, not sufficient: the login must actually WORK.

The nightly runner exposed a first-boot race the fast local machine never
shows: the container reports healthy while the image's init flow is still
setting ORACLE_PWD, so an immediate system/devpassword login gets ORA-01017.
wait_db_login polls a real login after the healthcheck, treating ORA-01017 as
"still initializing", bounded — and reports the last output when it gives up.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))


def test_retries_through_the_first_boot_password_race(monkeypatch):
    import live_helpers
    monkeypatch.setattr(live_helpers.time, "sleep", lambda s: None)
    outs = iter(["ERROR:\nORA-01017: invalid credential; logon denied",
                 "ERROR:\nORA-01017: invalid credential; logon denied",
                 "LOGIN_OK"])
    live_helpers.wait_db_login("db", probe=lambda: next(outs))


def test_gives_up_with_the_last_output_named(monkeypatch):
    import live_helpers
    monkeypatch.setattr(live_helpers.time, "sleep", lambda s: None)
    t = iter(range(0, 10_000, 100))          # fake clock: each check costs 100s
    monkeypatch.setattr(live_helpers.time, "time", lambda: next(t))
    with pytest.raises(AssertionError, match="ORA-01017"):
        live_helpers.wait_db_login("db", timeout=300,
                                   probe=lambda: "ERROR:\nORA-01017: logon denied")


# --- the 2026-09-06/07 nightly failure -------------------------------------
# Measured on database/free:latest (23.26.0): SYSTEM boots OPEN under the
# DEFAULT profile, whose FAILED_LOGIN_ATTEMPTS is 10. Eleven bad logins return
# ORA-01017 x10 then ORA-28000 — and the CORRECT password returns ORA-28000
# from then on. So a poller that retries a password login through the
# first-boot window converts a transient race into a permanent lock: exactly
# what turned an unchanged commit from green (09-05) to red (09-06, 09-07).

PROFILE_FAILED_LOGIN_ATTEMPTS = 10      # measured, DEFAULT profile


def test_password_attempts_stay_under_the_profile_limit(monkeypatch):
    """The loop must not be able to lock the account it is waiting for."""
    import live_helpers
    monkeypatch.setattr(live_helpers.time, "sleep", lambda s: None)
    clock = iter(range(0, 100_000, 5))           # 5s per tick: 60 ticks inside 300s
    monkeypatch.setattr(live_helpers.time, "time", lambda: next(clock))
    calls = []

    def probe():
        calls.append(1)
        return "ERROR:\nORA-01017: invalid credential; logon denied"

    with pytest.raises(AssertionError):
        live_helpers.wait_db_login("db", timeout=300, probe=probe)
    assert len(calls) < PROFILE_FAILED_LOGIN_ATTEMPTS, (
        f"made {len(calls)} password attempts — at "
        f"{PROFILE_FAILED_LOGIN_ATTEMPTS} the account locks and every later "
        "attempt fails ORA-28000, including ones with the right password")


def test_stops_on_the_lock_instead_of_hammering(monkeypatch):
    """ORA-28000 is terminal: retrying it cannot succeed, so say so at once."""
    import live_helpers
    monkeypatch.setattr(live_helpers.time, "sleep", lambda s: None)
    clock = iter(range(0, 100_000, 5))
    monkeypatch.setattr(live_helpers.time, "time", lambda: next(clock))
    calls = []

    def probe():
        calls.append(1)
        return "ERROR:\nORA-28000: The account is locked; login denied."

    with pytest.raises(AssertionError, match="ORA-28000"):
        live_helpers.wait_db_login("db", timeout=300, probe=probe)
    assert len(calls) == 1, f"kept probing a locked account {len(calls)} times"

# Copyright (c) 2026 Oracle and/or its affiliates.
"""ORDS must survive a restart.

Found in demo rehearsal: the `ords` service had no volume for `/etc/ords/config`. ORDS
installs itself into the DATABASE (which persists in the `oradata` volume) but writes its
config to the container's EPHEMERAL filesystem. So on the second `up`:

    INFO : The Oracle REST Data Services is already installed in your database.
    ERROR: The ORDS config directory /etc/ords/config is empty, please validate you ords
           config volume.

It works exactly once, on a virgin database volume, and is broken on every restart —
which is exactly the shape of a demo (warm the stack in pre-flight, bring it up again on
stage) and of any developer who stops and starts their environment. No Mongo API, no REST.
"""
import re
from pathlib import Path


def test_ords_config_is_on_a_persistent_volume(repo_root: Path):
    compose = (repo_root / "assets/compose/db-ords.compose.yml").read_text()
    assert "/etc/ords/config" in compose, (
        "the ords service has no volume for /etc/ords/config — ORDS installs into the "
        "database (persistent) but configures itself on the container filesystem "
        "(ephemeral), so the SECOND `up` fails with 'config directory is empty'")
    # and the volume must be declared, not a stray bind
    vols = compose.split("volumes:")[-1]
    assert re.search(r"\bords[-_]?config\b", compose), compose[-200:]


def test_ords_gets_the_schema_password_the_installer_demands(repo_root: Path):
    """ORDS 26.2.3 aborts its install without ORACLE_USER_PWD.

    Nightly 2026-09-09 (run 34350617056): the ords image published 09-08 made
    ORACLE_USER_PWD mandatory. Its entrypoint's _get_ords_user_pwd() now returns
    1 the moment that variable is empty:

        INFO : Installing The Oracle REST Data Services 26.2.3.
        ERROR: Required variable ORACLE_USER_PWD is missing or empty. Aborting.

    The guard fires BEFORE the fallback branches that still handle "no password
    supplied" (`elif [[ -z "$ORACLE_USER_NAME" ]] && [[ -z "$ORACLE_USER_PWD" ]]`
    -> sys/${ORACLE_PWD}/...), which is the path this compose used to take with
    ORACLE_PWD alone. So ORDS never installs, no package appears in the database,
    and every Mongo-API live test times out waiting for readiness.
    """
    compose = (repo_root / "assets/compose/db-ords.compose.yml").read_text()
    ords = compose.split("  ords:", 1)[-1]
    assert "ORACLE_USER_PWD" in ords, (
        "the ords service does not set ORACLE_USER_PWD — the 26.2.3+ entrypoint "
        "aborts its install without it, so ORDS never reaches the database")

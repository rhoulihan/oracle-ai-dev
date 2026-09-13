import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _health(name: str) -> str:
    out = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
        capture_output=True, text=True)
    return out.stdout.strip()


from live_helpers import wait_ords_ready  # noqa: E402  (tests/ is on sys.path via pytest)


@pytest.fixture(scope="session")
def live_container():
    """A healthy db+ORDS 26ai stack for live tests that don't manage their own.

    Reuses a running $ORACLE_AI_DEV_CONTAINER (default oracle-ai-dev-db) if one is
    already healthy — the demo-script workflow. Otherwise boots the **db-ords**
    compose profile once for the session (so the Mongo-API stack-validation tests
    run for real instead of skipping) and tears it down afterwards.

    Introduced by the 2026-07-14 repo review (tests assumed a pre-provisioned
    container); extended 2026-07-15 to the db-ords profile so the three Mongo-API
    validations stop silently skipping, with ORDS readiness waited on explicitly.
    """
    name = os.environ.get("ORACLE_AI_DEV_CONTAINER", "oracle-ai-dev-db")
    proj = "oadsession"
    if _health(name) == "healthy":
        # A pre-provisioned db-only container (demo workflow): ORDS may be absent,
        # and the Mongo tests skip honestly in that case — we do not tear down what
        # we did not start.
        yield name
        return
    # Boot the db-ords profile so the Mongo-API validations CAN run — but the fixture
    # is ready as soon as the DATABASE is healthy. ORDS install continues in the
    # background; only the Mongo test waits on it (via wait_ords_ready), so the ~20
    # DB-only tests never error on an ORDS hiccup. Blast radius stays where it belongs.
    compose = str(Path(__file__).resolve().parent.parent / "assets/compose/db-ords.compose.yml")
    subprocess.run(["docker", "compose", "-p", proj, "-f", compose, "up", "-d"], check=True)
    for _ in range(72):
        if _health(name) == "healthy":
            break
        time.sleep(5)
    else:
        subprocess.run(["docker", "compose", "-p", proj, "-f", compose, "down", "-v"])
        pytest.fail(f"{name} did not become healthy within 6 minutes")
    yield name
    subprocess.run(["docker", "compose", "-p", proj, "-f", compose, "down", "-v"])

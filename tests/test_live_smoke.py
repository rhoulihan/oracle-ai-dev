import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ORACLE_AI_DEV_LIVE") != "1",
    reason="set ORACLE_AI_DEV_LIVE=1 to run the live Docker smoke test",
)

DB_HOST_PORT = os.environ.get("DB_HOST_PORT", "1599")


@pytest.mark.live
def test_db_profile_boots_and_verifies(repo_root: Path):
    compose = str(repo_root / "assets/compose/db.compose.yml")
    proj = "oadsmoke"
    env = {**os.environ, "DB_HOST_PORT": DB_HOST_PORT}
    subprocess.run(
        ["docker", "compose", "-p", proj, "-f", compose, "up", "-d"],
        check=True, env=env)
    try:
        for _ in range(72):  # up to ~6 min
            out = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", "oracle-ai-dev-db"],
                capture_output=True, text=True).stdout.strip()
            if out == "healthy":
                break
            time.sleep(5)
        else:
            pytest.fail("db did not become healthy in time")
        r = subprocess.run(
            ["bash", str(repo_root / "assets/verify/verify-setup.sh"), "localhost", DB_HOST_PORT],
            capture_output=True, text=True)
        assert "ASSERT:db_port_open:PASS" in r.stdout, r.stdout
    finally:
        subprocess.run(
            ["docker", "compose", "-p", proj, "-f", compose, "down", "-v"], env=env)

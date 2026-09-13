# Copyright (c) 2026 Oracle and/or its affiliates.
"""verify-ords.sh: DB healthy is NOT Mongo-API ready.

ORDS installs itself into the database for minutes after `compose up --wait`
returns; this script is the user-facing sibling of the live tier's
wait_ords_ready probe. Offline, the honest testable half is its failure
behavior: a container that does not EXIST fails fast with a message that says
so — not after a 10-minute poll against nothing.
"""

import os
import stat
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "assets" / "verify" / "verify-ords.sh"


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & stat.S_IXUSR, "must be executable"


def test_missing_container_fails_fast_and_says_so():
    t0 = time.time()
    r = subprocess.run(["bash", str(SCRIPT), "no-such-db", "no-such-ords",
                        "x/y@z", "600"],
                       capture_output=True, text=True, cwd=REPO, timeout=60,
                       env={**os.environ, "PATH": os.environ["PATH"]})
    assert time.time() - t0 < 30, "a nonexistent container must not poll for 10 minutes"
    assert r.returncode != 0
    assert "ASSERT:ords_ready:FAIL" in r.stdout
    assert "does not exist" in r.stdout + r.stderr

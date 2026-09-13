# Copyright (c) 2026 Oracle and/or its affiliates.
"""The benchmark-schema lifecycle tool and its external-safety guard."""
import os
import subprocess
from pathlib import Path

import pytest

LC = "assets/tooling/optimize/db-lifecycle.sh"


def _run(repo_root, cmd, **env):
    e = {**os.environ, "PATH": os.environ.get("PATH", ""), **env}
    return subprocess.run(["bash", str(repo_root / LC), cmd],
                          capture_output=True, text=True, env=e)


def test_external_destructive_is_refused_without_override(repo_root: Path):
    for cmd in ("reset", "new-project", "load"):
        p = _run(repo_root, cmd, OPT_CONN_MODE="wallet")
        assert p.returncode == 3, f"{cmd} should be refused on external target"
        assert "REFUSED" in p.stderr and "protected" in p.stderr


def test_external_read_passes_the_guard(repo_root: Path):
    # status is read-only: the guard must let it through (it then fails later at
    # the connection step, which is NOT a guard refusal).
    p = _run(repo_root, "status", OPT_CONN_MODE="wallet", OPT_WALLET="/nope")
    assert "REFUSED" not in p.stderr


def test_override_lets_external_write_past_the_guard(repo_root: Path):
    # with the explicit override the guard permits it (then fails at connect).
    p = _run(repo_root, "new-project", OPT_CONN_MODE="wallet",
             OPT_ALLOW_EXTERNAL_WRITES="1")
    assert "REFUSED" not in p.stderr
    assert "override in effect" in p.stderr


def test_unknown_command_errors(repo_root: Path):
    p = _run(repo_root, "frobnicate")
    assert p.returncode == 2


def test_status_script_enables_serveroutput(repo_root: Path):
    # The row counts are emitted via DBMS_OUTPUT.PUT_LINE; sqlplus/SQLcl default
    # SERVEROUTPUT OFF, so without this the '=== sample row counts ===' banner
    # prints followed by nothing (time-query.sql and time-dml.sql already set it).
    s = (repo_root / "assets/seed/scale/status.sql").read_text().lower()
    assert "dbms_output.put_line" in s
    assert "set serveroutput on" in s, "counts are silently discarded without SERVEROUTPUT"


def test_drop_script_only_names_benchmark_objects(repo_root: Path):
    s = (repo_root / "assets/seed/scale/drop-benchmark.sql").read_text().lower()
    # fixed allow-list, FK-safe (view before its base tables), missing = ignored
    assert "order_dv" in s and "order_docs" in s and "orders" in s
    assert s.index("order_dv") < s.index("'table', 'orders'")
    assert "sqlcode not in" in s

def test_status_is_read_only(repo_root: Path):
    s = (repo_root / "assets/seed/scale/status.sql").read_text().lower()
    for banned in ("delete", "drop ", "insert", "update ", "truncate"):
        assert banned not in s, f"status.sql must be read-only, found {banned!r}"

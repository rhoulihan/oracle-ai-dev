# Copyright (c) 2026 Oracle and/or its affiliates.
"""Running the optimizer against an external system: a connection-mode-aware SQL
runner (local container / easy-connect / mTLS wallet) + a volume-scaling sample."""
import os
import subprocess
from pathlib import Path


def test_runner_makes_sqlcl_headless_in_easy_mode(repo_root: Path, tmp_path):
    """The agent runs run-sql.sh non-interactively; without the dumb jline
    terminal provider SQLcl aborts with 'Unable to create a terminal' — and
    exits 0, so the benchmark harness would get empty output with a success
    code. run-sql.sh must set the flag itself (via lib.sh) like every other
    SQLcl caller in the repo."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "sql"
    shim.write_text('#!/usr/bin/env bash\ncat >/dev/null\necho "JTO=${JAVA_TOOL_OPTIONS:-}"\n')
    shim.chmod(0o755)
    script = tmp_path / "noop.sql"
    script.write_text("SELECT 1 FROM dual;\n")
    env = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"}
    env.update(PATH=f"{shim_dir}:{env.get('PATH', '')}",
               OPT_CONN_MODE="easy", OPT_CONNECT="u/p@//db:1521/PDB1")
    p = subprocess.run(
        ["bash", str(repo_root / "assets/tooling/optimize/run-sql.sh"), str(script)],
        capture_output=True, text=True, env=env)
    assert "org.jline.terminal.provider=dumb" in p.stdout, \
        f"easy mode ran SQLcl without the headless flag:\n{p.stdout}\n{p.stderr}"


def test_runner_supports_three_connection_modes(repo_root: Path):
    s = (repo_root / "assets/tooling/optimize/run-sql.sh").read_text().lower()
    for mode in ("container", "easy", "wallet"):
        assert mode in s, f"run-sql.sh missing the {mode!r} mode"
    assert "cloudconfig" in s          # SQLcl consumes the ADB wallet directly
    assert "-l" in s                   # sqlplus -L: fail fast, never hang a benchmark
    assert "opt_connect" in s


def test_scale_seed_generates_all_three_shapes(repo_root: Path):
    s = (repo_root / "assets/seed/scale/scale-seed.sql").read_text().lower()
    assert "&orders" in s and "&items_per_order" in s   # sized
    assert "connect by level" in s                       # bulk generate
    assert "delete from order" in s                      # idempotent: clear prior
    assert "insert into order_docs" in s                 # document shape populated
    assert "json_arrayagg" in s                          # items nested into the doc
    assert "order_dv" in s                               # duality reflected in report
    assert "commit" in s


def test_scale_seed_reports_shape_agreement(repo_root: Path):
    # the final report counts all three shapes so a mismatch is visible
    s = (repo_root / "assets/seed/scale/scale-seed.sql").read_text().lower()
    for col in ("orders_rel", "orders_doc", "orders_dv"):
        assert col in s

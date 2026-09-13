# Copyright (c) 2026 Oracle and/or its affiliates.
"""The configurators resolve SQLcl the same self-healing way as the MCP arm.

Demonstrated in the greenfield clean-room: eleven scripts called bare `sql`
while the plugin's self-installed SQLcl sits deliberately OFF PATH, so
create-plugin-user reported a bare ASSERT:FAIL with `command not found`
swallowed. lib.sh now resolves through ensure-sqlcl.sh at source time and
exposes a `sql` function; failure names its cause on visible stderr; scripts
that never touch sql opt out (OAD_NO_SQL=1) and stay dependency-free.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Satisfies ensure-sqlcl's works() probe (-version -> exit 0, output says
# SQLcl); any other invocation prints a marker and echoes a scalar so the
# configurators' `grep -q "1"` checks succeed.
_STUB = """#!/usr/bin/env bash
if [ "${1:-}" = "-version" ]; then echo "SQLcl stub 25.1"; exit 0; fi
cat >/dev/null
echo "STUB-SQL-RAN $*"
echo "1"
"""

# Like _STUB, but the scalar answer arrives AFTER a pause. Forces the
# early-grep-exit race deterministically: a `... | grep -q` consumer matches
# on the first line (the echoed connection string contains "1521"), exits,
# and the still-writing producer takes SIGPIPE — which `set -o pipefail`
# converts into a FAIL even though the match succeeded. Seen as a one-in-N
# CI flake on 2026-08-09; the fix is capture-then-match.
_SLOW_TAIL_STUB = """#!/usr/bin/env bash
if [ "${1:-}" = "-version" ]; then echo "SQLcl stub 25.1"; exit 0; fi
cat >/dev/null
echo "STUB-SQL-RAN $*"
sleep 1
echo "1"
"""

# An old JVM: makes ensure-sqlcl fail FAST at the Java preflight (before any
# resolution or download), which is the cheapest honest failure to provoke.
_OLD_JAVA = """#!/usr/bin/env bash
echo 'openjdk version "1.8.0_401"' >&2
exit 0
"""


def _java_home():
    java = shutil.which("java")
    if java is None:
        return None
    return str(Path(os.path.realpath(java)).parent.parent)


def _write_exe(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _bash(script, env, cwd=REPO):
    return subprocess.run(["bash", "-c", script], env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=300)


def test_lib_resolves_the_plugin_installed_sqlcl_off_path(tmp_path):
    jh = _java_home()
    if jh is None:
        import pytest
        pytest.skip("no java on this machine; ensure-sqlcl's preflight needs one")
    home = tmp_path / "sqlclhome"
    _write_exe(home / "sqlcl" / "bin" / "sql", _STUB)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "SQLCL_HOME": str(home), "JAVA_HOME": jh}
    r = _bash('source assets/verify/lib.sh && echo "select 1;" | sql -S sys/x@db', env)
    assert r.returncode == 0, r.stderr
    assert "STUB-SQL-RAN -S sys/x@db" in r.stdout, \
        "lib.sh must route sql calls to the plugin's own SQLcl, off PATH"


def test_a_whole_configurator_works_without_sql_on_path(tmp_path):
    jh = _java_home()
    if jh is None:
        import pytest
        pytest.skip("no java on this machine; ensure-sqlcl's preflight needs one")
    home = tmp_path / "sqlclhome"
    _write_exe(home / "sqlcl" / "bin" / "sql", _STUB)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "SQLCL_HOME": str(home), "JAVA_HOME": jh}
    r = _bash('bash assets/tooling/configure/create-plugin-user.sh "system/x@localhost:1521/FREEPDB1"', env)
    assert "ASSERT:plugin_user:PASS" in r.stdout, r.stdout + r.stderr


def test_configurator_survives_a_slow_sql_tail(tmp_path):
    # The 2026-08-09 CI flake, made deterministic: SQLcl's answer trickles out
    # after the line the grep matches on, so an early-exiting `grep -q` in the
    # pipeline SIGPIPEs the producer and pipefail reports a false FAIL.
    jh = _java_home()
    if jh is None:
        import pytest
        pytest.skip("no java on this machine; ensure-sqlcl's preflight needs one")
    home = tmp_path / "sqlclhome"
    _write_exe(home / "sqlcl" / "bin" / "sql", _SLOW_TAIL_STUB)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "SQLCL_HOME": str(home), "JAVA_HOME": jh}
    r = _bash('bash assets/tooling/configure/create-plugin-user.sh "system/x@localhost:1521/FREEPDB1"', env)
    assert "ASSERT:plugin_user:PASS" in r.stdout, r.stdout + r.stderr


def test_resolution_failure_names_its_cause_on_visible_stderr(tmp_path):
    fake_java = tmp_path / "jvm"
    _write_exe(fake_java / "bin" / "java", _OLD_JAVA)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "SQLCL_HOME": str(tmp_path / "empty"), "JAVA_HOME": str(fake_java)}
    r = _bash('source assets/verify/lib.sh; echo sourced; sql -S x; echo "rc=$?"', env)
    assert "sourced" in r.stdout, "sourcing lib.sh must not abort the script"
    assert "rc=127" in r.stdout, "calling sql after a failed resolution must fail"
    assert "Java" in r.stderr, \
        "the cause (Java 17+ missing) must reach VISIBLE stderr, not a swallowed one"


def test_no_sql_scripts_skip_resolution_entirely(tmp_path):
    # verify-setup probes a TCP port and must stay runnable on a machine with
    # no Java and no SQLcl at all.
    fake_java = tmp_path / "jvm"
    _write_exe(fake_java / "bin" / "java", _OLD_JAVA)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           "SQLCL_HOME": str(tmp_path / "empty"), "JAVA_HOME": str(fake_java)}
    r = _bash("bash assets/verify/verify-setup.sh localhost 1", env)
    assert "Java" not in r.stderr, "a no-sql script must not pay or report SQLcl resolution"
    assert "ASSERT:db_port_open:FAIL" in r.stdout  # port 1 closed: honest failure


def test_assert_prints_the_failing_commands_output():
    script = ('export OAD_NO_SQL=1; source assets/verify/lib.sh; '
              'boom() { echo "ORA-01017: invalid credentials"; return 1; }; '
              'assert who boom; echo "rc=$?"')
    r = _bash(script, {"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
    assert "ASSERT:who:FAIL" in r.stdout
    assert "ORA-01017" in r.stderr, \
        "the failing command's output must surface on FAIL, not vanish"

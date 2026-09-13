import os
import subprocess
from pathlib import Path

import pytest


def test_configure_scripts_pass_shellcheck(repo_root: Path):
    scripts = list((repo_root / "assets/tooling/configure").glob("*.sh"))
    assert scripts, "no configurator scripts found"
    r = subprocess.run(["shellcheck", *map(str, scripts)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_create_user_sql_is_idempotent(repo_root: Path):
    sql = (repo_root / "assets/tooling/configure/create-plugin-user.sql").read_text().lower()
    assert "plugin_dev" in sql
    assert ("count(*)" in sql) or ("exception" in sql), "must guard against re-create"


def test_configurator_emits_assert_line(repo_root: Path):
    sh = (repo_root / "assets/tooling/configure/create-plugin-user.sh").read_text()
    assert "ASSERT:" in sh or "assert " in sh, "must emit an ASSERT result"


def test_doctor_reports_features(repo_root: Path):
    sh = (repo_root / "assets/tooling/configure/doctor.sh").read_text().lower()
    assert "plugin_dev" in sh


def test_create_user_rejects_unsafe_password(repo_root: Path):
    # A password with a quote/ampersand must be rejected BEFORE any SQL runs
    # (SQLcl &-substitution would otherwise allow PL/SQL injection). The
    # distinctive "unsafe" message proves the guard fired, not just a missing sql.
    sh = repo_root / "assets/tooling/configure/create-plugin-user.sh"
    r = subprocess.run(
        ["bash", str(sh), "dummy/conn@db", "bad'pw&x"],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "unsafe" in (r.stdout + r.stderr).lower()



def test_lib_sh_makes_sqlcl_headless(repo_root):
    """Every configurator shells out to SQLcl (`sql -S ...`), and the agent runs them
    NON-INTERACTIVELY. Without a dumb terminal provider, SQLcl's jline dies with
    `java.lang.IllegalStateException: Unable to create a terminal` and every
    configurator returns ASSERT:<name>:FAIL. `.mcp.json` already sets this for the MCP
    server; lib.sh (sourced by every configurator) must do the same.
    """
    lib = (repo_root / "assets/verify/lib.sh").read_text()
    assert "JAVA_TOOL_OPTIONS" in lib, "configurators must run SQLcl headlessly"
    assert "org.jline.terminal.provider=dumb" in lib
    assert "export" in lib, "must be exported so the `sql` child process sees it"


# SQLcl prints SQL statement errors to STDOUT and exits 0 (WHENEVER SQLERROR
# defaults to CONTINUE), so a configurator can only trust an explicit success
# marker in the output — never the exit code, and never bare digits (every
# ORA-xxxxx message contains digits).
_SQLCL_ERROR_OUTPUT = """\
Error starting at line : 1 in command -
GRANT SODA_APP TO nosuchuser
Error report -
ORA-01917: user or role 'NOSUCHUSER' does not exist

  COUNT(*)
----------
         0
"""

# Every shim answers the works-probe (`sql -version` -> "SQLcl..."): lib.sh now
# resolves SQLcl through ensure-sqlcl.sh, and a shim that cannot identify itself
# as SQLcl is (correctly) rejected instead of adopted.
_VERSION_GATE = 'if [ "${1:-}" = "-version" ]; then echo "SQLcl shim 25.1"; exit 0; fi\n'

_ERROR_SHIM = f"""#!/usr/bin/env bash
{_VERSION_GATE}cat >/dev/null
cat <<'OUT'
{_SQLCL_ERROR_OUTPUT}OUT
exit 0
"""

# Emulates success: echoes back the script's own marker with a nonzero count.
_SUCCESS_SHIM = f"""#!/usr/bin/env bash
{_VERSION_GATE}in="$(cat)"
marker="$(printf '%s' "$in" | grep -oE '[A-Z_]+_OK_' | head -1)"
printf 'RESULT\\n------\\n%s1\\n' "${{marker}}"
exit 0
"""

_SQLCL_CONFIGURATORS = {
    "enable-soda.sh": ["sys@db as sysdba", "app_user"],
    "enable-property-graph.sh": ["sys@db as sysdba", "app_user"],
    "enable-duality-graphql.sh": ["conn@db", "app_user"],
    "enable-select-ai.sh": ["sys@db as sysdba", "INSTALL_SCRIPT"],
    "enable-text-index.sh": ["conn@db", "docs", "data", "docs_search_ix"],
    "init-awr.sh": ["conn@db"],
    "load-onnx-model.sh": ["conn@db", "/opt/models"],
    "enable-vector-memory.sh": ["sys@db as sysdba", "512M"],
}


def _run_with_sql_shim(repo_root, tmp_path, script, shim_body):
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "sql"
    shim.write_text(shim_body)
    shim.chmod(0o755)
    args = list(_SQLCL_CONFIGURATORS[script])
    if "INSTALL_SCRIPT" in args:
        install = tmp_path / "dbms_cloud_install.sql"
        install.write_text("-- stand-in install script\n")
        args[args.index("INSTALL_SCRIPT")] = str(install)
    # Hermetic: HOME/SQLCL_HOME point into tmp so resolution can never adopt a
    # SQLcl that happens to live on the developer's machine, and never installs.
    env = {**os.environ, "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
           "HOME": str(tmp_path), "SQLCL_HOME": str(tmp_path / "no-bundled"),
           "SQLCL_NO_INSTALL": "1"}
    return subprocess.run(
        ["bash", str(repo_root / "assets/tooling/configure" / script), *args],
        capture_output=True, text=True, env=env, timeout=120)


@pytest.mark.parametrize("script", sorted(_SQLCL_CONFIGURATORS))
def test_configurator_fails_on_ora_error(repo_root: Path, tmp_path, script):
    """A failed statement (SQLcl: ORA- on stdout, exit 0) must report FAIL —
    grepping raw output for digits matched the '1917' in the error message."""
    p = _run_with_sql_shim(repo_root, tmp_path, script, _ERROR_SHIM)
    assert ":FAIL" in p.stdout, f"{script} reported success on an ORA- error:\n{p.stdout}"
    assert ":PASS" not in p.stdout
    assert p.returncode != 0


@pytest.mark.parametrize("script", sorted(_SQLCL_CONFIGURATORS))
def test_configurator_passes_on_success_marker(repo_root: Path, tmp_path, script):
    p = _run_with_sql_shim(repo_root, tmp_path, script, _SUCCESS_SHIM)
    assert ":PASS" in p.stdout, f"{script} failed on clean output:\n{p.stdout}\n{p.stderr}"
    assert p.returncode == 0


def test_no_configurator_greps_bare_digits(repo_root: Path):
    """`grep -qE '[1-9]'` over raw SQLcl/sqlplus output false-PASSes on any
    ORA-xxxxx message; success must key on an explicit marker instead."""
    offenders = []
    for sh in (repo_root / "assets/tooling/configure").glob("*.sh"):
        t = sh.read_text()
        if "grep -qE '[1-9]'" in t or "grep -qE '[1-9][0-9]*'" in t:
            offenders.append(sh.name)
    assert not offenders, f"scripts trusting bare digits in SQL output: {offenders}"


def test_every_sqlcl_script_sources_lib_sh(repo_root):
    """The headless-SQLcl flag lives in lib.sh, so any script that shells out to `sql`
    must source it — otherwise it dies with 'Unable to create a terminal' when the agent
    runs it (this is exactly how doctor.sh silently reported every feature as absent)."""
    import re
    gaps = []
    for d in ("assets/tooling/configure", "assets/tooling/optimize",
              "assets/verify", "scripts"):
        for p in (repo_root / d).glob("*.sh"):
            if p.name == "lib.sh":
                continue
            t = p.read_text()
            if re.search(r"\bsql -S|\|\s*sql\b", t) and "lib.sh" not in t:
                gaps.append(str(p.relative_to(repo_root)))
    assert not gaps, f"scripts calling SQLcl without sourcing lib.sh (headless flag): {gaps}"

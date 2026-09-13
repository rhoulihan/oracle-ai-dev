import json
import os
import shutil
import stat
import subprocess
from pathlib import Path


def _sqlcl(repo_root: Path) -> dict:
    m = json.loads((repo_root / ".mcp.json").read_text())
    return m["mcpServers"]["sqlcl"]


def test_command_is_the_bundled_launcher(repo_root: Path):
    """SQLcl is a self-healing dependency: the MCP server launches our wrapper, which
    resolves SQLcl (config override -> PATH -> plugin data) and installs it if missing.
    Pointing `command` straight at `sql` would fail for anyone without SQLcl."""
    assert _sqlcl(repo_root)["command"] == "${CLAUDE_PLUGIN_ROOT}/scripts/sqlcl-mcp.sh"


def test_restrict_level_4_is_present_and_ordered(repo_root: Path):
    args = _sqlcl(repo_root)["args"]
    assert "-mcp" in args, "must launch MCP mode"
    i = args.index("-R")
    assert args[i + 1] == "4", "restrict level 4 is a security MUST"


# --- the isolated connection store (-home) must be COHERENT across platforms -------
# gap-3 recommendation 3: the plugin must spawn `sql -mcp -R 4 -home <isolated dir>`,
# and connections saved into a different dbtools home are invisible to the server.
# Codex does no ${} expansion, and a user saving a connection from a terminal cannot
# address ${CLAUDE_PLUGIN_DATA} — so the ONE store both platforms and the save
# workflow can share is a fixed path, appended by the shared launcher.
_DBTOOLS_HOME_SUFFIX = "/.oracle-ai-dev/dbtools-home"


def test_claude_manifest_leaves_home_to_the_launcher(repo_root: Path):
    """A ${CLAUDE_PLUGIN_DATA}-based -home in .mcp.json would be a store no terminal
    save can reach (and one Codex could never mirror) — the launcher owns -home."""
    args = _sqlcl(repo_root)["args"]
    assert args == ["-mcp", "-R", "4"], args


def test_platform_launches_agree_on_args(repo_root: Path):
    codex = json.loads((repo_root / ".codex-plugin/plugin.json").read_text())
    codex_args = codex["mcpServers"]["sqlcl"]["args"]
    assert codex_args[0] == "./scripts/sqlcl-mcp.sh"
    assert codex_args[1:] == _sqlcl(repo_root)["args"], \
        "Claude and Codex must launch the SQLcl MCP server identically"


def test_skill_saves_into_the_store_the_server_reads(repo_root: Path):
    """The skill's save-connection workflow must target the exact home the launcher
    passes to the server — a plain `conn -save` into ~/.dbtools is invisible to it."""
    skill = (repo_root / "skills/sqlcl-mcp-setup/SKILL.md").read_text()
    launcher = (repo_root / "scripts/sqlcl-mcp.sh").read_text()
    assert "~" + _DBTOOLS_HOME_SUFFIX in skill, \
        "the skill must name the isolated store the server actually reads"
    assert "(stored in `~/.dbtools`)" not in skill, \
        "~/.dbtools is NOT where the bundled server looks for connections"
    assert _DBTOOLS_HOME_SUFFIX in launcher, \
        "the launcher must pin the same store on both platforms"


def test_launcher_appends_the_isolated_home(repo_root: Path, tmp_path: Path):
    """Behavioural: sqlcl-mcp.sh must exec SQLcl with -home <fixed store> on any
    platform, even though neither manifest can carry the path portably."""
    fake = _fake_arg_echoing_sql(tmp_path)
    _fake_java(tmp_path, "21.0.1")
    env = {**os.environ, "SQLCL_PATH": str(fake), "JAVA_HOME": "",
           "PATH": str(_bin(tmp_path)), "HOME": str(tmp_path)}
    r = subprocess.run([str(repo_root / "scripts/sqlcl-mcp.sh"), "-mcp", "-R", "4"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    home = str(tmp_path) + _DBTOOLS_HOME_SUFFIX
    assert r.stdout.split() == ["-mcp", "-R", "4", "-home", home], r.stdout
    assert Path(home).is_dir(), "the store must exist before SQLcl opens it"


def test_launcher_respects_a_caller_supplied_home(repo_root: Path, tmp_path: Path):
    """`claude mcp add sqlcl ... -- -mcp -R 4 -home X` stays honoured — the launcher
    only fills -home in when the caller did not choose one."""
    fake = _fake_arg_echoing_sql(tmp_path)
    _fake_java(tmp_path, "21.0.1")
    env = {**os.environ, "SQLCL_PATH": str(fake), "JAVA_HOME": "",
           "PATH": str(_bin(tmp_path)), "HOME": str(tmp_path)}
    r = subprocess.run([str(repo_root / "scripts/sqlcl-mcp.sh"),
                        "-mcp", "-R", "4", "-home", str(tmp_path / "mine")],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["-mcp", "-R", "4", "-home", str(tmp_path / "mine")]


def test_tns_admin_passed_through_env(repo_root: Path):
    env = _sqlcl(repo_root).get("env", {})
    assert env.get("TNS_ADMIN") == "${user_config.tns_admin}"


def test_user_sqlcl_path_is_passed_as_an_override(repo_root: Path):
    """The user's sqlcl_path is no longer the command — it becomes an optional
    override the launcher honours first."""
    env = _sqlcl(repo_root).get("env", {})
    assert env.get("SQLCL_PATH") == "${user_config.sqlcl_path}"


def test_launcher_and_ensure_scripts_exist_and_are_executable(repo_root: Path):
    for name in ("sqlcl-mcp.sh", "ensure-sqlcl.sh"):
        p = repo_root / "scripts" / name
        assert p.is_file(), f"{name} must exist (the MCP command depends on it)"
        assert p.stat().st_mode & stat.S_IXUSR, f"{name} must be executable"


def test_session_start_hook_prewarms_sqlcl(repo_root: Path):
    """A 143MB download inside MCP startup would blow the startup timeout (there is no
    per-server startup-timeout field), so the SessionStart hook pre-warms it."""
    manifest = json.loads((repo_root / ".claude-plugin/plugin.json").read_text())
    hooks = manifest.get("hooks", {})
    starts = json.dumps(hooks.get("SessionStart", []))
    assert "ensure-sqlcl.sh" in starts, "SessionStart must pre-warm the SQLcl dependency"


# --- behavioural: the resolver picks an existing SQLcl and never downloads --------
def _run_ensure(repo_root: Path, env_overrides: dict):
    env = {**os.environ, **env_overrides}
    return subprocess.run([str(repo_root / "scripts/ensure-sqlcl.sh")],
                          capture_output=True, text=True, env=env, timeout=30)


# `java` lives in /usr/bin on most systems, so a "no java" case can't just prepend a
# dir to the real PATH. Build a sandbox PATH holding only the shell utilities the
# script needs — java is present only when a test puts it there.
_UTILS = ("bash", "env", "mkdir", "rmdir", "rm", "mv", "sed", "cut", "head", "cat",
          "seq", "sleep", "dirname", "chmod")


def _bin(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    if not d.exists():
        d.mkdir(parents=True)
        for u in _UTILS:
            real = shutil.which(u)
            if real:
                (d / u).symlink_to(real)
    return d


def _fake_sql(tmp_path: Path) -> Path:
    """A stub that IDENTIFIES AS SQLcl. `ensure-sqlcl.sh` no longer adopts anything merely
    named `sql` — it runs `-version` and requires SQLcl to answer. A developer machine can
    easily have some other `sql` on PATH (in demo rehearsal it was a docker shim bound to a
    dead compose network), and adopting it makes every configurator fail with what looks
    like a database error."""
    f = _bin(tmp_path) / "sql"
    f.write_text("#!/usr/bin/env bash\n"
                 "echo 'SQLcl: Release 26.2.0.0 Production'\n"
                 "exit 0\n")
    f.chmod(0o755)
    return f


def _fake_arg_echoing_sql(tmp_path: Path) -> Path:
    """Identifies as SQLcl for the resolver's -version probe, then echoes whatever
    args the launcher finally execs it with — so tests can see the real MCP argv."""
    f = _bin(tmp_path) / "sql"
    f.write_text("#!/usr/bin/env bash\n"
                 "if [ \"${1:-}\" = -version ]; then\n"
                 "  echo 'SQLcl: Release 26.2.0.0 Production'; exit 0\n"
                 "fi\n"
                 "echo \"$@\"\n")
    f.chmod(0o755)
    return f


def _fake_not_sqlcl(tmp_path: Path) -> Path:
    """Something else called `sql` — must be REJECTED, not adopted."""
    f = _bin(tmp_path) / "sql"
    f.write_text("#!/usr/bin/env bash\necho 'usage: sql [options]'\nexit 1\n")
    f.chmod(0o755)
    return f


def _fake_java(tmp_path: Path, version: str) -> Path:
    """`java -version` writes to STDERR — mimic that exactly."""
    f = _bin(tmp_path) / "java"
    f.write_text(f"#!/usr/bin/env bash\necho 'openjdk version \"{version}\" 2024-01-01' >&2\n")
    f.chmod(0o755)
    return f


def test_ensure_honours_the_sqlcl_path_override(repo_root: Path, tmp_path: Path):
    fake = _fake_sql(tmp_path)
    _fake_java(tmp_path, "21.0.1")
    r = _run_ensure(repo_root, {"SQLCL_PATH": str(fake), "JAVA_HOME": "",
                                "PATH": str(_bin(tmp_path))})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(fake)          # resolved, nothing downloaded


def test_ensure_finds_sqlcl_on_path(repo_root: Path, tmp_path: Path):
    fake = _fake_sql(tmp_path)
    _fake_java(tmp_path, "21.0.1")
    r = _run_ensure(repo_root, {"SQLCL_PATH": "", "JAVA_HOME": "",
                                "PATH": str(_bin(tmp_path))})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(fake)          # found on PATH, nothing downloaded


# --- Java is SQLcl's runtime dependency: fail clearly, never with a cryptic JVM error
def test_ensure_fails_clearly_when_java_is_missing(repo_root: Path, tmp_path: Path):
    fake = _fake_sql(tmp_path)                    # SQLcl present, but no java anywhere
    r = _run_ensure(repo_root, {"SQLCL_PATH": str(fake), "JAVA_HOME": "",
                                "PATH": str(_bin(tmp_path))})
    assert r.returncode != 0, "must not hand back a SQLcl that cannot run"
    assert "Java 17" in r.stderr, r.stderr
    assert "no `java`" in r.stderr or "not found" in r.stderr.lower(), r.stderr


def test_ensure_fails_clearly_when_java_is_too_old(repo_root: Path, tmp_path: Path):
    fake = _fake_sql(tmp_path)
    _fake_java(tmp_path, "1.8.0_401")             # legacy 1.x scheme -> major 8
    r = _run_ensure(repo_root, {"SQLCL_PATH": str(fake), "JAVA_HOME": "",
                                "PATH": str(_bin(tmp_path))})
    assert r.returncode != 0, "Java 8 is below SQLcl's floor"
    assert "Java 17" in r.stderr, r.stderr
    assert "8" in r.stderr, "should name the version it actually found"


def test_ensure_accepts_java_17(repo_root: Path, tmp_path: Path):
    fake = _fake_sql(tmp_path)
    _fake_java(tmp_path, "17.0.8")                # exactly at the floor
    r = _run_ensure(repo_root, {"SQLCL_PATH": str(fake), "JAVA_HOME": "",
                                "PATH": str(_bin(tmp_path))})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(fake)


def test_ensure_honours_java_home(repo_root: Path, tmp_path: Path):
    """JAVA_HOME wins over PATH — a common setup where java isn't on PATH."""
    fake = _fake_sql(tmp_path)
    jhome = tmp_path / "jdk"
    (jhome / "bin").mkdir(parents=True)
    j = jhome / "bin" / "java"
    j.write_text("#!/usr/bin/env bash\necho 'openjdk version \"21.0.1\" 2024-01-01' >&2\n")
    j.chmod(0o755)
    r = _run_ensure(repo_root, {"SQLCL_PATH": str(fake), "JAVA_HOME": str(jhome),
                                "PATH": str(_bin(tmp_path))})   # no java on PATH
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(fake)


# --- the install lock must self-heal after SIGKILL/OOM/power loss -----------------
# The EXIT trap that frees the lock never runs on SIGKILL (e.g. Codex killing the
# launcher at its 60s startup timeout mid-download). A leftover lock must not wedge
# every later run into a 6-minute wait-then-fail; a LIVE holder must still block.
def _lock_sandbox(tmp_path: Path):
    """Copy ensure-sqlcl.sh next to a stub installer (instant, no 143MB download) so
    the install/lock path can run for real."""
    import shutil as _sh
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    repo = Path(__file__).resolve().parent.parent
    _sh.copy(repo / "scripts/ensure-sqlcl.sh", scripts / "ensure-sqlcl.sh")
    (scripts / "ensure-sqlcl.sh").chmod(0o755)
    target = tmp_path / "sqlcl-target"
    bundled = target / "sqlcl" / "bin" / "sql"
    inst = scripts / "install-sqlcl.sh"
    inst.write_text("#!/usr/bin/env bash\n"
                    "mkdir -p \"$1/sqlcl/bin\"\n"
                    "printf '%s\\n' '#!/usr/bin/env bash' "
                    "\"echo 'SQLcl: Release 26.2.0.0 Production'\" > \"$1/sqlcl/bin/sql\"\n"
                    "chmod 755 \"$1/sqlcl/bin/sql\"\n")
    inst.chmod(0o755)
    return scripts, target, bundled


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_stale_lock_from_a_killed_install_is_taken_over(repo_root: Path, tmp_path: Path):
    scripts, target, bundled = _lock_sandbox(tmp_path)
    _fake_java(tmp_path, "21.0.1")
    lock = Path(str(target) + ".lock")
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{_dead_pid()}\n")     # holder is gone (SIGKILL'd)
    env = {**os.environ, "SQLCL_PATH": "", "JAVA_HOME": "", "HOME": str(tmp_path),
           "PATH": str(_bin(tmp_path)), "SQLCL_HOME": str(target)}
    r = subprocess.run([str(scripts / "ensure-sqlcl.sh")],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stdout.strip() == str(bundled), "must install despite the orphaned lock"
    assert not lock.exists(), "the stale lock must be reclaimed, not waited on"


def test_live_lock_holder_still_blocks_a_second_install(repo_root: Path, tmp_path: Path):
    """Concurrency safety must survive the staleness fix: while the holder is alive,
    a second run sits in the wait loop (no takeover, no second download) and picks up
    the binary the holder installs. The binary appears only a few seconds IN, so the
    second run really exercises the wait branch rather than resolving up front."""
    scripts, target, bundled = _lock_sandbox(tmp_path)
    _fake_java(tmp_path, "21.0.1")
    lock = Path(str(target) + ".lock")
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{os.getpid()}\n")     # us: very much alive
    holder = subprocess.Popen(                        # "holder" finishes mid-wait
        ["bash", "-c", f"sleep 4; exec '{scripts / 'install-sqlcl.sh'}' '{target}'"])
    try:
        env = {**os.environ, "SQLCL_PATH": "", "JAVA_HOME": "", "HOME": str(tmp_path),
               "PATH": str(_bin(tmp_path)), "SQLCL_HOME": str(target)}
        r = subprocess.run([str(scripts / "ensure-sqlcl.sh")],
                           capture_output=True, text=True, env=env, timeout=60)
    finally:
        holder.wait()
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stdout.strip() == str(bundled)
    assert "waiting" in r.stderr, "a live lock must route the second run into the wait loop"
    assert lock.exists(), "a live holder's lock must never be stolen"


def test_ensure_rejects_a_sql_that_is_not_sqlcl(repo_root: Path, tmp_path: Path):
    """A `sql` that EXISTS is not a `sql` that WORKS. Found in demo rehearsal: `sql` on PATH
    was a docker shim bound to a compose network that no longer existed. ensure-sqlcl adopted
    it, the plugin's self-install never fired, and every SQLcl-backed configurator reported
    FAIL — `doctor` said the plugin user was 'absent' for a user that plainly existed. The
    failure looked like a database problem; it was a PATH problem."""
    import subprocess
    _fake_not_sqlcl(tmp_path)
    _fake_java(tmp_path, "21.0.1")
    # SQLCL_NO_INSTALL: after rejecting the impostor the script would otherwise
    # proceed to a real 143 MB download — the assertion needs the rejection, not
    # the install.
    env = dict(os.environ, PATH=f"{_bin(tmp_path)}:{os.environ['PATH']}",
               SQLCL_HOME=str(tmp_path / "never"), HOME=str(tmp_path),
               SQLCL_NO_INSTALL="1")
    r = subprocess.run([str(repo_root / "scripts" / "ensure-sqlcl.sh")],
                       capture_output=True, text=True, env=env, timeout=120)
    assert "does not run as SQLcl" in r.stderr, r.stderr
    assert str(_bin(tmp_path) / "sql") not in r.stdout, \
        "a non-SQLcl `sql` was adopted anyway"

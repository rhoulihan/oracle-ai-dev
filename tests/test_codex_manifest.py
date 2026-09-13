import json
from pathlib import Path


def _load(repo_root: Path) -> dict:
    return json.loads((repo_root / ".codex-plugin" / "plugin.json").read_text())


def _sqlcl(repo_root: Path) -> dict:
    return _load(repo_root)["mcpServers"]["sqlcl"]


def test_skills_path_and_empty_hooks(repo_root: Path):
    m = _load(repo_root)
    assert m["skills"] == "./skills/"
    assert m["hooks"] == {}, "Codex hooks must be a literal empty object"


def test_no_placeholders_survive_on_codex(repo_root: Path):
    """Codex performs NO ${} / env expansion in an MCP server's command, args or env —
    they reach Command::new() verbatim, so a ${...} would be a literal filename."""
    assert "${" not in json.dumps(_sqlcl(repo_root))


def test_launches_the_bundled_launcher_via_interpreter_and_cwd(repo_root: Path):
    """Parity with Claude Code: SQLcl self-installs on Codex too.

    Codex resolves a *relative cwd* against the plugin root (`"cwd": "."` == plugin
    root), but a relative `command` is explicitly platform-specific/unstable. So the
    supported pattern — the one OpenAI's own codex-security / openai-developers plugins
    use — is: PATH-resolvable interpreter as `command`, the bundled script as a relative
    `arg`, and `cwd: "."`.
    """
    s = _sqlcl(repo_root)
    assert s["cwd"] == ".", "cwd '.' is how Codex addresses the plugin root"
    assert s["command"] == "bash", "command must be PATH-resolvable, not a relative path"
    assert not s["command"].startswith("."), "relative commands are unstable on Codex"
    assert s["args"][0] == "./scripts/sqlcl-mcp.sh", "the launcher runs as a relative arg"


def test_codex_server_has_restrict_level_4(repo_root: Path):
    args = _sqlcl(repo_root)["args"]
    i = args.index("-R")
    assert args[i + 1] == "4", "restrict level 4 is a security MUST"
    assert "-mcp" in args


def test_java_home_is_forwarded_despite_env_clear(repo_root: Path):
    """Codex calls env_clear() on the MCP child — only HOME/PATH/SHELL/LANG/TMPDIR/...
    survive. JAVA_HOME must be named in env_vars, or the launcher's Java check would not
    see a JAVA_HOME-only JDK (and TNS_ADMIN would be lost for wallet connections)."""
    env_vars = _sqlcl(repo_root).get("env_vars", [])
    assert "JAVA_HOME" in env_vars, "JAVA_HOME is stripped by env_clear unless forwarded"
    assert "TNS_ADMIN" in env_vars, "wallet/tnsnames dir must survive env_clear"


def test_codex_raises_startup_timeout(repo_root: Path):
    assert _sqlcl(repo_root).get("startup_timeout_sec", 0) >= 60

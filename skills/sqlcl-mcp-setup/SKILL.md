---
name: sqlcl-mcp-setup
description: Use when connecting an AI agent or assistant to an Oracle database, or configuring the SQLcl MCP server. Sets up live database access for Claude Code and Codex with the right security posture.
---

# Wire SQLcl MCP for live database access

Oracle's SQLcl MCP server is the agent's database arm. This plugin bundles its
wiring — this skill saves a connection and starts the server safely on either
platform.

## SQLcl installs itself — on both platforms
Nothing to install by hand. Both manifests launch `scripts/sqlcl-mcp.sh`, which
resolves SQLcl (the optional `sqlcl_path`/`SQLCL_PATH` override → `sql` on PATH → the
plugin's own copy) and **downloads it if missing** (~143 MB, once). Idempotent and
lock-guarded — and the lock self-heals: if the process holding it dies without
cleaning up (SIGKILL, OOM, power loss), the next run reclaims it and installs.

**Java 17+ is required** — SQLcl is a Java program. `ensure-sqlcl.sh` checks
`JAVA_HOME`/PATH up front and fails with an explicit message (naming the version it
found) rather than downloading 143 MB that can't run or dying on a cryptic JVM error.

## Save a connection
The server sees **only** the plugin's isolated connection store,
`~/.oracle-ai-dev/dbtools-home` — the launcher appends `-home` with that path on
both platforms, so connections in the default `~/.dbtools` are invisible to it
(deliberate: the agent never sees your personal saved credentials). Create a
least-privilege user first (the `create-plugin-user` configurator), then save the
named connection **into that store**:

```
sql -home ~/.oracle-ai-dev/dbtools-home /nolog
SQL> conn plugin_dev/<password>@localhost:1521/FREEPDB1 -save dev -savepwd
```

A plain `conn -save` (no `-home`) lands in `~/.dbtools`, and the server's
`connections_list` will come back empty.

## Start it safely
See [MCP tools & security](references/mcp-tools.md). The critical rule: the server
launches with **`-R 4`** (restrict level 4) — verified NOT to be the default on the
26.2 binary, and security-critical (it blocks host-shell execution). The bundled
`.mcp.json` (Claude) and `.codex-plugin/plugin.json` (Codex) both set it.

## Platform wiring
- **Both platforms** launch `scripts/sqlcl-mcp.sh -mcp -R 4`; the launcher appends
  `-home ~/.oracle-ai-dev/dbtools-home` so the agent-visible connection store is the
  same everywhere (Codex can't expand `${}` placeholders, so the path lives in the
  script, not the manifests).
- **Claude Code:** `.mcp.json` runs `${CLAUDE_PLUGIN_ROOT}/scripts/sqlcl-mcp.sh` and a
  `SessionStart` hook pre-warms the install. `sqlcl_path` is an optional override.
  Manual alternative:
  `claude mcp add sqlcl <path>/sql -- -mcp -R 4 -home ~/.oracle-ai-dev/dbtools-home`.
- **Codex:** Codex does **no** `${}` expansion (command/args/env reach `Command::new()`
  verbatim) and a *relative command* is platform-unstable — but it **does** resolve a
  relative `cwd` against the plugin root. So the server runs
  `command: "bash"`, `args: ["./scripts/sqlcl-mcp.sh", "-mcp", "-R", "4"]`, `cwd: "."`
  — the same pattern OpenAI's own plugins use. Codex `env_clear()`s the MCP child, so
  `JAVA_HOME`/`TNS_ADMIN`/`SQLCL_PATH` are forwarded via `env_vars`.
- **Windows:** both paths need a POSIX shell (`bash`); otherwise put `sql` on PATH.

When the server will not start at all, the two environment causes — an
uninherited Java and an empty `TNS_ADMIN` — are in
[launch failures](references/launch-failures.md).

## Sources
- Using the SQLcl MCP Server (26ai) —
  https://docs.oracle.com/en/database/oracle/sql-developer-command-line/

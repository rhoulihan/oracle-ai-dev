# SQLcl MCP tools & security

## The tools (runtime-verified, SQLcl 26.2)
The live server exposes **nine underscore-named tools** — the hyphenated names in
the docs (`run-sql`, etc.) fail at runtime:

`connect`, `disconnect`, `connections_list`, `sql_run`, `sqlcl_run`,
`schema_information`, `skills_sync`, `request_status`, `annotation_generate`.

Skills name *actions* ("run this SQL against the connected database"), not these
tool names. `skills_sync` installs Oracle's own skills into detected agent skill
directories — relevant when reconciling with `oracle/skills`.

## Security posture
- **`-R 4` is mandatory, not default.** On the 26.2 binary, plain `sql -mcp` ran
  host shell via `sqlcl_run`. The bundled configs launch with `-R 4`, which blocks
  the restricted SQLcl *client commands* — `host`, `spool`, `@`/`start` scripts,
  and the `ddl` DDL-generation command — while SQL, schema inspection, and the
  tuning workflow still work.
- **`-R 4` is NOT a database write guard.** Restrict levels gate SQLcl commands,
  not SQL: DDL and DML statements through `sql_run` (`CREATE TABLE`, `DROP TABLE`,
  …) still run at `-R 4` (runtime-verified — gap-3 §3.5, gap-1 §5.3; the tuning
  loop depends on this to create indexes over MCP). `-R 4` stops the model from
  shelling out on the launch host; what limits database damage is the
  least-privilege DB user.
- **No server-side read-only flag.** The guardrail is a least-privilege DB user
  (`plugin_dev`, from the configurator) plus `-R 4`, plus the Class A–E action
  labelling.
- **Auditing:** `DBTOOLS$MCP_LOG` records tool calls in the connected schema;
  queries are tagged with the model in use.

## Async queries
`sql_run` supports an async job pattern (job id + status/results/cancel) for
long-running statements — useful so the agent isn't blocked.

## Sources
- Using the SQLcl MCP Server (26ai) —
  https://docs.oracle.com/en/database/oracle/sql-developer-command-line/

from pathlib import Path

S = "skills/sqlcl-mcp-setup"


def test_mcp_tools_states_what_r4_actually_gates(repo_root: Path):
    # gap-3 SS3.5 / gap-1 SS5.3 (runtime-verified): restrict levels gate SQLcl
    # *client commands* (host, spool, @/start scripts, the `ddl` generation
    # command), NOT SQL — CREATE/DROP TABLE via sql_run SUCCEED at -R 4. The
    # security reference must not promise that -R 4 blocks DDL statements.
    t = (repo_root / S / "references/mcp-tools.md").read_text().lower()
    assert "arbitrary-ddl" not in t and "arbitrary ddl" not in t
    assert "host" in t and "spool" in t
    # must state that SQL DDL/DML still executes at -R 4
    assert "not sql" in t or "still run" in t or "still execute" in t
    # the real database guardrail is the least-privilege DB user
    assert "least-privilege" in t

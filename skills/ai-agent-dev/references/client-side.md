# Client-side agents with Oracle as the data layer

The most common shape: the agent runs in your app; Oracle is its memory and tools.

## Oracle as the stores
- **Vector store / knowledge:** embeddings + IVF index (the `vector-rag-dev` skill).
  Retrieval is a `VECTOR_DISTANCE` query, optionally hybrid with text/relational.
- **State / memory:** a JSON collection or relational table for conversation state,
  scratchpads, and results — with real transactions.

## The database arm: SQLcl MCP
Wire the SQLcl MCP server (the `sqlcl-mcp-setup` skill) as a tool so the agent can
query and inspect the schema. It runs at restrict level 4 and against a
least-privilege `plugin_dev` user — the guardrails, since there is no server-side
read-only flag.

## Safe tool execution (approval-gated)
Destructive or write tools should require explicit user approval before the result
is applied — the pattern from Oracle's APEX ai-helpdesk workshop
(`apex_ai.set_tool_result` gated on approval). Read tools (queries, plans) can run
freely; writes and DDL are Class D/E and confirm first.

## Frameworks
Oracle ships client integrations: `langchain-oracledb` (OracleVS vector store),
`llama-index-vector-stores-oracledb`, and the async `python-oracledb` pool for
high-concurrency agents.

## Sources
- Oracle AI Vector Search User's Guide (26ai) — https://docs.oracle.com/en/database/oracle/oracle-database/26/vecse/
- Agent-tool safety patterns — field-verified, 2025–2026.

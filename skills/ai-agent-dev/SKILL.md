---
name: ai-agent-dev
description: Use when building AI agents that use Oracle as memory, knowledge, or tools — client-side agent frameworks with Oracle as the data layer, or in-database agents with Select AI. Covers the safe tool patterns and the SQLcl MCP database arm.
---

# AI agents on Oracle

Two tiers, depending on where the agent runs.

## Client-side (primary)
Build the agent in a framework (Claude API, OpenAI Agents SDK, LangChain) with
Oracle as the vector store, state store, and knowledge base, and the SQLcl MCP
server as the agent's database arm. See [client-side](references/client-side.md)
for the store patterns, MCP wiring, and approval-gated tool execution.

## Agent memory (Oracle Agent Memory pattern)
Give the agent durable memory the way the Oracle agent-memory labs do: a memory row
with a `VECTOR` embedding, projected as an updatable JSON **duality view**, revised
via `superseded_by`, recalled by `VECTOR_DISTANCE`. One Oracle holds every memory
type — working, episodic, semantic facts, procedural, RAG, chat history — and the
`oracleagentmemory` / LangGraph (`AsyncOracleSaver`, `OracleSemanticCache`) stack
drops straight onto this install. See [agent memory](references/agent-memory.md)
for the schema, recall query, and the install options it needs (server-side
embedding model, `db-ords` for the Mongo API).

## In-database (Select AI)
Run NL2SQL, RAG, and agent workflows inside the database with Select AI. On Free
this needs a one-time manual install — see [in-database Select AI](references/in-db-select-ai.md).

## Remote MCP for teams
Locally, SQLcl MCP (stdio) is the default. For a shared team endpoint, ORDS 26.2
exposes a streaming-HTTP `/mcp` endpoint (standalone mode, external OAuth2/JWT).

## Sources
- Oracle Select AI documentation (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/

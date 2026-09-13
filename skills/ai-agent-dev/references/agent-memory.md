# Agent memory on Oracle (the Oracle Agent Memory pattern)

Oracle AI Database is a single memory core for agents: vector, JSON, graph, and
relational under one transaction. This is the shape the Oracle agent-memory labs
use — the [Oracle AI Agent Memory package](https://github.com/oracle-devrel/oracle-ai-developer-hub)
(`oracleagentmemory`: users/agents, memories, threads with automatic extraction and
vector retrieval) and the **Agent Memory Workshop** (a `MemoryManager` over the
memory types below). Build memory-compatible with those labs, or wire the labs'
Python API straight onto this install.

## The memory record: vector + updatable duality view
A memory is a normalized row with an embedding, projected as one updatable JSON
document through a duality view — so the agent reads/writes a document while Oracle
keeps the relational record transactional.

```sql
CREATE TABLE agent_memories (
  id VARCHAR2(64) PRIMARY KEY, session_id VARCHAR2(64) NOT NULL,
  content VARCHAR2(4000) NOT NULL, embedding VECTOR(384, FLOAT32),
  superseded_by VARCHAR2(64));                    -- fact revision, not delete
CREATE TABLE agent_memory_tags (                  -- indexable child attributes
  tag_id VARCHAR2(64) PRIMARY KEY,
  mem_id VARCHAR2(64) NOT NULL REFERENCES agent_memories(id) ON DELETE CASCADE,
  tag VARCHAR2(64) NOT NULL);
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW agent_facts AS
  agent_memories @insert @update @delete
  { _id: id, sessionId: session_id, content, supersededBy: superseded_by,
    tags: agent_memory_tags @insert @update @delete { tagId: tag_id, tag } };
```

Write pipeline (as the labs do): `INSERT` the record through the duality view, then
`UPDATE` its `embedding` server-side. Revise a fact by setting `superseded_by`, not
by deleting — recall filters superseded rows out, keeping an audit trail.

## Recall (COSINE, superseded-aware)
```sql
SELECT id, content FROM agent_memories
WHERE session_id = :sid AND superseded_by IS NULL
ORDER BY VECTOR_DISTANCE(embedding,
  VECTOR_EMBEDDING(all_minilm_l12_v2 USING :query AS DATA), COSINE)
FETCH FIRST :k ROWS ONLY;
```
Add an IVF vector index (`ORGANIZATION NEIGHBOR PARTITIONS DISTANCE COSINE`) for
approximate recall at scale; combine with the `tags` child or a text index for
hybrid retrieval.

## Memory types → Oracle shapes (the workshop's six)
- **Working / short-term** — the live turn, held in a session row or JSON collection.
- **Episodic** — past events/interactions, one memory row each, vector-recalled.
- **Semantic / long-term facts** — durable user facts (the schema above), `superseded_by` for revision.
- **Procedural** — reusable routines/tools, referenced by name.
- **Retrieval / RAG** — a document KB over the same vector machinery ([vector-rag-dev](../../vector-rag-dev/SKILL.md)).
- **Chat history** — the transcript, a JSON collection or relational log.

## Framework wiring (same DB)
The LangChain/LangGraph ecosystem persists all of it in one Oracle: `OracleVS`
(vector store), `AsyncOracleSaver` (LangGraph checkpointer), `OracleSemanticCache`
(meaning-equivalent prompt reuse), and Oracle chat message history. Install the labs'
own Python APIs onto this stack with the optional extra:
`pip install -r requirements-agent-memory.txt` (`oracleagentmemory`,
`langchain-oracledb`, `llama-index-vector-stores-oracledb`).

## Install prerequisites (the options that make this compatible)
- **Server-side embedding** — `VECTOR_EMBEDDING()` needs the ONNX model loaded. One
  command downloads, stages, grants, loads, and verifies it:
  `setup-embedding-model.sh <container> <pdb> <user> <password>`
  ([embeddings](../../vector-rag-dev/references/embeddings.md)). Until it runs, embed
  client-side and store the vector — the stack-validation test skips the server-side
  check with this exact hint when no model is present.
- **Mongo-API memory store** — to read/write memories over the MongoDB API, bring up
  the `db-ords` compose profile ([compose profiles](../../oracle-ai-setup/references/compose-profiles.md)).
- **Grants** — memory tables/views need `CREATE TABLE`/`CREATE VIEW` (the least-priv
  `plugin_dev` user has these). Loading the embedding model additionally needs
  `CREATE MINING MODEL` + `READ` on the staged directory — `setup-embedding-model.sh`
  grants both to the target user as part of the install.

This pattern is validated live in `tests/test_stack_validation.py`
(`test_agent_memory_duality_and_vector_recall`): insert-through-duality, COSINE
recall, and `superseded_by` revision, all on 26ai Free.

## Sources
- Oracle AI Agent Memory / labs — https://github.com/oracle-devrel/oracle-ai-developer-hub
- Building agentic memory on Oracle AI Database — vector embeddings + duality views as the memory core.

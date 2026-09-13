# Help — at the depth you need

Four levels: **overview** (what each path is) → **common tasks** (what you'd ask
for) → **reference** (the deep docs) → **troubleshooting** (errors with fixes).
Ask for "help", "help &lt;path&gt;", or "help &lt;topic&gt;" and the router takes you
to the matching depth.

---

## Level 1 — Overview: the paths

| Path | Skill | Use it when |
|---|---|---|
| Set up | `oracle-ai-setup` | You need the Free stack running in Docker and its features enabled. |
| Connect an agent | `sqlcl-mcp-setup` | You want an AI agent to reach the database live (SQLcl MCP). |
| Model the data | `oracle-data-modeling` | You're designing/reviewing a schema and want the shape chosen by measurement. |
| Documents — SQL | `sql-json-dev` | You store/query JSON with SQL (`JSON_TABLE`, collection tables, JSON indexes). |
| Documents — duality | `json-duality-dev` | One dataset must serve both relational and document consumers. |
| Documents — Mongo API | `mongodb-api-dev` | You run a MongoDB app/driver/mongosh against Oracle, or migrate one. |
| Documents — in-DB | `soda-dev` | You do document CRUD/QBE from PL/SQL, MLE JavaScript, or SQLcl. |
| Documents — DynamoDB API | `adb-dynamodb-api` | You run a DynamoDB app or AWS SDK against Autonomous Database, or migrate one. |
| Headless SQL on ADB | `ords-rest-sql-headless-adb` | You must run SQL against a wallet-less ADB from a script or CI, with no SQLcl. |
| Vector & RAG | `vector-rag-dev` | You add embeddings, semantic/hybrid search, or RAG. |
| AI agents | `ai-agent-dev` | You use Oracle as agent memory, knowledge, and tools. |
| Write queries | `query-craft` | You author SQL, SQL/JSON path, or graph queries. |
| Tune queries | `query-tuning` | A query is slow or a plan regressed. |

---

## Level 2 — Common tasks

**Setup & connect**
- *Stand up a database* → setup: pick a compose profile (`db` or `db-ords`), run it, wait for healthy.
- *Enable a feature* → setup: the idempotent configurators in `assets/tooling/configure/` (vector memory, Mongo API, SODA, duality/GraphQL, property graph, Select AI, Text index).
- *Connect from Python/Node/Java/Go/.NET/mongosh* → the [access matrix](../../oracle-ai-setup/references/access-matrix.md); generate a connection kit with `scripts/gen-connection-kit.sh`.
- *Connect an AI agent* → sqlcl-mcp-setup (launch SQLcl MCP with `-R 4`).

**Model & optimize**
- *Model my domain* → modeling: the intake interview → a shape recommendation per access pattern.
- *Which shape is fastest?* → [measured optimization](../../oracle-data-modeling/references/optimization.md): generates the query per shape, benchmarks, ranks the options.
- *Run the measured election* → seven designs walked document → single collection → hybrid → duality → summary → relational (plus the `sql_view` projection), each entity carrying four
  storage dimensions — partition · IOT · advanced compression · hybrid flex `LIMIT`, off with `--no-partition`/`--no-iot`/`--no-compress`/`--flex-limit N`/`--no-flex-limit`
  ([storage mechanics](../../oracle-data-modeling/references/storage-mechanics.md)).
- *Record our org standards* / *"capture that as a lesson"* → [local knowledge](../../oracle-data-modeling/references/local-knowledge.md): the committable `.oracle-ai-dev/` store
  (standards govern, lessons inform) and the one-time gap-fill against the shipped [operating principles](../../oracle-data-modeling/references/operating-principles.md).
- *Balance reads vs writes* → the write-amplification model; the read/write frequency knob flips the winner.
- *One model for all my patterns* → `recommend_model`: the deterministic union optimizer, with washout + latency-budget warnings.
- *Reverse-engineer a model* → `tooling/generate/ingest.py`: from documents, DDL (Oracle/Postgres/MySQL/SQL Server), `$jsonSchema`, or Mongoose.
- *Optimize against my real DB* → `run-sql.sh` wallet/easy mode + a sized sample (`scale-seed.sql`, `sizing.py`).
- *Reset/init a benchmark target* → `db-lifecycle.sh status|init|load|reset|new-project`.

**Build**
- *Generate a data layer* → `python -m tooling.datalayer <spec.json> <out> [--platforms …]`; ships schema DDL + deploy + `ensure_schema`.
- *Migrate a Mongo app* → mongodb-api-dev: the three-lane migration framework.
- *Add vector search / RAG* → vector-rag-dev (IVF is zero-config; HNSW needs vector memory).

**Query & tune**
- *Write a query* → query-craft (SQL, SQL/JSON path, graph).
- *My query is slow* → query-tuning: measure → hypothesize → change → re-measure.

---

## Level 3 — Full reference
Each skill's `references/*.md` holds the deep detail — all options, syntax, and
Oracle Version Notes. Highest-value references:
- Modeling: [umt-methodology](../../oracle-data-modeling/references/umt-methodology.md),
  [decision-rules](../../oracle-data-modeling/references/decision-rules.md),
  [optimization](../../oracle-data-modeling/references/optimization.md),
  [patterns](../../oracle-data-modeling/references/patterns.md),
  [storage-mechanics](../../oracle-data-modeling/references/storage-mechanics.md).
- Standards & lessons: [local-knowledge](../../oracle-data-modeling/references/local-knowledge.md),
  [operating-principles](../../oracle-data-modeling/references/operating-principles.md).
- Setup: [access-matrix](../../oracle-ai-setup/references/access-matrix.md).
- Architecture: `docs/ARCHITECTURE.md`. End-to-end: `docs/WALKTHROUGH.md`.

---

## Level 4 — Troubleshooting
Hit an error? See [troubleshooting](troubleshooting.md) — the ORA-* errors with
cause and fix (ORA-40477 duality PK, ORA-06598 ORDS enable-schema, ORA-01403
transient, ORA-43853 JSON in SYSTEM, ORA-51962 HNSW vector memory, ORA-00054 SODA
index-in-txn, ORA-12954 12 GB cap, ORA-29833 Text on slim image), plus the Mongo
API caveats (no vector/text/change-streams on Free) and the connection-string
requirements. If you're optimizing an external system and an operation is
**REFUSED**, that's the safety guard — set `OPT_ALLOW_EXTERNAL_WRITES=1` only
against a dedicated benchmark schema.

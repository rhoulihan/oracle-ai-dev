---
name: oracle-ai-dev
description: Use when starting OR migrating an Oracle AI Database project — building a new app, or moving an existing app/database/workload to Oracle ("migrate X to Oracle", from MongoDB, PostgreSQL, MySQL, SQL Server, or DynamoDB) — choosing a development path or feature, sizing a Free deployment, or when a developer wants recommendations or feedback on their requirements or architecture. Routes to the setup, migration, modeling, document, vector/RAG, agent, query, and tuning paths.
---

# Oracle AI Database 26ai — Developer Guide (Router)

This is the front door for building on Oracle AI Database 26ai Free. Pick the path that matches the goal; see `references/routing.md` for the decision table.

## Development paths
- **Set up the database** — install and configure the Free stack in Docker.
- **Migrate an existing app** — reverse-engineer a model from your current DDL
  (Oracle/PostgreSQL/MySQL/SQL Server), example documents, `$jsonSchema`, a Mongoose
  schema, or a DynamoDB export (`tooling/generate/ingest.py`); review it; then pick the
  target shape and path (a MongoDB workload → the Mongo-compatible API + mongosh→SQL
  translation; a relational app → SQL/JSON or duality).
- **Model the data** — choose the right data shape for the access patterns (converged modeling).
- **Documents** — JSON with SQL, JSON Relational Duality, the MongoDB-compatible API, or SODA.
- **Vector search & RAG** — embeddings and semantic search, offline-first on Free.
- **AI agents** — use the database as memory, knowledge, and tools.
- **Write & tune queries** — author SQL/JSON and run a measure-driven tuning loop.

## How to use
Ask the developer what they are trying to **build or migrate**, then follow the matching path. For a migration ("I want to migrate X to Oracle"), start by ingesting what they already have (DDL, documents, `$jsonSchema`, Mongoose, or a DynamoDB export) into a ModelSpec, then run the modeling skill in **brownfield/review** mode over it before routing to the target path. When the goal is unclear or spans several paths, or the developer brings requirements or a spec, act as the [advisor](references/advisor.md): run the intake, produce a recommendation, and critique what they gave you before routing. On the first use in a project — no `.oracle-ai-dev/standards.md` yet — run the one-time operating-principles gap-fill from the [advisor](references/advisor.md) flow and record the outcomes. Always confirm the target is the local Free container before running anything that changes state.

## Help
Need help at any depth? See [help](references/help.md) — overview, common tasks,
full reference, and [troubleshooting](references/troubleshooting.md) (the ORA-*
errors with cause and fix).

## Sources
- Oracle AI Database 26ai documentation — https://docs.oracle.com/en/database/oracle/oracle-database/26/

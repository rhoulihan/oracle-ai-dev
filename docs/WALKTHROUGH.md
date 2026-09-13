# oracle-ai-dev — end-to-end walkthrough

A developer (or their coding agent) going from nothing to a working, tuned Oracle
AI Database 26ai app. Every step maps to a skill the plugin ships; the agent runs
these for you when you describe the goal in natural language.

**You don't type these commands.** That's what the skills are for — the agent
executes the scripts on your behalf (asking approval before anything that writes or
touches an external system), and each configurator emits `ASSERT:<name>:PASS` so the
agent can confirm it worked. The commands are shown here only so you can see exactly
what runs under the hood.

## 0. Install

**Claude Code**
```
/plugin marketplace add rhoulihan/oracle-ai-dev
/plugin install oracle-ai-dev@oracle-ai-dev-marketplace
```
**Codex**
```
codex plugin marketplace add rhoulihan/oracle-ai-dev
# then install oracle-ai-dev from /plugins
```
The bundled SQLcl MCP server gives the agent live database access (launched with
`-R 4`; wired for both platforms). **SQLcl installs itself** — the MCP server launches
through `scripts/sqlcl-mcp.sh`, which resolves SQLcl (your optional `sqlcl_path` → `sql`
on PATH → the plugin's own copy) and downloads it if missing, so there is nothing to
install by hand. A `SessionStart` hook pre-warms it in the background so it never
delays MCP startup. (SQLcl needs Java 17+.)

## 1. "I want to build X on Oracle" (or "migrate X to Oracle") → the advisor (S0)

Tell the agent what you're building — **or migrating**. The **oracle-ai-dev** router
runs the architecture intake, then produces a plan: which paths to follow, which
features to enable (with the exact configurators to run), the compose profile, and an
honest critique of anything that won't work on Free — e.g. it will tell you vector
search does *not* work through the Mongo API on Free and route you to native SQL. For a
**migration**, it first reverse-engineers a model from what you already have — DDL
(Oracle/PostgreSQL/MySQL/SQL Server), example documents, `$jsonSchema`, a Mongoose
schema, or a DynamoDB export (`tooling/generate/ingest.py`) — and reviews it before
recommending the target shape and path (a MongoDB workload routes to the
Mongo-compatible API + the mongosh→SQL translation cookbook).

On its **first use in a project** the router also runs a one-time gap-fill: it
compares its shipped operating-principles corpus
(`skills/oracle-data-modeling/references/operating-principles.md`) against your own
`CLAUDE.md`/`AGENTS.md`, stays silent on everything you already cover, asks once about
the real gaps, and records each adopt/decline in `.oracle-ai-dev/standards.md` — which
it then reads before every modeling session, and never asks about again. That store is
two plain committable files: `standards.md` (org directives **and** adopted principles —
it governs) and `lessons.md` (what this project has measured — it informs). Your
standards outrank the shipped defaults, with three carve-outs that never yield: the
destructive-operation override, nothing-identifying-ships, and the claims guardrails.

## 2. Stand up the database → setup (S1)

The setup skill brings up the stack and enables exactly the features the advisor
recommended — the agent runs these; you just approve. What it runs:
```
docker compose -f assets/compose/db.compose.yml up -d           # DB only
# or db-ords.compose.yml for the MongoDB API / REST / GraphQL
```
Warm start is ~11s (the image ships a healthcheck). Then the idempotent configurators
(each prints `ASSERT:<name>:PASS`, which the agent checks):
```
assets/tooling/configure/create-plugin-user.sh <conn>
assets/tooling/configure/enable-vector-memory.sh <sysdba>        # if you want HNSW
assets/tooling/configure/setup-embedding-model.sh <c> <pdb> <u> <pw>  # in-DB embeddings
assets/tooling/configure/doctor.sh <conn>                        # what's on/off
```

## 3. Model the data → UMT modeling (S3)

Describe your domain and access patterns. The modeling skill runs the UMT
interview (returns as `entity.property`, frequency, cardinality, latency, write
intensity), then the deterministic recommender picks a physical **shape** per
pattern and cites the rule: a write-hot cart → single collection; an order shown to
a customer → duality view; a single-entity profile → JSON collection. Any duality
DDL must clear the mechanical design gates (root/key laws, ETag scope, write-path
opt-ins), and recommendations lean on field lessons measured in real engagements. To follow
along, the skill loads the canonical restaurant example for you:
```
# as an app user on the USERS tablespace (not SYSTEM — JSON needs ASSM)
sqlplus demo/... @assets/seed/01-canonical.sql   # ... through 06-seed-data.sql
sqlplus demo/... @assets/verify/verify-seed.sql  # every line ASSERT:*:PASS
```

## 4. Prove the shape choice → measured optimization

When the tradeoff is close, don't guess — benchmark. The agent **reasons** about candidate
models; the tooling **measures** them. The six steps are codified, so the agent runs one
command rather than reassembling the loop each time:

```bash
python -m tooling.optimize <workload.json> --fresh --out ./out    # ~65s end to end
```

1. **The walk competes by default** — `document → single collection → hybrid → duality →
   summary → relational`, the six stations a design moves through as write pressure climbs
   (with `sql_view` as a seventh design — a read-only projection, never a station). The
   single collection's keys and the duality views are **derived** from the result sets, the
   filters and the relationships, not hand-drawn; `hybrid` (a relational core plus one JSON
   flex column per entity, on its own `_h` lane) and `summary` (a relational `_s` lane plus
   `REFRESH FAST ON COMMIT` aggregate MVs) are auto-nominated by heuristic when you don't
   declare them. **Four storage dimensions compose with all of it** and are measured in the
   same election — `partition` (`interval`/`auto_list`/`hash`, making retention a
   metadata-only drop), `organization: "index"` (an IOT with an `OVERFLOW` segment),
   `compress: "advanced"`, and the hybrid flex `LIMIT` — each with a `--no-…` flag that
   measures the same design without it, so the counterfactual costs one run.
2. **Indexes first.** Derived from what the patterns actually do — their **filters *and* their
   aggregations** — and deployed before anything is measured, so you never benchmark a full
   scan production would never run.
3. **Equivalence before speed.** Every design must return the *same answer* for every pattern,
   or its cells are not timed at all. A design that returns less is faster, and a stopwatch
   cannot tell the difference.
4. **Measure, then explain.** The matrix is built in one consistent unit (median elapsed µs —
   logical reads and redo bytes are different units and cannot be summed), and the **execution
   plan for every cell** is captured and reported: a filtered read that full-scans is a
   *warning*, not a datapoint.
5. **Decide, honestly.** Writes are first-class rows. A margin inside the noise floor prints
   `TOO CLOSE TO CALL` rather than asserting a winner — and the verdict discloses what it
   cannot prove. `decided by: point reads` means the margin **carries to Exadata-class
   deployments** (buffer-cache point reads never offload); `decided by: scan economics` means
   it is environment-conditional, because smart scan cheapens exactly that side. A deciding
   cell that answered fewer rows than the pattern's declared `expect_rows` is flagged
   `!! PROVISIONAL` — production cardinality unproven, re-seed before trusting it. And when
   `summary` competes, `SUMMARY MAINTENANCE` prints the per-write-pattern summary-vs-relational
   delta: the MV upkeep is inside summary's `execute + COMMIT` cells while every other design's
   writes roll back, so the bias runs *against* summary and is disclosed, not corrected.
6. **Turn the knob for free.** A cell is a property of the schema, not of how often the pattern
   runs — so named workload scenarios are a *re-weighting of measurements already taken*. One
   measurement pass, many workloads, and you watch the winner move.

Point it at the local container or, via a wallet, your **own system** with a sized
sample (`run-sql.sh`, `db-lifecycle.sh` — external writes are refused without an
explicit override). Driven for you by the modeling skill.

## 4b. Turn the model into code → the data layer
The data-layer skill generates it for you:
```
python -m tooling.datalayer <spec.json> <out_dir> [--platforms py,node,java,go,dotnet]
```
Each access pattern becomes a bind-by-name method per runtime; the archive ships the
schema DDL (with the derived indexes), `deploy.sh`, and `ensure_schema`.

## 5. Build a path

- **Documents in SQL** → `sql-json-dev` (S4): JSON_TABLE, indexing (multivalue vs
  search index), and the mantra — dot notation first, item methods preserve the
  type, `JSON_VALUE RETURNING` as last resort.
- **Both rows and documents** → `json-duality-dev` (S5): `order_dv`, full-child-PK
  rule (avoids ORA-40477).
- **A MongoDB app** → `mongodb-api-dev` (S6): connect with `tls=true`, the three-lane
  migration framework.
- **Semantic search / RAG** → `vector-rag-dev` (S8): IVF by default, offline ONNX
  embeddings; `VECTOR_DISTANCE ... FETCH APPROX`.
- **An AI agent** → `ai-agent-dev` (S9): Oracle as vector/state store, SQLcl MCP as
  the DB arm, approval-gated tools.

## 6. Make it fast → tuning (S11)

The measure-driven loop: baseline the plan (`DBMS_XPLAN`), hypothesize, change one
thing, re-measure. The Diagnostics and Tuning packs are **licensed on Free**, so
SQL Tuning Advisor, AWR, ASH, and ADDM all work — the skill uses them (and knows to
create PDB-local AWR snapshots inside FREEPDB1).

---

Every claim here is backed by hands-on verification on Oracle 26ai Free — see the
live tests (`pytest -m live`), which also run nightly in CI as **two serialized passes**
(the self-managed compose stacks first, then the shared-container pass — one container
name, so they cannot interleave; the `shared_container` marker is the contract), and
the end-to-end [capstone integration test](capstone-airline-integration.md) that runs
this whole flow against the real airline-reservations model and validates the
generated data layer identical across all five runtimes.

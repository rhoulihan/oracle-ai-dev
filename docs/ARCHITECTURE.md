# Architecture

How oracle-ai-dev is put together and why. Three layers — **skills** (what the
agent reads and reasons with), **tooling** (pure-Python logic), and **assets**
(the runnable side) — plus dual-platform packaging.

## Design principles

- **Measured, not dogmatic.** The optimizer never asserts a winning shape; it
  generates the query for each shape, benchmarks with deterministic server-side
  metrics, and ranks. The winner varies with the read/write knob.
- **Pure logic separated from execution.** Everything in `tooling/` is a pure
  function of a spec or a set of measured numbers — no database access, no I/O.
  All DB contact lives in `assets/` scripts and the gated live tests. This keeps
  the logic unit-testable and fast.
- **Specs are first-class.** A ModelSpec (entities, columns, relationships,
  projections) and QuerySpecs (result set + predicates + ordering) drive
  everything. They can be hand-authored or reverse-engineered.
- **Safe by default on external systems.** Destructive/write operations are
  refused on non-local targets without an explicit override.
- **The project's standards outrank ours.** Shipped operating principles are
  defaults; an `active` directive in the project's own `.oracle-ai-dev/standards.md`
  displaces them — except the three non-overridable ones (the destructive-operation
  override requirement, nothing-identifying-ships, and the claims guardrails), which
  are refused by name when a standard collides with them.
- **Dual-platform.** One repository installs on Claude Code and OpenAI Codex.

## Layer 1 — `skills/`

Twelve skills, each a `SKILL.md` (the agent-facing instructions) plus a
`references/` folder of deep docs. `oracle-ai-dev` is the **router/advisor**: it
runs the intake, recommends paths and features, and dispatches. `oracle-data-
modeling` owns the **measured optimizer** and its references — including the
duality design-gate rulebook (`duality-design-gates.md`), field-hardened war
stories (`field-lessons.md`), the never-claim list (`claims-guardrails.md`), the
physics under the storage dimensions (`storage-mechanics.md`), the shipped
defaults the gap-fill reconciles (`operating-principles.md`), and the
project-local store's contract (`local-knowledge.md`). The document paths
(`sql-json-dev`, `json-duality-dev`, `mongodb-api-dev`, `soda-dev`), plus
`vector-rag-dev`, `ai-agent-dev`, `query-craft`, `query-tuning`, `oracle-ai-setup`,
and `sqlcl-mcp-setup` cover the rest. Multi-level help lives in the router's
`references/help.md` + `troubleshooting.md`.

## Layer 2 — `tooling/` (pure Python)

One line per module — the guarantees each one carries are spelled out in
prose right below the tree.

```
tooling/
  generate/
    model.py     the ModelSpec/QuerySpec validators, plus the routing
                 predicates (duality_supports, summary_mv_for)
    sql.py       the query generator — one query per design, from
                 ModelSpec + QuerySpec
    ddl.py       the DDL generator — tables, lanes, storage dimensions,
                 and the access-pattern-derived indexes
    ingest.py    reverse-engineer a ModelSpec (documents, DDL x4 dialects,
                 $jsonSchema, Mongoose)
  optimize/
    runner.py    the measured election, end to end — `python -m tooling.optimize`
    equivalence.py  the shape-independent canonical answer (the gate that
                 runs before any timing)
    analyze.py   post-election analysis: weighted read+write cost,
                 break-points, recommend_design_options, recommend_model
    sizing.py    recommend a representative-but-bounded sample size
    safety.py    the external-write policy (single source of truth)
    benchparse.py  parse the BENCH:<label>:… line the SQL harness emits
    patterns.py  the 17-pattern catalog + model-aware generic naming
  datalayer/
    generate.py  bound_sql — the parameterized (bind-variable) form of
                 every generated query, for the emitted data layer
    platforms.py render a DAO per platform + schema.sql + deploy.sh
    __main__.py  the CLI
```

**What the DDL generator guarantees** (`ddl.py`; each rule is pinned by a
unit test named for the defect it prevents — `tests/test_dot_notation_first.py`,
`tests/test_hybrid_shape.py`, `tests/test_partition_dimension.py`,
`tests/test_iot_compress.py`, `tests/test_summary_design.py`):

- **Indexes are derived from the access patterns** — from their filter
  predicates *and* their `GROUP BY`/aggregate arguments, never hand-listed.
  The expression a query uses and the expression its index is built on come
  from one shared helper (`agg_expr`), because an index whose expression
  differs from the query's by a single character is built, valid, and
  silently ignored — four separate field defects had exactly that shape.
- **Every design owns its storage.** The hybrid design builds `<table>_h`
  copies carrying the `flex JSON (OBJECT LIMIT 8192)` column; the summary
  design builds `<table>_s` copies plus its MV logs and
  `REFRESH FAST ON COMMIT` aggregate materialized views. Shared tables
  would let one design's storage cost leak into another's measured cells.
- **The per-entity storage dimensions emit here**, in the clause order the
  live engine accepts: the partition clause (interval / auto_list / hash,
  with derived indexes `LOCAL` by default), `ROW STORE COMPRESS ADVANCED`,
  and `ORGANIZATION INDEX [PCTTHRESHOLD n] [INCLUDING col] OVERFLOW`.
  Combinations the engine rejects (an IOT with row compression, with a
  non-hash partition, or with hybrid flex properties) are refused at
  validation time with the ORA number the deploy would have raised.

**What the election runs** (`runner.py`), in order:

1. Deploy every candidate design — the six walk stations (document →
   single collection → hybrid → duality → summary → relational; `sql_view`
   is the seventh design, a projection, never a station), with the single
   collection's keys, the duality views, and the hybrid/summary
   nominations all derived from the patterns when not declared.
2. Seed every design identically, deriving the co-located lanes from the
   relational rows.
3. **Validate answers**: every design must return the same canonical
   answer for every pattern (`equivalence.py`) or its cell is invalid — a
   design that returns less is faster, and a stopwatch cannot tell.
4. Measure every pattern × design cell on the live database, capturing
   each cell's execution plan.
5. Decide — rate-weighted over reads and writes, refusing a verdict
   inside the noise floor (`TOO CLOSE TO CALL`).
6. Re-weight into any named workload scenarios and emit the winning DDL,
   built exactly as it was measured.

The report also **discloses what the run cannot prove**: `decided by:`
(a point-read-decided margin carries to Exadata-class deployments; a
scan-decided one is environment-conditional), `!! PROVISIONAL` (a deciding
cell answered fewer rows than the pattern's declared `expect_rows` —
production cardinality unproven), and `SUMMARY MAINTENANCE` (the summary
design's per-write-pattern cost beside relational's; its cells include a
commit other designs' rolled-back cells do not, a bias that runs against
summary and is disclosed rather than corrected).

The query generator compiles multi-hop joins (BFS over the relationship
graph, reserved-word-safe aliases), the full predicate set (incl. JSON-path
array filters), `ORDER BY`/`FETCH FIRST`, computed/COALESCE projections,
hierarchies in all three realizations (`CONNECT BY`, recursive CTE, SQL/PGQ
`GRAPH_TABLE` — the last needs a bounded depth), and the write DML per
design. `analyze.py` consumes measured numbers only.

## Layer 3 — `assets/` (the runnable side)

```
assets/
  compose/            db + db-ords profiles, each self-checking (ASSERT:<name>:PASS)
  tooling/configure/  idempotent, self-verifying feature enablers (11 scripts)
  tooling/optimize/   run-sql.sh (container/easy/wallet) + db-lifecycle.sh (guarded)
  tooling/connection-kit/  per-language connection templates
  bench/              time-query.sql, time-dml.sql, explain-query.sql, get_order.<shape>.sql
  seed/               canonical restaurant domain + scale/ (volume generator, reset, drop, status)
```

### The benchmark harness
`time-query.sql` reports per-execution **logical reads** (consistent gets from
`V$MYSTAT`) — deterministic even at small scale where a 10 ms wall-clock reads 0.
`time-dml.sql` reports per-iteration **redo bytes** (the sharp write-amplification
signal), bracketed across SQL*Plus calls because redo flushes only at call
boundaries. Both warm up, take the median + coefficient of variation over K
trials, set `RESULT_CACHE_MODE=MANUAL`, and emit
`BENCH:<label>:<primary>:cg=…:us=…:cv=…`. `explain-query.sql` captures the actual
plan off the timing path. Methodology: durability parity across engines,
cache-unbound proof, and per-cell CV gating — see the noise-floor section of
[the walkthrough](WALKTHROUGH.md).

## The end-to-end flow

```
describe goal → router intake → (first use only) operating-principles gap-fill
  → .oracle-ai-dev/ store: standards.md governs, lessons.md informs — read first,
    every modeling session
  → model (hand-authored or ingested)
  → generate query per shape → benchmark (run-sql.sh → harness) → analyze
  → ranked options + union model + plans → chosen shape
  → datalayer: schema.sql + deploy + per-platform DAO
```

## Dual-platform packaging

`.claude-plugin/plugin.json` (Claude Code) and `.codex-plugin/` (Codex) both point
at `.mcp.json`, which launches the SQLcl MCP server (`-R 4`). Codex does no
placeholder substitution, so paths resolve to `sql` on `PATH`; `userConfig`
entries carry `title`s. CI keeps the two manifests in lockstep.

## Testing

Strict TDD. The pure-Python suite is fast and hermetic. A gated tier
(`ORACLE_AI_DEV_LIVE=1`, and nightly in `.github/workflows/live.yml`) runs the
harness, generators, DDL, and the full db+ORDS Mongo-API path against real 26ai
Free containers. Nightly it runs in **two serialized passes** — the self-managed
compose stacks first, then the shared-container pass — because the stacks pin one
container name and interleaving them was green only by luck; the `shared_container`
marker is the explicit, lint-enforced contract. This is where the load-bearing
runtime findings (duality PK
projection, ORDS enable-schema privileges and mapping-refresh lag, JSON
tablespace, redo call-boundary flushing) were verified. That tier holds **no
xfail escapes**: ORDS readiness is waited on explicitly (`tests/live_helpers.py`),
and the only sanctioned skips are genuine capability gaps (a db-only container
with no ORDS; a cold, offline ONNX-model cache). The **capstone integration test**
(`tests/integration/airline/`, [write-up](capstone-airline-integration.md)) exercises
the whole pipeline against the real airline-reservations model — model → derived indexes →
the design walk over a mixed workload at 30k reservations → data layer validated
identical across all five runtimes. Its
[RESULTS.md](../tests/integration/airline/RESULTS.md) documents **seventeen defects found in
the measurement harness itself**, each of which had produced a confident, wrong architecture;
they are why the optimizer now validates answers before timing and reports the access path for
every cell. CI also runs manifest, lint, frontmatter, shellcheck, and executable-bit checks.

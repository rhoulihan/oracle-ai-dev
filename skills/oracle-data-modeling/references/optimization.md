# Measured model optimization

UMT's "read three dials, pick a shape" becomes a *measurement* when you can
benchmark the candidates. This turns shape selection from judgment into evidence,
and surfaces the break-points where a globally different design wins.

## The workflow

1. **Define query-result sets.** Name each query by the `entity.property`
   references it must return (the modeling intake already captures this).
2. **Generate the query per shape.** For each candidate physical shape
   (relational, duality, embedded document, …) write the equivalent query. The
   canonical domain ships three in [`assets/bench/`](../../../assets/bench/README.md);
   add `get_order.<shape>.sql` to register another.
3. **Benchmark against seeded data.** Run each candidate through the PL/SQL timing
   harness (`assets/bench/time-query.sql`), which loops it N times and reports
   `BENCH:<shape>:<ms>` measured server-side.
4. **Find the per-query optimal shape** from the medians
   (`tooling/optimize/analyze.py` → `optimal_shape_per_query`).
5. **Gather frequencies.** Ask how often each access pattern runs; rank them —
   by **frequency × measured cost, not raw count**. A pattern can be 99% of traffic
   and ~zero load (a static health check); a hot-but-free pattern must not shape the
   model. And **infrastructure writes are access patterns too**: sessions, audit
   rows, telemetry minted by middleware — the busiest write pattern in a system is
   often one nobody designed. Enumerate them with the rest.
6. **Weigh cross-query tradeoffs.** A shape that is optimal for the most common
   query can make an uncommon query more expensive.
   `weighted_cost` scores a whole design by frequency × measured cost.
7. **Find the break-point.** `find_breakpoint` computes the frequency at which a
   globally different design overtakes the locally optimal one — the point where
   the uncommon query's penalty exceeds the common query's savings — and
   `recommend_global_design` reports the mixed-vs-uniform choice with the savings.

## Output
A recommended physical design with the tradeoff math shown: what each shape costs
each access pattern, weighted by frequency, and the break-points that justify the
call. The measurements are real; the analysis is deterministic and reproducible.

## Works on any model
Step 2 is no longer hand-written. Describe the domain as a **ModelSpec** (entities,
columns, relationships, and the duality/document projections) and each query as a
QuerySpec (an `entity.property` result set + predicates); `tooling/generate/`
generates the equivalent SQL for **any model** against all three shapes
(relational join, duality, embedded document). `generate_candidates(model, query)`
returns the per-shape SQL that feeds the benchmark — so the whole measure→analyze→
recommend loop runs for arbitrary user models, not just the restaurant example.

## Reads and writes (write amplification)
The engine models **write amplification**, not just reads: `generate_update`
produces the child-field UPDATE per shape — a relational update touches one row,
an embedded-document update `JSON_TRANSFORM`s (rewrites) the whole document, a
duality write fans to the base tables. The DML harness times these (and rolls
back). `weighted_cost_rw` then scores a design by **read AND write** cost weighted
by each pattern's read/write frequency: `Σ (read_freq·read_ms + write_freq·write_ms)`.
This is the resource-consumption model where the read/write balance is the tuning
knob that flips the optimal shape.

## Output: a ranked range of options
`recommend_design_options` returns a ranked range of designs (the per-query-optimal
mix plus each uniform shape), cheapest first, and for each: its total cost,
**discussion points** (why the shape wins — "fastest reads, but writes amplify"),
and the **frequency break-points** where a neighbour overtakes it (e.g. "above
write frequency ≈ 8.3, the write-cheaper shape wins"). The developer sees the whole
tradeoff frontier, not just one answer.

## The union model: one design for all patterns
Once every pattern's per-shape cost is measured, choosing the single converged
model that best serves the **union** of all access patterns is mechanical.
`recommend_model(patterns, read_meas, write_meas)` takes each pattern's **rate**
(and optional **interval**, so `1000/hour` and `10/day` compare on one base) and,
for each candidate model, sums `rate·cost` across all patterns — the minimum is
the winner. A converged model realizes the shared dataset as one shape, so the
candidates are the shapes shared by every pattern.

Because the sum is **rate-weighted, the highest-frequency pattern dominates** and a
low-frequency pattern's cost is *washed away* — optimizing the hot path effectively
sets the model. That is usually what you want, but it has a trap: a rare pattern
with a tight **latency budget** can be silently sacrificed even though its weighted
cost is negligible. So `recommend_model` returns, alongside the ranked models:
- **contributions** — each pattern's share of the weighted cost, and whether it is
  washed out (below a threshold);
- **latency_violations** — any pattern whose *raw per-op* cost under the chosen
  model exceeds its budget, even when washed out (the fix is usually a secondary
  materialization — a duality view or index — just for that pattern);
- **rate_breakpoints** — how far a washed-out pattern's rate must rise before the
  runner-up model overtakes the chosen one.

This closes the loop: measured costs + declared rates → the deterministically
optimal model, with the washed-out minority made visible rather than buried.

## Index the ACCESS PATTERN, not just its filters

An aggregation is an access pattern. Derive indexes from a query's **`GROUP BY` keys and its
aggregate arguments**, not only from its `WHERE` clause — or every aggregation full-scans and
you will conclude, wrongly, that the shape "cannot aggregate".

This is not hypothetical. The airline capstone reported the document design as **2.4× worse
than relational, entirely because of aggregation** — 1.1% of the traffic was 60% of its cost.
The optimizer's own code asserted the conclusion in a comment. It was a missing index:

| `count_by_status`, document collection, 30k reservations | | |
|---|---:|---|
| no index on the group key | 15,479 µs · 3,359 reads | `TABLE ACCESS FULL` |
| index on the group key | **1,789 µs · 102 reads** | `INDEX FAST FULL SCAN` |
| relational reference | 1,352 µs · 247 reads | |

Fewer logical reads than the relational table. The design went from **last to first**.

**Two details are the whole trick, and neither is guessable.**

**1. The trailing constant.** A B-tree omits an entry whose key is entirely NULL, so Oracle
will *not* use it for `COUNT(*)` — any row might be missing the key. Add a constant:

```sql
CREATE INDEX docs_status_ix ON res_docs (JSON_VALUE(data, '$.status'), 0);
--                                                                     ^ never wholly NULL,
-- so the index holds EVERY row and can be fast-full-scanned. No query change, no semantic
-- change: the NULL group is still counted.
```

Make it **covering** — group keys, then aggregate arguments — and Oracle never touches the
table at all: `(JSON_VALUE(data,'$.class'), JSON_VALUE(data,'$.qty' RETURNING NUMBER), 0)`.

**2. `JSON_VALUE(... RETURNING NUMBER)`, not dot notation.** Dot notation (`d.data.qty.number()`)
preserves the JSON type — which is why it was chosen — but it is **not the expression a
functional index is built on**. `RETURNING NUMBER` preserves the type *and* matches the index.
Type preservation was never the whole requirement.

> **The rule underneath both:** an index whose expression differs from the query's *by one
> character* is built, `VALID`, and silently ignored. Oracle will even tell you so — read the
> plan's SQL Analysis Report: *"predicates which preclude their use as keys in index range
> scan."* Generate the query and its index from **one function**, never two.

**And the meta-rule:** *a design's weakness must be demonstrated on its best access path, not
its default one.* Before writing "X cannot do Y", ask what index would make it, and build it.

The exact-match rule is a **family**: `RETURNING NUMBER` ≠ default-VARCHAR2,
`VARCHAR2(100)` ≠ `VARCHAR2(400)`, dot-notation `.string()` ≠ `JSON_VALUE(...)` — the
CBO matches expressions, not semantic equivalents. Pick one syntax per access path,
use it identically in the index and every query, and verify with the plan.

### One index for two lanes (Mongo API + SQL) — dot notation first

When one collection is read by BOTH the Mongo API and SQL (a view, BI tool, JDBC
app) — the converged story — the index you choose and the way the SQL side writes
its predicate decide whether both lanes share one index or split into two. This
is a modeling decision, not a tuning afterthought (field-verified on 26ai + ORDS,
2026):

- **Simple dot notation matches Mongo's comparison semantics.**
  `WHERE t.data.customerRef = '…'` (and `t.data.paidAt.dateTimeOnly() > TIMESTAMP '…'`
  for native-date ranges) compiles to a `JSON_VALUE(... TYPE(STRICT))` recheck over
  the multivalue index access — the same semantics the Mongo API uses — so the SQL
  predicate picks up the multivalue index a Mongo `createIndex` auto-creates, and
  vice versa: a SQL-authored `CREATE MULTIVALUE INDEX … (t.data.customerRef.string())`
  serves Mongo `find()`.
- **What breaks the sharing (measured → full scan):** a scalar
  `JSON_VALUE(DATA,'$.f') = …` predicate (full-scans against a Mongo-created
  index; one build was seen rewriting it onto a SQL-created `.string()`
  multivalue — do not rely on that: **plain dot is the only predicate form
  measured to match the shared index regardless of which lane created it**),
  a scalar `JSON_VALUE` functional index (serves only the SQL lane — the
  Mongo lane can never use it, so the lanes split into two indexes that never
  converge), and an item method ON the predicate (`.string() = …` coerces with
  different semantics and loses the match — plain dot is the sweet spot).
- **The sharing rule is really TWO rules — scalars and arrays differ, and
  getting it wrong is silent.** Dot-equality on an ARRAY field is not
  containment: `t.data.characteristic = 'POOL'` returned **0 rows, fast,
  wrong**, while the Mongo lane returned 197 — only the equivalence gate
  caught it. The correct array form is containment, and it shares the same
  index Mongo uses:

  | field kind | SQL form that shares the index |
  |---|---|
  | scalar | plain dot — `t.data.field = 'x'` |
  | array | `JSON_EXISTS(t.data, '$.field?(@ == "x")')` |

- **There are two convergence stories, one per storage model.** Mongo filters
  through a DUALITY view push down to the **base table's B-tree** — so the
  relational indexes serve both lanes there, exactly as the multivalue index
  does over a collection:

  | storage | Mongo reads through | the shared index |
  |---|---|---|
  | relational | duality views | the base-table B-tree |
  | document | JSON collections | the `$ora:`/multivalue index |

  The demonstration that beats an assertion: drop the one shared index and
  time both lanes — they degrade **together** (measured ~4.6× SQL / ~2.9×
  Mongo on one B-tree). Caveat: only where no alternative index exists,
  or the optimizer substitutes and the delta is ~1×.
- **Numbers share only when the writer preserves a real number type**
  (measured, e2e): values written as SQL/JSON numbers or BSON
  `NumberInt`/`NumberLong`/`NumberDecimal` match the `.numberOnly()` multivalue
  index from plain-dot SQL; the **JS bare-number default (BSON double) does
  not** — the Mongo lane still matches, answers stay identical, but the SQL
  lane full-scans that field. On shared collections, write numerics with an
  explicit number type from Mongo clients, and let `python -m
  tooling.plancheck` catch any field that slipped (it did, live).
- **The honest tradeoff:** a relational view whose columns are `JSON_VALUE`
  projections will full-scan when filtered on those columns. To keep the shared
  index, filter with dot notation on an exposed `DATA` column (or the base
  table) — you give up plain `col = value` ergonomics; surface that cost during
  modeling.

The generators enforce this doctrine for the document lane: plain-dot scalar
predicates, typed-item-method MULTIVALUE indexes, and item-method aggregation/
ORDER BY expressions — `tooling/generate/sql.py`, `tooling/generate/ddl.py`
(`dot_pred_expr` / `dot_typed_expr`), guarded by
`tests/test_dot_notation_first.py`. `JSON_VALUE RETURNING` is the documented
last resort (the `_id` point read, and the duality lane whose rewrite evidence
is on those forms).

**Exact first, then the native estimate.** Before hand-maintaining a probabilistic
counter (the Approximation pattern), check two cheaper rungs: the CBO often makes the
*exact* aggregate cheap enough; and when an estimate genuinely is the right trade,
`APPROX_COUNT_DISTINCT` ships the sketch natively — nothing hand-rolled to maintain
or get wrong.

## Why, not just how much: execution-plan capture
Alongside the measured cost, `assets/bench/explain-query.sql` captures each
shape's **actual execution plan** (`DBMS_XPLAN.DISPLAY_CURSOR('ALLSTATS LAST')`
with `STATISTICS_LEVEL=ALL`) — real A-Rows vs estimated E-Rows and per-operation
buffer gets. This explains *why* a shape costs what it costs: a relational read
showing a nested-loop join over an index range scan, a document read showing a
single LOB fetch, or a cardinality misestimate (A-Rows ≫ E-Rows) that warns the
plan may flip at scale. It runs once per shape, off the timing path.

AWR and SQL Monitor are deliberately **not** used — not for licensing (the
Diagnostics and Tuning packs are **included on 26ai Free**;
`CONTROL_MANAGEMENT_PACK_ACCESS` defaults to `DIAGNOSTIC+TUNING` — runtime-verified
in the gap-1 dossier) but because they aggregate at the wrong grain for a
per-query shape comparison. `DISPLAY_CURSOR` gives the same per-statement insight
directly. For tuning a single slow query with AWR / SQL Monitor / the advisors,
use the query-tuning skill — all of it works on Free.

## Optimizing against your own system (wallet + sized sample)
The optimizer isn't limited to the local Free container. Point it at any Oracle
database — including an Autonomous Database by mTLS wallet — and benchmark on a
sample sized to your data.

**Connection.** All harness scripts run through `assets/tooling/optimize/run-sql.sh`,
which has one execution seam and three modes (`OPT_CONN_MODE`):
- `container` (default) — the local Free container via `docker exec`.
- `easy` — a remote DB by easy-connect (`OPT_CONNECT=user/pw@//host:port/service`),
  run with SQLcl on your machine.
- `wallet` — an Autonomous Database: `OPT_WALLET=/path/to/wallet.zip` and
  `OPT_CONNECT=admin/pw@myadb_tp` (the tnsnames alias). SQLcl consumes the wallet
  directly (`-cloudconfig`), so there's nothing to unzip. Grant the benchmarking
  user `SELECT_CATALOG_ROLE` for the deterministic logical-reads/redo metrics;
  without it the harness degrades to microseconds.

The same `time-query.sql` / `time-dml.sql` / `explain-query.sql` run unchanged on
every target, so the Python analysis is identical.

**Sizing the sample.** You don't benchmark the whole production dataset — you
generate a representative but bounded sample. `assets/seed/scale/scale-seed.sql`
produces a sized, self-consistent sample (`&orders`, `&items_per_order`, and pool
sizes), populating the SAME logical content across all three shapes — the
relational base tables, the `order_docs` document collection, and (automatically,
because it reads the base tables) the `order_dv` duality view. `tooling/optimize/
sizing.py`'s `recommend_sample_size` picks the row count: big enough to separate
shapes (multi-block scans, real index depth — below ~1000 root rows the data fits
in too few blocks to be representative) yet within a storage cap (the 12 GB Free
limit, or the target system's headroom), accounting for the three shapes each
holding the content.

At real volume the shapes separate cleanly: on a 5000-order sample a point read
measured 89 logical reads relational, 90 duality, 191 document (cv = 0 —
deterministic), versus an indistinguishable 0 ms on the 2-row toy seed.

## From access patterns to a data layer
The optimizer's output isn't only a shape recommendation — it drives a generated
**data-access layer**. `tooling/datalayer` turns the model plus its access
patterns (each a QuerySpec) against the chosen shape into a working repository per
platform:

    python -m tooling.datalayer <spec.json> <out_dir> [--platforms py,node,java,go,dotnet]

The spec is `{"model": ModelSpec, "patterns": [{"name","shape","query"}, ...]}`.
Every access pattern becomes a method whose predicate values are **bind
parameters** — `bound_sql` parameterizes the query (relational/sql_view via the
shape generators; document/duality via JSON-path `PASSING` binds, so nothing is
inlined). By default it renders all five platforms (python-oracledb,
node-oracledb, Oracle JDBC, godror, ODP.NET); `--platforms` selects a subset. The
generated code reads the connection from `DB_USER`/`DB_PASSWORD`/`DB_DSN` and never
embeds credentials. An archive README lists the patterns, shapes, and their binds. The archive also ships `schema.sql` — the generated CREATE DDL for the optimal
schema (tables + FKs for relational, the JSON collection for document, base
tables + a single-level duality view for duality) — plus `deploy.sh`; and the
generated Python exposes `ensure_schema(conn)`, which probes for the schema and
deploys it if absent. `tooling/generate/ddl.py` produces the DDL from the model.

## Initializing a target, safely
Use `assets/tooling/optimize/db-lifecycle.sh` to prepare a database for a run:
- `status` — read-only: which benchmark objects exist and their row counts.
- `init` — create the benchmark schema if absent.
- `load` — generate the sized sample.
- `reset` — drop the benchmark objects and recreate them empty (reload).
- `new-project` — drop all benchmark objects and start fresh.

**Safety guard (enforced, mirrors `tooling/optimize/safety.py`).** On an EXTERNAL
target (`easy`/`wallet`) any operation that writes or drops is **refused unless you
explicitly set `OPT_ALLOW_EXTERNAL_WRITES=1`** — the tool never touches pre-existing
data by default. Reads (`status`, and the timing/plan harness) are always allowed.
The local container is disposable, so everything is permitted there. Destructive
SQL only ever names a fixed allow-list of benchmark objects, never an arbitrary
user object — so even with the override, point it at a DEDICATED benchmark schema.

## Candidates come from reasoning; the winner from measurement
The plugin does **not** pick a shape by a fixed rule table. The agent **reasons**
about the domain and access patterns to propose a diverse set of candidate models —
embed the aggregate, decompose it into meaningful containers to tame write
amplification, reference vs embed per relationship, a precomputed subset, a shape
per entity. The [decision heuristics](decision-rules.md) and [pattern
catalog](patterns.md) inform that reasoning; they don't replace it. The optimizer
then measures every proposed candidate and ranks them. Imagination is the LLM's job;
the numbers are the tooling's.

**A unit caveat:** read cost (logical reads) and write cost (redo bytes) are not the
same unit, so they cannot be added directly. When comparing a design across a
read/write mix, use a consistent unit — per-op elapsed µs (the harness reports it) —
and reserve logical-reads / redo-bytes for same-kind comparisons.

## Analyze index requirements BEFORE interpreting performance
Indexes are part of the physical model, **derived from the access patterns' filter
conditions** — and you must add them before trusting any performance numbers, or
you are measuring full scans that would never exist in production. `generate_indexes`
turns each query's predicates into candidate indexes: a single-column index per
filter, and a **multi-column (composite) index when one query filters on several
columns** — on **both tables** (composite B-tree) and **documents** (composite JSON
function index; verified live via `INDEX RANGE SCAN`). PK filters are skipped
(already indexed). The generated datalayer `schema.sql` includes these indexes.

Whether an index actually wins depends on **selectivity and data volume**: at small
scale a low-selectivity filter (e.g. one returning thousands of rows) still loses to
a full scan, but wins at production scale — which is exactly why the sample must be
sized representatively. Index maintenance is also a write cost, so more indexes add
to write amplification: another measured trade-off, not a free win.

**The deployment target is a dimension of "which index?".** On Exadata-class storage,
Smart Scan offloads filtering and projection to the storage cells (JSON operators run
there against OSON), storage indexes auto-track min/max per region, and Bloom filters
prune joins before the network — so wide analytical scans often beat a maintained
B-tree. B-trees still win OLTP point lookups and highly selective predicates.
Calibrate on the target: this harness's benches run *without* those offload features,
and any flat efficiency multiplier (offload, compression) is access-shape-dependent —
an assumption to measure, never to assume for a bursty point-access shape.

## Single-table designs are a candidate too
Single-table design is a tool, not a religion: it fits enumerable, priority-ranked,
read-heavy patterns over owned data. Ad-hoc analytics, fast-changing access patterns,
or a small simple model don't warrant it — and on Oracle, where joins and rich
indexing are cheap, the preconditions failing routes the design to a normalized base
plus duality instead.

DynamoDB single-table designs are a first-class **converged** candidate. Import one
(NoSQL Workbench export) with `model_from_dynamodb`: each item `type` becomes an
entity, the concatenated PK/SK composite keys are decomposed into **natively-typed
columns** (no string concat, dates as DATE), and every GSI becomes a **multi-column
index** — including composites DynamoDB can't express and multivalue indexes over
JSON arrays it has no answer for. `generate_ddl(model, "single_table")` realizes it:
one shared table with a `type` discriminator, the union of the types' columns, a
composite-key index per type (anchor-first, so an item-collection read uses it), and
the GSI-derived indexes. `generate_single_table` queries it — a per-type read filters
the discriminator; an **item-collection** read filters the shared anchor and returns
the co-located types in one indexed scan, no joins.

Two converged advantages DynamoDB lacks: **(1)** shape the co-located result into the
required document *on the way out* with `JSON_ARRAYAGG`/`JSON_OBJECT` (`as_document`)
— single-table storage with document output and no stored doc to rewrite (measured
free: the same logical reads as the raw item-collection read); **(2)** it is still
SQL, so joins and reporting aggregations run on the same table. A duality view can
layer an *updatable* document over the same storage where the parent/child key
mapping is clean.

## The iterative loop: change the model, re-compare
Modeling is a loop, not a one-shot. Propose or implement a change — add an index,
change a projection, try the single-table variant, embed vs reference — and re-run
`tooling/optimize/compare.compare(model, patterns, read_meas, write_meas)`. It reports
each pattern's available candidate shapes (straight from the edited ModelSpec), the
measured per-pattern winner, and the converged union model. Because everything is a
pure function of the ModelSpec plus the measured numbers, re-running after a change
is a single call — the candidate set and the ranking update to reflect the new model.

**Every summary tier re-justifies itself.** When stacking precomputed tiers (a fact
table, then global summaries, then per-key summaries — in that order, and per-key
last and gated), re-run the matrix after each tier lands: a tier that was justified
alone may stop paying once a coarser or finer tier exists. Delete tiers that no
longer win any pattern. The measured field arc behind this rule is in
`references/field-lessons.md` (the financial-services PoC).

**From the cost matrix to capacity.** The matrix's rate × per-op µs is the same
product Little's Law needs (concurrency = rate × service time), so measured per-shape
costs bridge directly to capacity estimates. When sizing a migration target: decide
the shape first (footprint is per-shape — source bytes do not transfer), size **one
logical copy** (collapse the source's replica fan-out), and normalize the size basis
(compressed vs logical, TB vs TiB) before quoting any footprint delta.

## Single-table writes: sparse indexes + partition-by-type (automatic)
A single-table design carries many indexes to serve its many access patterns, and
naively every insert touches all of them — the write-side cost of its read
versatility. The generator defaults fix this:
- **Automatic list partitioning by the discriminator** (`PARTITION BY LIST(type)
  AUTOMATIC`): each item type lands in its own partition, auto-created, so reads
  filtered by type **prune to one partition** and each type is physically isolated.
- **Sparse (type-filtered) local indexes**: each index is `CASE WHEN type='t' THEN
  col END`, so it holds only its own type's rows (Oracle omits all-NULL keys) — the
  native analog of a DynamoDB **sparse GSI**. An insert of another type never touches
  it. `generate_single_table` emits the matching sparse predicate, so reads still use
  the index (partition prune → `INDEX RANGE SCAN`).

Measured live: an `assignment` insert dropped from **3,084 → 1,805 redo bytes (~41%)**
once the indexes were sparse (it had been leaking into the `booking`/`flight` indexes
via shared columns), while the read still did a partition-pruned index range scan.
This materially closes the write gap versus a normalized schema. **Index overloading**
(one generic index serving several types) is available but usually worse here: an
overloaded index is maintained by *every* type it covers and reintroduces
generic/concatenated keys — sparse purpose-built indexes are both cheaper to write and
keep native typing. Both `sparse` and `partition_by_type` can be disabled —
`python -m tooling.optimize --no-sparse --no-partition-by-type`.
(GSI overloading was born when DynamoDB capped GSIs at 5; with the limit at 20 and
on-demand capacity, its own originators consider it deprecated even there — never
replicate it on Oracle.) The same type-routed CASE-gated
technique generalizes beyond DynamoDB imports to **any** polymorphic or
schema-versioned collection — with the caveat that the discriminator becomes a
load-bearing field that must be set consistently.

## The core process: the cost matrix fuels the decision
Modeling is not shape-picking; it is filling a **cost matrix** and letting it drive
the design. Every access pattern is a row — **reads *and* writes**, each with a rate
— every candidate design a column, each cell a *measured* cost. `tooling/optimize/
decide.py`'s `decide_model` consumes that matrix and mechanically elects the design
that minimizes the frequency-weighted total. A design is viable only if it can serve
*every* pattern (a document store with no `GROUP BY` cell is excluded from a workload
that aggregates). Writes are first-class rows — they are what make denormalization
expensive — so as the write rate climbs the choice walks toward the write-cheap design.

### The document-modeling algorithm
This is the core process of document modeling — optimize to the access pattern, and
remember **writes are patterns too, not just reads**:

1. **Assemble the ideal document per read pattern** — the aggregate that serves it in
   one read, denormalizing/duplicating referenced data to eliminate joins. (In a
   document store it is fine to embed the same referenced datum in several documents.)
2. **Add the write patterns** — for each write, count the documents it touches,
   *including every denormalized copy*.
3. **Fill the cost matrix** — measured, reads and writes.
4. **Reduce documents touched where amplification > read savings** — merge/consolidate
   the documents whose write cost (documents-touched × rate) exceeds the read benefit
   they buy. This collapses many ideal-per-pattern docs toward fewer shared ones.
5. As write frequency climbs, that consolidation walks the design **document →
   single-table → hybrid → duality → summary → normalized** — each step trading
   read-assembly for write-cheapness. The hybrid station (a relational core +
   one JSON flex column per entity, `projections.hybrid`) keeps stable keys as
   typed columns while the variable attributes ride the flex column with the
   document lane's dot-notation doctrine. The summary station is normalized
   storage plus declared `REFRESH FAST ON COMMIT` aggregates
   (`projections.summary`): matching aggregation reads hit the materialized
   view, everything else is relational SQL, and every write pays the view's
   incremental maintenance. The knob is measured, not dogmatic.

**Single-table is the far end of that same walk**: maximal read consolidation (one
anchor scan, many indexes) with *no* cross-document duplication to re-write. Three
measured scenarios show the same matrix electing document (reads only), relational
(aggregations + writes), and single-table (multi-anchor co-retrieval + writes) — see
`tests/integration/airline/decide-scenarios.txt`. Then change the model and re-run
`compare` (which now shows writes as first-class rows) to see the ranking move.

## Run it: `python -m tooling.optimize` (the six steps, codified)

Do **not** hand-assemble the loop. The runner does all of it against the live database:

```bash
pip install oracledb   # the live paths need the driver; generation is stdlib-only
export DB_USER=plugin_dev DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1
python -m tooling.optimize <workload.json> --out ./out
```

`workload.json` = `{"model": ModelSpec, "patterns": [...], "seed": "<file|inline sql>"}`,
each pattern `{name, kind: read|write, rate, category, query, [write], [sql]}`. **You**
(the agent) propose the candidate models — the projections in the ModelSpec; the runner
measures whatever the model declares.

It then: derives + deploys the **access-pattern indexes first** (measuring un-indexed
tables benchmarks full scans production would never run), deploys every candidate shape,
seeds, measures **every pattern against every shape** on the live DB, prints the **full
cost matrix** (reads AND writes as first-class rows, each with its rate), runs
`decide_model` over it, reports **where the winner flips**, and writes the winning
schema's DDL.

**Unit discipline:** logical reads and redo bytes are *different units* and must never be
summed — the matrix is built in one unit (median elapsed µs), with the server-side
counters kept alongside as diagnostics.

**A missing cell means EXCLUDED, not penalised** — a document cannot serve a `GROUP BY`
via a duality view, so that design is dropped for that pattern rather than scored badly.
Measurement *errors* are reported loudly for the same reason: a failed cell would
silently exclude a design and invert the recommendation.

**The decision block also discloses transferability and cardinality**
(`tooling/optimize/runner.py`):

- `decided by: point reads … -> verdict carries to Exadata-class deployments`
  vs `decided by: scan economics … -> environment-conditional`. The split is
  research-verified: Exadata smart scan and storage indexes cheapen only
  direct-path full-segment scans — buffer-cache point reads never offload — so
  a margin won on point reads means the same thing on production hardware,
  while a margin won on scans must be re-validated on the target. This bench
  runs *without* those offload features; never assume a scan-decided verdict
  transfers.
- `!! PROVISIONAL — <pattern> answered N rows against a declared expectation
  of M`. Declare `expect_rows` on a pattern to arm the check: a deciding
  pattern that answered fewer rows ran against a degenerate fixture, and a
  small-seed winner is chosen on its incidental costs — re-seed at
  representative volume before trusting the verdict.
- `SUMMARY MAINTENANCE (measured, charged to the write cells)` — printed
  whenever `summary` is a candidate: per write pattern, the summary's cell
  against relational's and the delta between them, which is what the
  materialized view's upkeep actually costs at that pattern's rate. The
  summary's write cells time `execute + COMMIT`, so incremental view
  maintenance is inside them; every other design's write cells are rolled back
  and pay no commit at all. The bias therefore runs *against* summary — a
  summary that still wins the election wins despite the handicap — and it is
  disclosed rather than corrected. Maintenance never appears as its own row:
  it is a write cost, so it is charged where writes are.

## Sources
- Oracle JSON Developer's Guide (26ai) — https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
- Count-vs-load weighting, tier re-justification, Exadata offload calibration, and
  the capacity bridge — field-verified, 2025–2026.

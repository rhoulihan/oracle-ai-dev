# Document/data-modeling patterns → measured Oracle realizations

These are the well-known data-modeling patterns. On Oracle's converged engine each
is a **realization on one engine**, and the optimizer picks the winner by
**measurement**, not by rule — the best realization **varies with the read/write
knob** (frequency, cardinality, scale). Pure document is a first-class realization,
not a fallback.

The full catalog — 17 generic patterns (the 12 canonical + the 5 tree variants,
collapsed onto Oracle's three hierarchy realizations). Each is proven live on 26ai by
a mini-domain test (`tests/test_pattern_catalog_live.py`): every generated realization
deploys, runs, and is named — the winner still varies with the knob.

| Pattern (generic) | What it is | Oracle realization(s) | Wins when… |
|---|---|---|---|
| **Embedded Document** | a child aggregate nested in the parent doc | JSON collection / document shape | read-heavy, bounded/owned child |
| **Subset** | keep the hot subset (top-n of an array), rest elsewhere | document + `FETCH FIRST n`; overflow table | reads touch only the hot slice |
| **Extended Reference** | embed a frequently-read subset of a referenced entity | duality/document projecting the subset; relational join | reads want the referenced subset without a join |
| **Normalized (Referenced)** | separate tables joined by keys | relational | write-heavy; shared/independent entities |
| **Duality** | relational storage projected as a document (both APIs) | JSON Relational Duality view | write-efficient storage + document access |
| **Computed / SQL View** | derived values (COALESCE/aggregation) | `sql_view` wrapped in JSON_OBJECT (read-only); materialized as a `REFRESH FAST ON COMMIT` summary MV when the precompute inequality passes (measured) | the projection needs expressions duality can't do; precomputed aggregate wins the read, pays the write |
| **Attribute** | many sparse `{k,v}` attributes searched uniformly | JSON + multivalue index | heterogeneous/sparse attributes |
| **Bucket** | group many small records into bucketed docs | embedded array vs partitioned relational | append-light reads vs write-heavy appends |
| **Polymorphic** | heterogeneous shapes in one collection | JSON (schemaless) + a discriminator; per-type virtual columns | mixed document shapes under one anchor |
| **Schema Versioning** | evolve schema without a migration | a `schema_version` field + version-conditional read | shapes evolve over time |
| **Outlier** | a few records break the common shape | overflow table/collection + an `is_outlier` flag | most records are uniform, a few are whales |
| **Document Versioning** | keep historical versions | Flashback / temporal `AS OF`; current + history table | history is read alongside the current record |
| **Pre-allocation** | allocate fixed slots up front | pre-sized array / pre-inserted rows, update slot i | slot count is known and updates are in place |
| **Approximation** | approximate counters to cut writes | exact aggregate first; then native `APPROX_COUNT_DISTINCT` — never a hand-rolled sketch | exact counts aren't needed and writes are hot |
| **Tree / Hierarchy — Adjacency** | parent/child reference | `CONNECT BY` / `GRAPH_TABLE` first; recursive CTE is the portability spelling — plan-check it (see [claims guardrails](claims-guardrails.md)) | deep or unbounded traversal |
| **Tree / Hierarchy — Materialized Path** | array-of-ancestors / path column | path column + multivalue index | ancestor/prefix lookups |
| **Tree / Hierarchy — Graph** | property-graph traversal | SQL/PGQ `GRAPH_TABLE` (bounded depth) | bounded-depth / multi-relationship graph traversal |

## How the optimizer uses this
Given a model + access patterns, it generates each realization, benchmarks read
**and** write cost, and returns a **ranked range of options** — each named by its
generic pattern — with the frequency break-points where a neighbour overtakes it.
An Embedded Document optimal for reads can lose on a write-heavy path to a
Normalized/Duality realization because of write amplification. The three Tree
realizations return the same subtree, but differ in cost — Adjacency handles deep
or unbounded trees, while `GRAPH_TABLE` needs a bounded depth (its cost grows with the
bound) and shines on bounded/multi-relationship graphs. See
[measured optimization](optimization.md).

**`CONNECT BY` and `WITH RECURSIVE` are not interchangeable on Oracle.** A recursive
CTE materializes each recursion level as a true intermediate relation — a
write-then-read dam the CBO can barely optimize — while native `CONNECT BY` keeps the
frontier in a single hash table and streams. Emit `CONNECT BY` (or `GRAPH_TABLE`) for
hierarchy projections; treat the standards-compliant recursive CTE as the portability
spelling, and plan-check it before shipping. Any "Oracle handles hierarchies well"
claim is specifically a `CONNECT BY`/`GRAPH_TABLE` claim. For near-static deep
hierarchies that must read at depth-independent latency, materializing
transitive-closure edges (the Computed pattern's graph realization) is a further
option — priced by its O(N²)-worst-case write trade, so only when the structure
rarely changes.

## Triage before you map: physics vs workaround
Before porting a document pattern onto Oracle, sort it into one of two bins.
**Physics** trades a real resource you would trade on any engine (hot/cold tiering,
time-series amortization at true scale, precision-for-cost). **Workaround** exists to
dodge a missing engine capability (embedding a fact in N copies to dodge a join,
pre-storing a rollup to dodge read-time compute, rewriting a subtree because the
engine won't traverse edges). The pattern's lineage is the diagnostic — each has a
pre-NoSQL ancestor born of an era's constraint; ask whether that constraint still
exists on the target engine. A brownfield review's deliverable is a per-pattern
**keep / retire / replace** verdict: keep physics, retire workarounds, replace them
with the native realization (duality, `CONNECT BY`/`GRAPH_TABLE`, temporal `AS OF`).

## Sources
- The catalog is the general document-modeling pattern vocabulary; Oracle realizes
  each on one converged engine.
- Physics-vs-workaround triage and the `CONNECT BY` streaming-vs-materialization
  distinction — field-verified, 2025–2026.

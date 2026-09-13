<!-- Copyright (c) 2026 Oracle and/or its affiliates. -->
# Data-modeling intake (S3) — the UMT access-pattern interview

Unified Model Theory models the *access*, not just the domain: "Model the domain.
Project the access." Gather the canonical entities first, then enumerate every
access pattern with the dials that decide its shape. At most three questions per
turn; accrue answers into `data_requirements.md`.

## 1. What are the entities and how do they relate?
Build the canonical ERD before choosing any physical shape.
- field: entities
- Why: the canonical form is the one truth every shape projects from.

## 2. What are ALL the access patterns?
For each one the app must serve, capture it as a named query. This is the core of
the interview — enumerate them exhaustively before designing.
- field: access_patterns

For every access pattern, gather these dials:

### 2a. What does it return?
List the fields as `entity.property` references.
- field: access_patterns.returns
- Why: the set of entities in the result drives embed-vs-reference-vs-duality.

### 2b. How often does it run?
- field: access_patterns.frequency
- Why: rank by frequency (70/20/10). The most common pattern earns the optimized shape.

### 2c. What is the cardinality?
1:1, 1:N, N:1, or N:M between the entities involved.
- field: access_patterns.cardinality
- Why: unbounded children get referenced; bounded/owned children get embedded.

### 2d. What predicates and ordering does it use?
- field: access_patterns.predicates
- Why: predicates and sort keys decide which indexes the shape needs.

### 2e. What is the latency budget?
- field: access_patterns.latency_budget_ms
- Why: tight budgets favor denormalized, pre-joined shapes.

### 2f. How write-heavy is this path?
none / low / medium / high.
- field: access_patterns.write
- Why: a write-hot path must not pay a duality view's read-time join — the honesty
  calibration that routes it to a single collection instead.

### 2g. How many of the document's fields does the read actually touch?
- field: access_patterns.fields_touched
- Why: client-side deserialization has a break-even — a read that touches a few
  fields of a big aggregate argues for a leaner projection or smaller co-located
  documents gathered by an index.

### 2h. Must every shape reflect the same commit point?
- field: access_patterns.consistency_moment
- Why: connection-centric and entity-360 patterns often need graph, relational,
  spatial, and vector answers *as of the same instant* — when set, only same-engine
  projections qualify; no sidecar pipeline can.

## 3. What does your middleware/platform write per request?
Sessions, audit rows, telemetry, retry queues — enumerate them as access patterns.
- field: access_patterns
- Why: infrastructure writes are access patterns too; the busiest write pattern in a
  system is often one nobody designed. Weight every pattern by frequency × cost, not
  raw count — a hot-but-free pattern must not shape the model.

## 4. What is the document-size distribution — typical AND P99?
Also: how many indexes per collection?
- field: scale.doc_size_kb
- field: scale.doc_size_p99_kb
- field: scale.indexes_per_collection
- Why: the P99, not the average, decides the inline-vs-LOB threshold and drives
  index footprint — the tail is a modeling input.

## 5. What fraction of the data is hot?
- field: scale.hot_set_pct
- Why: for memory-bound profiles (large cool dataset, bursty point access), the
  shape that minimizes the hot set wins — reference rarely-read bulk out of the
  frequently-read document.

## 6. (Migrations) What basis are the source size figures on?
Compressed vs logical, TB vs TiB, replicas included or not.
- field: scale.sizing_basis
- Why: source engines report compressed, replicated sizes. Normalize the basis and
  size ONE logical copy; the target footprint is per-shape and is decided before any
  capacity quote. Also ask transaction sizes and hot-field update rates — source
  engine memory cliffs (cache-bound transactions, small-row thresholds, whole-document
  journaling) explain observed pain and do not transfer to Oracle.

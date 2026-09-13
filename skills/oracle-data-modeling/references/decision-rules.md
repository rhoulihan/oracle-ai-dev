# UMT decision heuristics

**These are heuristics to inform your reasoning, not a mechanical decision tree.**
Candidate models come from **LLM reasoning** — you (the agent) reason about the
domain and the access patterns and propose a *diverse set* of plausible physical
models (embed the aggregate, decompose it into meaningful containers, reference vs
embed per relationship, a shape per entity, a precomputed subset, …). The heuristics
below are vocabulary and intuition-pumps for that reasoning; they are **not** applied
as fixed rules. The optimizer then **measures** every candidate you propose and ranks
them — the winner is decided by measurement, not by rule. `tooling/recommend/shapes.py`
offers a rule-of-thumb starting point, but never overrides reasoning + measurement.

| Situation | Rule | Shape |
|---|---|---|
| Child is bounded, owned, co-accessed | **Embed** it | JSON collection / nested in duality |
| Child is unbounded, shared, independent | **Reference** it | separate table, FK |
| Immutable child data | Copy the immutable, project the mutable | embed a snapshot |
| Access pattern is write-hot | Never pay a duality read-time join on every write | single collection + multivalue index |
| One dataset serves both rows and documents, read-mostly | Stitch with a duality view | relational + duality |
| Collection read by the Mongo API **and** SQL/views | One multivalue index; dot-notation predicates on the SQL side — no parallel scalar `JSON_VALUE` index | JSON collection, shared index |
| Precomputed subset considered | Keep it only if read-freq × read-cost > write-freq × maintenance-cost | materialized view / summary |
| Splitting a collection | Split on governance/lifecycle, not query shape | separate collections |
| Tree structure | Trees store paths (multivalue index, O(log n) prefix scan) | path-encoded |
| Real graph traversal | Use GRAPH_TABLE / property graph | SQL/PGQ |
| Concerns in one aggregate change at different rates | Normalize along the **change-rate seams** (price vs availability vs description), re-assemble per consumer | relational + projection per consumer |
| Stable join/filter keys + open-ended per-instance attributes | **Spine + JSON extension column** — typed columns for what patterns filter/aggregate, ONE JSON column for the rest (never a nullable column per variant metric). A first-class measured candidate: declare `projections.hybrid` (or let the optimizer nominate it) and it competes in the election like every other shape | hybrid (measured) |
| Time-ordered or lifecycle-bound data + a retention/archival SLA, or hot-window scans over a fraction of rows | **Partition the entity** (`partition` block: interval for time-series TTL, auto_list for enumerable categories, hash to spread) — retention becomes metadata-only `DROP PARTITION`, and the dimension composes with any base-table shape; measure with and without via `--no-partition` | partition dimension |
| PK-led point and range reads over narrow rows with few secondary indexes | **Store the table in its primary-key B-tree** (`organization: "index"`) — the row lives in the leaf, so the PK traversal IS the fetch and a key range comes back ordered with no rowid hop; the price is the overflow split on wide rows and logical-rowid guess decay on the secondary indexes. A dimension, not a shape: measure it against the heap via `--no-iot`. Not available where the entity also wants compression, a non-hash partition family, or hybrid flex | organization dimension |
| Storage-pressure or redo-sensitive write-heavy tables | **Compress the rows** (`compress: "advanced"`) — fewer blocks per row on the read side, and only the transaction that trips a block's fullness threshold pays the compression CPU; BASIC is not the alternative (it compresses direct-path loads only). Measure with and without via `--no-compress` and read the write cells' elapsed/redo | compress dimension |
| Substructure with no identity, never queried relationally | Embed as an **opaque JSON column** — the third embed option beside object/array nesting | JSON column passthrough |
| Binary payloads (files, images, uploads) | **Blobs stay out** — metadata + content hash in the model, bytes in object storage; never design around GridFS on the Mongo API path | metadata document + object store |
| Content rolls out in versions (menus, price books, templates) | Insert the new version's documents and switch the version the query passes; rollback is the same move — no migration | version in the index equality prefix |
| "Near / within X / nearest" requirement | Location is a column type, not two NUMBERs | SDO_GEOMETRY + R-tree index |
| Invariant "at most one open X per Y" | Partial unique index filtered to the open states; duplicate-key → domain conflict (409) | partial unique index |

## The three physical strategies

1. **JSON collection** — single-entity, co-accessed; embed and store as a document.
2. **single collection with a multivalue index** — the write-hot path.
3. **relational + duality** — normalized tables stitched by a duality view.

The recommender evaluates in this precedence: **write intensity first** (a
write-hot path short-circuits to a single collection — and flags the ownership
caveat when it also spans multiple entities), **entity count second** (a
multi-entity read-mostly result gets a duality view), and a **single-entity JSON
collection as the default**. Frequency ranking is applied across patterns by the
modeling workflow (70/20/10), not inside this per-pattern decision.

## The ladder has a direction: cheapest tool first

The three strategies are an **escalation ladder, not a menu**. Start at the cheapest
tool — a pure document collection when the dials align (one consumer,
read-and-written-together). Escalate to a single collection with derived keys as the
hot path's write cost rises. Land on relational + duality **only when** pattern
complexity or lifecycle/governance conflicts force it — when you don't need the
join, don't pay for it. Over-normalizing out of relational habit is the mirror image
of the document crowd's over-embedding; escalate on evidence, not reflex. The
measured backbone: on the same Oracle engine, entitlement and array-containment
patterns ran roughly 9–15× faster in document shape (JSON + multivalue index) than against
a fully normalized schema, while the unwind-and-rank and join/aggregate-heavy
families went the other way — shape per pattern, one engine, decided by the matrix
(field-verified, 2025–2026).

## Key & identity strategy (an explicit intake decision)

- **Who supplies `_id`?** A document consumer favors a client-generated string UUID
  (the caller knows `_id` before insert, and it is readable in the document) at the
  cost of 36 chars vs 16 bytes per index entry for a DB-generated GUID/identity.
  Decide, then keep the DDL consistent — an IDENTITY root cannot accept a
  client-supplied `_id` on insert.
- **Immutable records** (attachments, ledger blobs, chain-of-custody) can use a
  **content-hash natural key**: one column serving as identity, dedupe key, and
  tamper evidence.
- Composite `_id` columns must all be NOT NULL — a nullable column cannot
  participate in a stable document identity.

## Index-shape heuristics

- **Order compound indexes ESR** — Equality keys (tenant/version/type scope), then
  Sort keys, then Range keys.
- **Sort keys are data, not derivation** — store them on the document
  (`section_order`, `item_order`); never derive them at read time.
- **Eligibility-filtered partial indexes** keep ineligible rows (inactive,
  out-of-stock) out of the index entirely; resolve schedule/variant choices on read
  rather than materializing one document per leaf × variant combination.
- **Multivalue index cost ≈ array cardinality × mutation rate** — one entry per
  element. Static descriptive arrays embed happily; arrays that churn per update tip
  toward referenced documents.
- **A field queried as two types carries two typed functional indexes** on the same
  path — each matched by its query's cast; deliberate coexistence, not redundancy.
- **Read-after-write on a search index needs `SYNC (ON COMMIT)`** — the default
  deferred sync leaves a just-committed row invisible to `CONTAINS`.

## Integrity tiering

- **Match the integrity pattern to the cost of the violation** — the three
  archetypes: duplicate identities → unique constraint; oversold inventory → atomic
  conditional update; double charges → idempotency key.
- **Exactly-once = at-least-once + idempotent processing**, with the idempotency
  check in the **same transaction** as the business write.
- **Know the source engine's defaults** when migrating: a default that acks before
  replication means the design may never have had the guarantees it assumed
  (Jepsen's MongoDB analyses are the public record); Oracle's ACID-on-by-default
  removes the footgun — but re-verify the invariants, don't inherit the assumption.
- **Constrain the canonical, not the consumer** — CHECKs/FKs on base tables, so
  every projection inherits them.
- **Scope optimistic locking** — version columns only on genuinely contended
  aggregates; ledgers are append-only + constraints, never versioned updates.
- **Denormalized cross-collection writes are one unit of work** — which is exactly
  what one ACID transaction absorbs on a converged engine.

## Sources
- Escalation-ladder ordering, key strategy, ESR ordering, integrity tiering, and the
  document-vs-normalized measurements — field-verified, 2025–2026.
- Jepsen analyses (public record) — https://jepsen.io/analyses

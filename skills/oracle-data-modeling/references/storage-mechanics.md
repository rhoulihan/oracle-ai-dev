# Storage mechanics — the physics under the shape decision

The deep layer under [decision-rules](decision-rules.md): how the storage
engine actually behaves, and which of those behaviors the generators encode.
It covers OSON inline storage and the flex guardrail, the partition dimension,
the Exadata transferability split, materialized summaries, index-organized
tables, and row compression. Each section states the mechanism, the modeling
consequence, and where the tooling enforces it.

## OSON inline storage and the flex `LIMIT` guardrail

**Mechanism.** A JSON value is stored inline in the row while it fits the
block (practitioner figure ≈7,950 usable bytes at 8K — Oracle publishes no
number); past that it falls to SecureFiles LOB storage. The fall is a cliff,
and it is *sticky*: a document that grows across the threshold moves to the
LOB class and does not move back as it shrinks. On a small buffer cache the
cliff is steeper — every read of an out-of-line document is extra I/O.

**Consequence.** Documents that hover near the threshold decay silently: the
design that measured fast at seed time degrades in production as rows fatten.
Size aggregates at typical AND P99 (see the
[review checklist](review-checklist.md)).

**Mechanism, enforced.** The hybrid shape's flex column is emitted as
`flex JSON (OBJECT LIMIT 8192)` — the inline *guarantee*: an insert that
would exceed the limit is rejected with ORA-42712 rather than silently
demoted, so the decay hazard is impossible by construction for the flex
lane. (Live-verified grammar note: the LIMIT belongs inside the
type-constraint parentheses; `JSON (OBJECT) LIMIT n` raises ORA-03099.)
**RULE.** The flex column always carries the `LIMIT` clause unless the user
disables it (`--flex-limit N` / `--no-flex-limit`).
**CHECK.** `tooling/generate/ddl.py` emits the clause;
`tests/test_hybrid_shape.py` pins it.

## The partition dimension

**Mechanism.** Partitioning divides one table into independently managed
segments. Pruning skips segments a predicate cannot match; `DROP PARTITION
... UPDATE INDEXES` removes a segment as a metadata operation — retention
without a `DELETE`'s redo, undo, and high-water-mark debris. Licensing is
settled: Oracle Partitioning is included on Oracle Database Free
(per-offering tables of the Licensing Information User Manual, verified).

**Consequence.** Lifecycle is a *dimension*, not a shape: the same design
measured with and without partitioning answers "what does retention cost me"
directly. Local indexes drop with their partition (nothing to maintain);
global indexes survive a drop but need maintenance — `UPDATE INDEXES` keeps
them usable at a cost.

**Mechanism, enforced.** A per-entity `partition` block (`interval` |
`auto_list` | `hash`) emits the clause in the relational AND hybrid lanes;
derived B-tree indexes on a partitioned entity go `LOCAL` by default
(`local_indexes: false` opts out); `--no-partition` measures the same
designs unpartitioned, and the emitted winner is always built exactly as
measured. **CHECK.** `tooling/generate/ddl.py`,
`tests/test_partition_dimension.py`.

**Disclosed limits.** Document collections are not partitioned by this block
(the documented route is an expression column over a JSON field — not yet
generated; treat as prose guidance). A duality view over a partitioned base
is doc-unstated territory — live-proven on 26ai Free (the view creates and
answers; `tests/test_live_hybrid_partition.py`), still absent from the
documented participation rules, so treat it as plan-proven, not promised.

## Exadata transferability — the access-path split

**Mechanism (research-verified, adversarial 3-0).** Exadata Smart Scan
offloads predicate filtering, column projection, and bloom joins to storage
cells — but ONLY for direct-path full-segment scans (full table scans, fast
full index scans). Single-block buffer-cache B-tree access never offloads.
Storage indexes (automatic per-1MB min/max) and zone maps prune only when
data is physically clustered on the predicate columns. No parameter makes
Exadata behave like conventional storage — disabling offload still leaves
flash caching, storage indexes, and the fabric.

**Consequence.** A verdict this optimizer measures on Free splits cleanly:

- **Point-read-decided margins TRANSFER** — the winning access paths behave
  the same on Exadata.
- **Scan-decided margins are ENVIRONMENT-CONDITIONAL** — offload cheapens
  exactly the side of the break-even the loser was penalized on;
  re-validate on the target before committing architecture to it.
- **The modeler's Exadata lever is physical clustering** (partitioning,
  attribute clustering, sorted loads), not index declaration — storage
  indexes and zone maps only prune clustered data.
- **Relative write-cost rankings likely transfer**: write-back flash
  compresses absolute latencies for every shape alike; no verified evidence
  changes the relative ordering between designs.

The optimizer report states this per election (`decided by: …` —
`tooling/optimize/runner.py`); the disclosure is generated from the measured
plans, not assumed.

**JSON offload.** Exadata System Software 24.1 adds automatic in-memory
columnar caching of JSON (both the native JSON type and OSON-format BLOBs)
in flash cache, with Smart Scan offload of `JSON_EXISTS`, `JSON_VALUE`,
`JSON_QUERY`, and `IS [NOT] JSON` — stated by Oracle "in conjunction with"
Database In-Memory, so treat the licensing precondition as unresolved and
verify on the target; `JSON_TEXTCONTAINS` is not listed as offloadable.
Document-shape scans therefore have a smart-scan path on current Exadata,
conditional on that coupling — below ESS 24.1 treat document scans as
environment-conditional like any other scan.

## Materialized summaries — the precompute inequality, measured

**Mechanism.** A materialized view stores an aggregation's result and the
engine maintains it; the refresh mode decides who pays and when. `REFRESH FAST
ON STATEMENT` maintains the view inside the DML statement itself — but only for
join-shaped views: an aggregate (GROUP BY) MV is refused with **ORA-32428**
("on-statement materialized join view error: Shape of MV is not supported"),
live-verified on 26ai Free 23.26.2. What remains, and what ships, is `REFRESH
FAST ON COMMIT` over materialized view logs: the log on each base table
(`WITH ROWID, SEQUENCE (<cols>) INCLUDING NEW VALUES`) records the deltas, the
commit applies them incrementally, and the COUNT companions in the view's
select list are the eligibility price of fast refresh for SUM/AVG. Complete and
on-demand refresh buy a *stale* answer — cheaper writes for a consistency
window a correctness gate cannot honestly wave through.

**Consequence.** This reconciles [field lesson 16](field-lessons.md) — the
on-commit fast-refresh MV as precompute's gold standard, zero application code
and zero consistency window — with what a measurement harness can actually
charge: the gold standard is exactly the form deployed, so the measured design
is the emitted design. The cost moved; it did not vanish. Every committing
writer now pays incremental maintenance for every summary rooted on the table
it touched, and that is a *write* cost, not an operational footnote.

**Mechanism, enforced.** Because maintenance lands at COMMIT, a summary
design's write cells are timed commit-inclusive: `execute + COMMIT` inside the
timed region, the compensating statement and its commit outside it, net effect
zero. Every other design's write cell is rolled back and never pays a commit,
so the bias runs AGAINST the summary — one that wins the election wins despite
the handicap, and the report discloses the per-write-pattern breakdown rather
than correcting it synthetically.
**RULE.** Maintenance is charged to the write cells of the design that declares
the summary and to no other design's cells — which is why the summary lane
carries its own `<table>_s` tables instead of hanging views off the shared
base tables.
**CHECK.** `tooling/optimize/runner.py` (the write protocol and the disclosed
breakdown), `tooling/generate/ddl.py` (the lane, the logs, the views),
`tests/test_summary_design.py`.

**The sizing hazard.** A summary's row count is not the base table's divided by
anything: a per-key summary's cardinality is the SUM of each key's reachable
set through every mapping on the path. [Field lesson 1](field-lessons.md) is
the arc — two per-advisor summaries sized at ~70M and ~77M rows against an
*assumed* ~170K-row advisor-to-book mapping; the real mapping arrived at ~36M
rows, the same summaries would have run to billions, and both were deleted in
favor of GROUP BY on the fact table. Size against production cardinality of
every mapping on the path before building, and remember the containers and
their logs count against the 12 GB Free cap like any other segment.

**Exadata.** Summaries **transfer** under the access-path split above: a
summary read touches a small container by index or a short scan, and the margin
it wins does not depend on offload. The Exadata-side declared alternative is
physical rather than derived — zone maps plus attribute clustering prune the
base scan with no second segment to maintain; prefer them when the target is
Exadata-class and the write rate is what defeated the summary.

## Index-organized tables — the table IS its primary-key B-tree

**Mechanism.** A heap table stores rows wherever they fit and the primary-key
index stores `(key → rowid)`; a PK read therefore costs the index traversal
*plus* one table access by rowid. An index-organized table removes the second
segment: the row itself lives in the leaf block of the PK B-tree, in key order.
The PK traversal IS the row fetch, and a range scan over the key returns rows
already sorted with no sort and no scattered table blocks.

**The overflow split.** A leaf block that must hold whole rows fills fast, so
long rows are split: `PCTTHRESHOLD n` (1–50) keeps the head piece of the row in
the leaf up to n percent of the block and pushes the tail to an `OVERFLOW`
segment; `INCLUDING col` names the last column that stays in the leaf and moves
everything after it out. Column order in the DDL is therefore load-bearing —
the split is positional, not by access frequency. Precedence, adversarially
verified: `INCLUDING` decides the division point, and `PCTTHRESHOLD` still caps
what the leaf will accept, so a head piece that exceeds the threshold is cut
back regardless of `INCLUDING`. A column pushed to overflow costs an extra
block read whenever a query touches it — the split is a bet that the hot
columns are the leading ones.

**Secondary indexes and guess decay.** A secondary index on an IOT cannot store
a physical rowid, because a leaf row moves whenever the B-tree splits. It
stores a **logical rowid**: the primary key value, plus a *physical guess* at
the block the row was in when the index entry was built. A correct guess costs
one extra I/O on top of the secondary index probe; a stale guess costs a full
PK traversal instead. Guesses decay as the base table's blocks split under
inserts — the design that measured well at seed time gets quietly slower with
no plan change to show for it. Staleness is observable: `PCT_DIRECT_ACCESS` in
the index dictionary reports the share of entries whose guess still lands, and
`ALTER INDEX ... UPDATE BLOCK REFERENCES` refreshes the guesses **online**,
without rebuilding the index. Reach for that, not a rebuild: a full secondary
index rebuild has to read the base table, which on an IOT means walking the PK
B-tree.

**Ceilings.** At most 255 columns may live in the index (leaf) portion of an
IOT; the table as a whole is capped at 1000 columns, and there is no evidence
that the extended 4096-column limit applies to index-organized tables — treat
1000 as the ceiling until a probe says otherwise. Both ceilings bite the same
design: a wide entity is a bad IOT candidate before any performance argument is
made.

**Composition, live-probed on 26ai Free 23.26.2.** The engine, not the doctrine,
fixed these rules. Only **hash** partitioning composes with an IOT — automatic
list and interval both raise **ORA-25198** ("partitioning method is not
supported for index-organized table"). Advanced Row Compression on an IOT
raises **ORA-00922**, so the two dimensions are mutually exclusive per entity.
A `CREATE MULTIVALUE INDEX` on an IOT raises **ORA-61714** ("Multivalue index
is not allowed on an IOT table") — which is why an entity carrying hybrid flex
properties may not also be an IOT: its flex predicates would still *run*, just
without their index, full-scanning silently. The flex column itself is
accepted inside an IOT with overflow; it is the index that is refused, and an
unindexed flex predicate is exactly the dishonesty this doctrine forbids.

**Consequence — the win profile.** An IOT pays for itself on PK-led point and
range access over **narrow** rows with **few** secondary indexes: one segment
instead of two, key-ordered range scans, no rowid hop. It loses on wide rows
(overflow reads), on secondary-index-led access (logical rowid indirection plus
guess decay), and on any workload that wanted the compress dimension or a
non-hash partition family instead. It is a dimension, not a shape — the same
design measured as heap and as IOT answers "what does the rowid hop cost me"
directly.

**Mechanism, enforced.** A per-entity `organization: "index"` block emits
`ORGANIZATION INDEX [PCTTHRESHOLD n] [INCLUDING col] OVERFLOW` in the
probe-pinned clause order across all three base-table lanes — the OVERFLOW
segment unconditionally, because name-inferred VARCHAR2(4000) columns make a
>50%-of-block max row the common case and an IOT without one cannot even be
created (live-isolated: ORA-01429 on the hash-partitioned form). `--no-iot`
measures the same designs as heaps.
**RULE.** The three engine conflicts are validation **blockers** naming the ORA
they prevent — IOT × compress (ORA-00922), IOT × a non-hash partition family
(ORA-25198), IOT × hybrid flex on the same entity (ORA-61714). A model that
would die on deploy dies in validation first.
**CHECK.** `tooling/generate/model.py` (validation), `tooling/generate/ddl.py`
(emission), `tests/test_iot_compress.py` (clauses, ordering, each conflict as a
planted red), `tests/test_live_iot_compress.py` (`user_tables.iot_type = 'IOT'`,
IOT × hash partition, answers, writes).

**Disclosed limit.** A duality view over an IOT base is doc-unstated territory —
live-proven on 26ai Free (the view creates and answers a point read;
`tests/test_live_iot_compress.py`), still absent from the documented
participation rules. Plan-proven, not promised; the same posture as the
partitioned-base finding above.

## Row compression — the two tiers' DML split

**Mechanism.** Oracle's row compression removes duplicate values within a block
by storing them once in a per-block symbol table and pointing the rows at it.
The tiers differ in *which writes get compressed*, not in the format. **BASIC**
compresses only direct-path operations — a direct-path load, a `CREATE TABLE AS
SELECT`, an `INSERT /*+ APPEND */`. Conventional inserts land uncompressed, and
an update decompresses the row it touches; a BASIC table under normal DML
therefore drifts toward being uncompressed while still reporting compression in
the dictionary. **ADVANCED** compresses under conventional DML as well, and it
does so in *batch*: rows are inserted uncompressed until the block reaches an
internally controlled fullness threshold, at which point the block is
compressed as a unit and the cycle repeats (vendor-FAQ verbatim, adversarially
verified). Only the transaction unlucky enough to trip the threshold pays the
compression CPU — the amortized cost per row is a fraction of the per-row cost
a naive model would predict.

**Consequence.** BASIC is the wrong tier for anything a workload writes
conventionally: measuring it would rank a design that does not survive contact
with production, so the dimension rejects it outright and states the reason.
ADVANCED is a genuine trade the harness can charge honestly — fewer blocks read
per row on the read side, threshold-triggered CPU and altered redo on the write
side. Both sides already have instruments: the existing write cells' elapsed
and redo diagnostics ARE the measurement, with `--no-compress` as the
counterfactual run of the identical design. No new report machinery, and the
emitted winner is built exactly as it was measured.

**Hybrid Columnar Compression is out of reach here.** HCC is licensed N on
Oracle Database Free and additionally gated by storage: on unsupported storage
the create fails with **ORA-64307** ("Exadata Hybrid Columnar Compression is not
supported for tablespaces on this storage type"). The supported-platform list
is open-ended and vendor-controlled, so treat HCC as unavailable on the Free
container and unverifiable from it — not as a knob to reach for later.

**Mechanism, enforced.** A per-entity `compress: "advanced"` block emits `ROW
STORE COMPRESS ADVANCED` after the column list and before any partition clause,
in all three base-table lanes; it composes with the partition dimension and is
refused on an index-organized entity (ORA-00922).
**RULE.** The compress allowlist is exactly `{advanced}` — BASIC is rejected
with the measured reason above, and no HCC tier is emitted.
**CHECK.** `tooling/generate/model.py` (allowlist, conflicts),
`tooling/generate/ddl.py` (clause and its position),
`tests/test_iot_compress.py` (emission, ordering, BASIC rejection, knob
removal), `tests/test_live_iot_compress.py` (dictionary shows
`COMPRESSION = ENABLED`, `COMPRESS_FOR = ADVANCED`).

## Oracle Version Notes

- `JSON ... LIMIT n` (the inline guarantee) requires Oracle Database 23.7 or
  later on the 23ai code line; on earlier releases the flex column deploys
  without the clause and the inline-threshold guidance above applies.
- The Exadata JSON columnar cache and JSON operator offload arrive with
  Exadata System Software 24.1.0 paired with Oracle Database 23ai.

## Sources

- Oracle Database Licensing Information User Manual (26ai) — per-offering
  feature tables (Free column): partitioning, compression, In-Memory rows.
- Oracle JSON Developer's Guide (26ai) — OSON storage, JSON type limits.
- Oracle VLDB and Partitioning Guide (26ai) — pruning, partition
  maintenance, local vs global indexes.
- Oracle Database Data Warehousing Guide (26ai) — the materialized views and
  refresh chapters: refresh modes, materialized view logs, and fast-refresh
  eligibility for aggregate views.
- Oracle Database Administrator's Guide (26ai) — the index-organized tables
  chapter: row-in-leaf storage, `PCTTHRESHOLD`/`INCLUDING` and the overflow
  segment, logical rowids and physical guesses, `PCT_DIRECT_ACCESS` and
  `ALTER INDEX ... UPDATE BLOCK REFERENCES`, the column ceilings.
- Oracle Advanced Compression FAQ and the Advanced Compression technical brief
  — the BASIC vs ADVANCED DML split and the block-fullness threshold that
  triggers batch recompression (quoted verbatim, adversarially verified).
- Oracle Exadata System Software User's Guide — Smart Scan offload
  qualification, storage indexes, write-back flash cache; the coupled
  database-features pages for JSON columnar cache and operator offload.
- Project research corpus: three adversarially verified deep-research runs
  (2026-07), session records.

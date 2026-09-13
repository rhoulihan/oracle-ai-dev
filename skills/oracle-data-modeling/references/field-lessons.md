# Field lessons — war stories with numbers

Measured lessons from real engagements, migrations, and production incidents,
generalized (no customer, product, or person is identifiable) with the numbers
kept. Each entry is a rule a fresh agent can quote to a skeptical developer:
**Lesson** (the rule), **What happened** (the story and its measurements),
**Apply** (what to do differently in a model review). Use them as evidence when
the [decision rules](decision-rules.md) or the
[measured optimizer](optimization.md) need a "this actually happened" anchor.

---

## 1. The financial-services PoC: five denormalization lessons from one measured arc

**Lesson.** Denormalization is a sequence of gated, measured moves — not a reflex.
Stonebraker and Pavlo's standing warning applies ("prejoins are not necessarily
faster than joins"): every derived structure must earn its place under production
cardinality, and the order in which you add them decides how much you build that
you later throw away.

**What happened.** A financial-services PoC on Oracle Autonomous Database took a
40-query advisor-workload suite from a **~0.83 s** customer baseline to
**~0.16 s** average (**−81%, all 40 queries faster, 0 regressions**). Five
lessons, in the order they were paid for:

1. **Derived tables scale with the mapping, not the entities.** Two per-advisor
   summary tables (~70M and ~77M rows) delivered 3–5 ms queries — at the
   *assumed* mapping cardinality of ~170K rows. The customer's real
   advisor-to-book mapping arrived at ~36M rows — **over 200× larger** — and the
   same summaries would have exploded to billions of rows. Both were **removed**
   from the design; the queries were rewritten against the fact table with
   GROUP BY and ran ~0.4–0.5 s: slower than 5 ms, but buildable and
   maintainable. A per-key summary's row count is the sum of each key's
   reachable set *through the mapping*; size it against production cardinality
   of every mapping table on the path before building it.
2. **The winning order: hints out first, one fact table, global summaries, per-key
   last.** The first root cause was the customer's own embedded optimizer hints
   freezing full-scan plans — those came out before any schema change. Then one
   denormalized fact table (10.4M rows, pre-joining the account–book–investor
   chain with a covering index) fixed **28 of 40 queries** by itself. Then a
   single *global* summary (2.5M rows, one per investor, three DESC indexes
   matching the three sort orders) took five list queries from ~0.5–0.8 s to
   ~5–6 ms. Per-key summaries came last — and did not survive (see 1).
3. **JSON construction belongs outside the sort/limit boundary.** The original
   views built a JSON document for every candidate row *before* `ORDER BY …
   FETCH FIRST 100` — constructing documents for ~7M rows to return 100. The
   worst query **hung indefinitely**; restructured so raw columns are sorted and
   limited first and JSON is built only for the 100 survivors, it ran **0.39 s**.
   The shape:

   ```sql
   SELECT JSON_OBJECT('advisor' VALUE advisor_id, 'total' VALUE total_value)
   FROM  (SELECT advisor_id, total_value
          FROM   advisor_totals
          ORDER  BY total_value DESC
          FETCH  FIRST 100 ROWS ONLY);
   ```

   Document projection is presentation. Sort and limit raw columns; construct
   JSON for survivors only.
4. **Access paths flip with cardinality — and caching is not a modeling fix.**
   Nested-loop index probes that were optimal at ~170K mapping rows produced
   **8M+ random I/Os from ~20K probes** at ~36M rows (a worst-case key touching
   ~20K parent rows across ~7M accounts and ~2.5M clients); a parallel full scan + hash
   join was the correct shape at scale. `RESULT_CACHE` was tried and
   **rejected**: it is incompatible with PARALLEL execution and hides the
   first-call cost instead of fixing it. Pair every index recommendation with
   the cardinality assumption it was measured under.
5. **Trigger-maintained denormalization needs a bulk-load protocol.** The
   surviving derived tables (~13M rows total) are maintained by row-level
   triggers doing **delta arithmetic** (`total += new − old`), never
   recomputation. For batch loads the protocol is: disable triggers → bulk-load
   base tables → re-seed derived tables in parallel → re-enable triggers →
   re-gather stats. Measured: ~67M base rows loaded in ~18 minutes, ~13M derived
   rows re-seeded in **under two minutes** (trigger-driven maintenance of the same load
   would take hours), stats 14 s — a 20.4 min clean install. A denormalization
   is not designed until *both* write paths (OLTP trickle and batch) are.

**Apply.** In a brownfield review: flag hint-frozen plans before proposing
schema; recommend fact-table-first ordering; gate any per-key summary on the
mapping-cardinality computation; generate JSON-projecting Top-N queries in the
two-layer form; and always emit the bulk-load protocol alongside any
trigger- or MV-maintained summary, with both write costs in the cost matrix.

## 2. A win at the wrong scale is not a win

**Lesson.** Benchmark at production cardinality or not at all — and assert every
benchmarked query returns a non-empty result, because a query that returns
nothing is infinitely fast.

**What happened.** The same PoC produced an interim "victory": a **~0.11 s**
suite average (−86%) that was celebrated — and meaningless. It was measured at
the assumed mapping cardinality, **213× smaller than production**, and the two
headline tables that powered it were later removed because they could not exist
at real scale. Separately, **7 of the 40 queries returned zero rows** against
the synthetic data: `LIKE` patterns and `BETWEEN` ranges that never matched the
generated distribution (a range of 300M–1B against actual values reaching
3.2B). Their timings measured nothing.

**Apply.** Require stated production cardinalities per table and per mapping
before measuring; mark any verdict produced at assumed scale as provisional.
Sample query parameters from the seeded data and assert non-empty,
expected-magnitude result sets before a timing counts. The optimizer's
"equivalence before speed" gate catches designs disagreeing with each other;
this is the complementary trap — all designs agreeing on an empty answer.

## 3. Normalizing away the arrays: roughly 9–15× on the same engine

**Lesson.** For entitlement and array-containment access patterns, the document
shape with a multivalue index beats a fully normalized relational decomposition
*on the same Oracle engine*. Full normalization of array-of-subdocument
entities is a measured mistake for those patterns — this is the other half of
the 90/10 rule, bracketing the relational win on complex joins.

**What happened.** The same multi-gigabyte corpus (~840K financial-services documents,
entitlement-heavy, multi-array) was benchmarked as an Oracle JSON collection
and as a fully normalized 27-table Oracle relational schema, over nine
production-derived queries with cross-shape result validation. Entitlement and
array-containment filters: the relational shape lost **roughly 9–15×** — the
headline query ran **~17 ms p50 relational vs ~1.2 ms document** — because the
normalized shape pays multi-child-table joins for what a multivalue index
answers in place. The unwind-and-rank pattern also went to the JSON shape
(4.51 ms p50). Only one pattern (unwind + range filter) went to relational, and
only narrowly (2.45 ms). Shape per pattern, one engine — measured.

**Apply.** When the dominant patterns are multi-valued authorization, tag, or
containment filters, recommend a JSON collection + multivalue index and cite
these numbers; do not decompose arrays of subdocuments into child tables just
because relational is available. Keep the converse honest: join- and
aggregate-heavy patterns still go relational.

## 4. The API tax is shaped like the query, not the wire protocol

**Lesson.** On Oracle's MongoDB-compatible API, simple indexed finds run at
parity with (or faster than) hand-written SQL/JSON over JDBC — but aggregation
pipelines pay 3–15×. Route CRUD and finds through the API freely; project
pipeline-shaped work (unwind/group/window) as SQL.

**What happened.** The same nine-query harness ran each query through both
access paths against the same Oracle instance. Indexed finds: the API *beat*
JDBC SQL/JSON on four of five. Pipelines: 3–15× slower p50 with catastrophic
tails (one query: 74.79 ms p99 via the API vs 1.81 ms as SQL). Two capability
notes with modeling impact: window-function stages may not be supported through
the API (the count moved into SQL as `COUNT(*) OVER ()`), and one
array-element filter needed an explicit hint before the plan used the compound
array index.

**Apply.** In migration lane routing: leave finds and CRUD on the API, rewrite
hot pipelines as SQL over JDBC, and plan-check that array-element predicates
actually use the multivalue/compound index (hint or re-gather stats if not).

## 5. Ungoverned documents drift: a representative profile

**Lesson.** "Schemaless" without engine-side governance decays into synonym
fields, forked enums, and orphan keys — and every consumer inherits the mess.
Schema flexibility is a decision you defer; defer it *in the engine* (JSON
Schema validation, canonical naming, a projecting view), not in every reader.

**What happened.** A representative drift profile, assembled from real
schema reviews and reproduced here synthetically. A device-fleet maintenance
log, ~1,200 documents in one collection:

| Field | Documents | Problem |
|---|---:|---|
| `technician` | 1,138 (95%) | canonical spelling |
| `tech_name` | 62 (5%) | the same field, forked by a later writer |
| `status: "completed"` | 890 | the enum's canonical value |
| `status: "complete"` | 74 | the same category, second spelling — every filter needs both |
| `weather_notes` | 1 | orphan field from a one-off script |
| `legacy_import_batch` | 1 | orphan field from an import nobody remembers |

Every query that filters on technician or completed status silently misses the
minority spelling; nobody notices until a report disagrees with an invoice.

**Apply.** In any document-model review, run field-frequency analysis over a
sample (a data guide does this). Low-frequency near-synonyms of a hot field and
enum values that differ only by spelling are defects, not diversity: fix the
writers, add an engine-side JSON Schema constraint so the fork cannot recur,
and project a canonical view over the legacy shapes during cleanup.

## 6. The 2M-document session collection nobody designed

**Lesson.** Ephemeral, machine-generated documents (sessions, tokens, carts,
job leases) need a designed size bound — a TTL plus a removal mechanism proven
to run on the *target* platform. And on the MongoDB-compatible API, never
`drop()` a live collection to clean it: purge with `deleteMany` on the expiry
field instead.

**What happened.** A small production Node.js app minted a session document per
request (eager session middleware plus a load balancer's health checks), with a
24-hour max-age and a backend that ran no TTL sweep. The sessions collection
silently grew to **~2 million documents** and slowed every request in the
system — not just its own path. The fix (short TTL, store-level interval
removal, health endpoint moved ahead of session middleware) bounded it to
~14K documents. The recovery gotcha: dropping the live collection would have
caused a partial outage — new writes fail while existing traffic still works —
so the purge had to be `deleteMany` on the expiry field. Diagnostic heuristic:
slow-and-getting-*slower* is never the network; something is growing.

**Apply.** Review checklist: every collection gets a growth bound (TTL, rolling
partition drop, bucket) or an explicit "unbounded by design" justification —
and the removal mechanism is *verified to run* on the deployment target, not
assumed from driver docs. Document the non-`drop()` purge procedure for any
collection that must stay live.

## 7. Count is not load — and infrastructure writes are access patterns

**Lesson.** Rank access patterns by frequency × cost, not raw count; and
enumerate the patterns your platform generates, not only the ones your
application declares.

**What happened.** Same system, two corrections. (a) A health-check endpoint
was ~99% of request traffic and approximately zero load — static, pre-session,
no database touch. 99% of traffic is a scary count, not a load; the momentum to
"fix" it was bias, not evidence. (b) Meanwhile the busiest *write* pattern in
the system — the session document minted per request — appeared in nobody's
access-pattern table, because nobody had designed it. Middleware, health
checks, session stores, audit hooks, and retry queues all read and write.

**Apply.** Intake additions: weight every pattern by cost, not count — a
hot-but-free pattern must not shape the model; and ask "what does your
middleware/platform write per request (sessions, audit, telemetry)?" — those
are access patterns and belong in the table with the rest.

## 8. Claim at the layer you measured

**Lesson.** Attribute a measured win to a cause at the same layer you measured
it. Storage-format primitive ratios do not surface through pipeline or workload
benchmarks — per-row evaluator dispatch (microseconds) swamps the primitive
delta (nanoseconds) — so never present a primitive ratio as an expected query
speedup, and never explain a workload result with one.

**What happened.** A planned benchmark scenario was deliberately removed from a
public suite after measurement showed the predicted crossover from a
field-access primitive advantage never appeared at pipeline level: the
architectural *shape* was confirmed (per-access cost rising on the
length-prefixed format, flat on the offset-indexed one — an O(n)-vs-O(1)
*design property*, not a measured throughput claim), but the end-to-end ratio
stayed a fraction of the naive prediction. Rule of thumb: claims below the
SQL/aggregation evaluator (on-disk layout, page mechanics) need their own
harness; claims at or above it (planner, pipeline shape, write path) belong in
a workload bench.

**Apply.** When the optimizer reports a winner, explain it with plan-level
causes (index used, join method, rows examined) — never with storage-format
physics. When a stakeholder quotes a primitive ratio as a workload promise,
this is the rebuttal.

## 9. The benchmark methodology triad

**Lesson.** A cross-engine or cross-shape claim is defensible only with three
disclosures: **durability parity**, a **cache-unbound proof**, and the
**winner's handicaps**.

**What happened.** Field benchmarks that skipped these got (rightly) attacked.
(1) Durability parity: an engine whose default write concern acknowledges
before journal sync is not comparable to one that always waits for redo on
COMMIT — equalize guarantees (journaled acknowledgment on, replica-set
semantics stated) before timing writes, or the numbers are fiction.
(2) Cache-unbound proof: pre-empt "you starved it for RAM" by showing the
working set fit in cache for *both* engines and the loser still lost — if
doubling the host's memory would not change the headline, say so with the
cache-fit numbers. (3) Disclose the winner's handicaps: when the winning
engine's headline features were off (e.g. scan offload and in-memory features
unavailable on a free tier), the result is conservative — disclosing that
strengthens the claim.

**Apply.** The optimizer's written guidance already demands equivalence before
speed and unit discipline; extend every cross-engine comparison with the triad.
A benchmark writeup missing any leg is a draft, not evidence.

## 10. Validation is not the bottleneck

**Lesson.** "We skipped schema validation for performance" is not supported by
measurement. Engine-level validation compiled once at DDL time is cheap —
measured internally; benchmark publication forthcoming — and the only
expensive validation shape is recompiling the schema per call (validating in
app code, or through a compile-per-row extension).

**What happened.** An internal eight-engine harness over a ~100-case corpus
found compiled, engine-level JSON Schema validation cheaper than every
alternative measured, while the compile-per-call integration shape cost orders
of magnitude more. The performance argument, examined, favors *more* engine
validation, not less.

**Apply.** When a review finds a collection with no validation ("a validator
that doesn't fail is just decoration"), recommend engine-side JSON Schema with
`PRECHECK` where useful, and answer the inevitable performance objection
qualitatively: compiled-in-the-engine is the cheap shape; per-call is the
expensive one.

## 11. Look first: the most expensive database is the one you migrate to

**Lesson.** Before scoping a re-platform to acquire capabilities, audit whether
the platform already licensed provides them at its *current* release — teams
routinely compare a modern alternative against the old release they run. Then
price the true TCO against the base rate: large IT transformations fail at
**70–80%**, a rate that has not improved in 25 years.

**What happened.** Repeated field pattern: a shop evaluates a new stack while
the converged platform it already licenses sits several major releases behind —
the comparison is against the wrong incumbent. Public post-mortems of
nine-figure ERP and core-banking migrations document the base rate; cloud
repatriation surveys show a large share of migrations costing more than
expected. Sometimes the best migration is the one you don't do.

**Apply.** Pre-migration gate in the brownfield path: enumerate the target
capabilities, check each against the incumbent's current release, and force a
TCO tally (rewrite, testing, incidents, training, the inevitable Phase 2)
before recommending re-platforming.

## 12. Wire-compatible is not identical

**Lesson.** A wire-compatible API is faithful ~99.99% of the time; the defects
live at the edges and may reproduce only under production topology. Budget for
edge-shaped behavior; keep an app-level retry shim so user impact is decoupled
from fix timelines; use driver command-monitoring to turn a vague error into a
reportable defect.

**What happened.** A small production Node.js app migrated from a managed
MongoDB service to Oracle's MongoDB-compatible API. The developer's verdict:
one of the smoothest migrations on record, with a single snag: a geospatial
operator (`$near`) the API did not support, closed with the `$sql` escape
hatch. A later edge-case wire defect reproduced only under the production
connection-pool topology — and a *negative* repro in isolation was itself a
positive result, narrowing the trigger.

**Apply.** Set migration expectations as "high parity, edge-shaped risk":
retry shim + command monitoring during cutover; route operator gaps to `$sql`
or a native SQL rewrite; treat failure-to-reproduce as data.

## 13. Embeds may be forced, not chosen — unwind them

**Lesson.** Document-store views are read-only, so the only writable path to a
joined shape there is pre-denormalizing and owning the update anomalies — the
vendor's own guidance says to restructure via denormalization if you join
often. Heavy embedding in a migrated model is therefore often *forced*, not
chosen, and is a prime candidate to unwind into relational + a writable duality
view on Oracle.

**What happened.** The end-state of unpriced denormalization debt is on the
public record: a practitioner documented migrating **847 million records** from
a document store back to a relational system — and helping **34 companies**
through the same arc over eight years: initial excitement about developer
productivity, confusion about slow queries, sticker shock at infrastructure
costs, then migration back at enormous expense.

**Apply.** For every embedded structure in a migrated model, ask: was this
chosen (bounded, owned, co-accessed — keep it) or forced by the source engine's
read-only views and join costs? Forced embeds unwind to normalized tables plus
a duality view that keeps the document API contract — without the debt.

## 14. Every migration is a modeling exercise

**Lesson.** Access patterns migrate; mechanics follow. The modeling exercise
*is* the migration — DDL translation, data movement, and driver swaps are
downstream mechanics.

**What happened.** The largest public example: Amazon's documented migration of
~3,000 relational database instances to purpose-built NoSQL. What actually
moved was the *access patterns* — each workload re-modeled around what it asks
of the data; the technology swap followed. Access patterns are more stable than
technology, which is why access-pattern-driven designs outlive platforms.

**Apply.** Frame every "migrate X to Oracle" engagement as access-pattern
re-mapping: enumerate and rank the patterns first, choose target shapes per
pattern on the converged engine, and only then translate schemas and move data.

## 15. The backpack rule

**Lesson.** A request is a trip you make constantly; the document is the
backpack. Overpack and you pay the weight on every trip, forever; underpack and
you make extra trips to assemble. The right document is neither the largest
possible object nor the smallest fragment — it is the object shaped around
access. To pack well you must know the trip. (From the authors'
converged-database book project.)

**What happened.** This is the teaching frame that lands embed-vs-reference
with developers who tune out cardinality talk. Quantify "weight on every trip"
as bytes read × frequency, and "extra trips" as joins or round-trips ×
frequency — which is exactly the weighted cost the
[measured optimizer](optimization.md) computes.

**Apply.** Use the metaphor at intake to elicit the real trips (access
patterns), then replace the metaphor with the measured matrix.

## 16. Precompute's gold standard: the on-commit fast-refresh MV

**Lesson.** Precompute trades a consistency window for read efficiency — and
the engine sets how good the trade is. On Oracle, a materialized view with
`REFRESH FAST ON COMMIT` is the gold standard: zero application code, zero
consistency window, transactionally correct, incrementally maintained.

**What happened.** The published design-review arithmetic (Hoberman/Coupal)
makes the case for write-time computation: a workload reading 1,000,000
times/hour and writing 1,000 times/hour divides the computation by 1,000 by
moving it to the write path. On engines without engine-maintained aggregates,
that means stream processors or application triggers — extra code, an eventual
window, and a reconciliation job. The on-commit fast-refresh MV deletes all
three. (Where the refresh cannot be fast/on-commit, fall back to the trigger
delta-maintenance + bulk-load protocol of entry 1.)

**Apply.** When the precompute inequality (read-freq × read-cost > write-freq ×
maintenance-cost) passes, reach for the MV first, hand-maintained summaries
second — and check exact-first before approximating: the optimizer often makes
the exact aggregate cheap enough, and `APPROX_COUNT_DISTINCT` ships the sketch
natively when an estimate genuinely is the right trade.

## 17. Match the integrity pattern to the cost of the violation

**Lesson.** Not all data needs the same integrity machinery. The cost of the
pattern should be proportional to the cost of the violation it prevents.

**What happened.** Three recurring field archetypes: **duplicate patients**
(healthcare identity records created twice → wrong-patient treatment; fix:
unique constraint on the natural composite key), **oversold inventory**
(concurrent read-decrement-write both write the same count; fix: atomic
in-place update or optimistic lock), **double charges** (a processor retries a
timed-out charge; fix: idempotency key — see entry 19). Each fix costs more
than none; each violation costs far more than its fix. Ledgers get append-only
plus constraints; genuinely contended aggregates get version columns; most
tables need neither.

**Apply.** In review, tier every invariant: name the violation, price it, and
match the cheapest mechanism that actually prevents it — on Oracle most are
native (constraints, unique indexes, ACID transactions) rather than
application-level protocols.

## 18. Know your engine's defaults

**Lesson.** Integrity patterns assume the engine's guarantees hold — but
*defaults* can quietly void them. A migrated design may never have had the
guarantees it assumed.

**What happened.** The public Jepsen analysis of MongoDB 4.2.6 found that the
default write concern (`w:1`) acknowledges before replication: on a primary
crash, acknowledged writes vanish — in Jepsen's words, "the data is permanently
lost" — and default read/write concerns permitted dirty reads and broke causal
consistency unless both were raised to majority. The safe settings exist; they
are not the defaults, and they cost latency, so many deployments never enable
them. Oracle's ACID-on-by-default posture removes this class of footgun — a
COMMIT means redo is on disk.

**Apply.** In migration intake, audit the source deployment's actual
consistency/durability settings and surface the gap as a *modeling* risk:
unique-index and optimistic-locking designs built on weak defaults may have
been silently violating their own invariants. Verify what the design assumed
versus what the engine delivered.

## 19. Exactly-once is at-least-once plus idempotency — in the same transaction

**Lesson.** The network cannot deliver exactly-once; it can deliver
at-least-once. Exactly-once *execution* = at-least-once delivery + idempotent
processing, and the idempotency check must commit **in the same database
transaction** as the business write — otherwise a crash between them
re-introduces the duplicate.

**What happened.** The double-charge archetype (entry 17): a serverless handler
charges a card, times out before acknowledging the queue message, and the
message redelivers — charging again. The fix that holds is an idempotency key
checked and recorded inside the transaction that performs the charge. Prefer
naturally idempotent operations where possible: an absolute `SET` guarded by a
version beats a relative increment.

**Apply.** For event-driven and agent-facing models on Oracle, store the
idempotency key in the same transaction as the business write (trivial under
ACID); design mutations as conditional absolute sets over relative increments
where the domain allows.

---

## 20. A passing plan proof is necessary, not sufficient

**Lesson.** Before recommending a database solution, check that it does not
depend on internal columns, undocumented byte layouts, or reverse-engineered
expressions — prefer the documented idiom that states the intent directly.
"Clever" is a warning, not a win.

**What happened.** Working out how a SQL predicate and a Mongo-API lookup could
share one index, the first solution got the right plan through an internal,
undocumented column and its raw type-tag bytes, plus a verbose reverse-derived
`JSON_EXISTS(... TYPE(STRICT))` form. Every proof passed. Expert review still
rejected it as unshippable: the same behavior is expressed by the documented
forms — simple dot notation for fields, `."_id".idOnly()` /
`JSON_SCALAR(... AS ID)` for id comparisons — which say the intent and survive
upgrades. The plans were identical; only one version was supportable.

**Apply.** Add a review question after any plan proof: does this depend on
anything undocumented? If yes, find the documented idiom for the same behavior
before shipping the guidance — and treat unusual cleverness in a database
recommendation as a prompt to look for the sanctioned spelling of the same
thing.

## 21. Identity columns are not row counters — never key generated content off MAX(id)

**Lesson.** `GENERATED ALWAYS AS IDENTITY` promises uniqueness, not density.
The backing sequence caches (default 20) and discards on session end, failed
runs, and restarts — so id gaps are normal, and any seeding or generation
logic that derives state from `MAX(id)` silently diverges from reality.

**What happened.** A deterministic data generator appended rows toward a
target count using `MAX(ticket_id)` as its progress cursor, across a few
interrupted and retried sessions. Result: **8,080 rows with MAX(id) =
29,520** — the loop "reached" its 10,000-row target at barely 80% of the
rows, with the LCG-seeded content stream desynchronized on every retry. The
same generator run once, in a single fresh-init session, produced exactly
10,000 contiguous ids and byte-identical content on every rebuild.

**Apply.** Drive generation loops off `COUNT(*)` (or an explicit loop
counter persisted with the data), never `MAX(identity)`. For deterministic
corpora, make the canonical path a single-session cold init and re-seed any
PRNG from a fixed constant at each phase boundary — determinism you only get
on the happy path is not determinism. Treat identity values as opaque:
uniqueness is contractual, contiguity is luck.

## 21. Seed scale can invert the verdict — a small-seed winner is provisional

**Lesson.** A design chosen on a seed that cannot stress the deciding pattern
has been chosen on its *incidental* costs. State the deciding pattern's row
counts; if it degenerates (a range aggregate touching a handful of rows), say
the run cannot decide rather than reporting a winner.

**What happened.** The same schema, patterns, and rates were benchmarked at
two seed scales. At 25,000 bookings the harness chose **duality, +27.3%,
"separates."** At 500,000 it chose **relational, +8.3%, inside a 22.8% noise
floor — a tie.** Only the row counts changed. Duality's small-seed lead came
from cells that shrink as data grows; the document design went from +79% to
+430% because at small scale nothing had stressed it; and a single-table
hybrid's point read went 2,476µs → **40,377µs** — an anchor with no access
path for the pattern, nearly invisible small, catastrophic large. The deciding
range-aggregate touched ~19 rows per key at the small scale: it measured
nothing, quietly.

**Apply.** Alongside "benchmark at production cardinality" (lesson 2): report
the rows each deciding pattern actually touched; treat any verdict whose
deciding pattern degenerated as *no verdict*; and when a shape's cost is flat
across scales while another's grows, say which cells are scale-sensitive.

## 22. Generate seed data IN the database, not as literal INSERTs

**Lesson.** Emit set-based seed SQL — `INSERT ... SELECT` over
`CONNECT BY LEVEL <= :n` with `ORA_HASH` for deterministic pseudo-randomness —
and derive the document lane FROM the relational rows in the same statement.

**What happened.** Literal INSERTs did not survive scale: 25,000 bookings was
already a 14 MB file; 500,000 would have been ~280 MB. The set-based rewrite
produced the same data from a **23 KB file** loading 500k bookings in 43s.
Deriving documents from the relational rows (`JSON_OBJECT ... ABSENT ON
NULL`) made lane drift impossible, and `ORA_HASH` removed RNG
order-sensitivity — a Python RNG had reshuffled every downstream fixture when
one line moved, silently turning a write pattern into a zero-row update.
Three sharp edges: generated seed files must carry **no comments at all** (a
runner splitting on `;` drops the statement after a leading comment block and
executes a trailing one as SQL — both happened); JSON documents past the
4000-byte literal cap need `TO_CLOB` concatenation split so no chunk cuts an
escaped quote; and sequences created `START WITH <constant>` land inside the
data at the next scale — derive from `MAX(id)` and create them **after** the
seed.

**Apply.** Seed guidance: set-based generation, one lane derived from the
other, ORA_HASH over RNGs, comment-free seed files with provenance in a
sidecar, sequences after seed. Fixtures (ids, keys used by write patterns)
are **queried from the seeded database**, never hardcoded from the generator.

## 23. The reference design can be the broken one

**Lesson.** The equivalence gate compares designs against each other — it
cannot see that the *reference* is wrong. Audit the baseline's own semantics
before trusting any comparison built on it.

**What happened.** Three ways, one run. The generated relational baseline used
inner joins only, so 25% NULL foreign keys silently dropped rows from the
reference every other design was compared against (19 rows vs the document's
correct 28). A document that answered `_id` had not answered `Entity.id` —
the gate skips `_id`, so the natural key must ride alongside it. And a child
reached through a fact table appeared once per line, inflating a COUNT by
thousands of groups. Separately: a pattern no design can express excludes a
design from the whole decision — disclosed now by the harness, but the
modeling answer is to fix or drop the pattern *and say which way the bias
runs*.

**Apply.** In review: check the baseline's join semantics against nullable
FKs (outer-join or filter deliberately); carry natural keys in documents,
named for the entity property they answer; aggregate children at the right
grain, not through a fact table; and treat "every design agrees" as necessary,
never sufficient.

## Oracle Version Notes

- All Oracle-side behavior referenced here (multivalue indexes, `JSON_OBJECT`
  with `FETCH FIRST`, `RESULT_CACHE` semantics, `REFRESH FAST ON COMMIT`
  materialized views, `APPROX_COUNT_DISTINCT`, JSON Schema validation with
  `PRECHECK`) is current as of Oracle AI Database **26ai**; none of it is
  RU-sensitive.
- The measured figures were produced on Autonomous Database and 26ai Free-tier
  instances; free tiers run without scan offload or in-memory features, so
  Oracle-side numbers are conservative there.

## Sources

- Materialized view refresh (`REFRESH FAST ON COMMIT`) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/dwhsg/
- SQL/JSON generation and `JSON_OBJECT` —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
- `APPROX_COUNT_DISTINCT` —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/
- M. Stonebraker & A. Pavlo, "What Goes Around Comes Around… And Around," SIGMOD
  Record, 2024 — the three classic denormalization problems ("prejoins are not
  necessarily faster").
- Jepsen analysis of MongoDB 4.2.6 (2020) — default write/read concern findings
  (public record).
- S. Hoberman & D. Coupal — Align→Refine→Design; the read/write-ratio argument
  for write-time computation (published).
- Amazon's public history of migrating ~3,000 relational database instances to
  purpose-built NoSQL (public record).
- Entries 1–9, 12: generalized field engagements, production incidents, and
  internal harness measurements (field-verified, 2025–2026). Entry 5 is a
  synthetic exhibit reproducing drift shapes observed across real reviews.
- Entry 15 framing: from the authors' converged-database book project.

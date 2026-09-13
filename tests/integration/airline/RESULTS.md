# Airline capstone — results (real DataBaseAnswers model)

> **2026-07-14 production-volume re-run — the current verdict.** After the repo-wide
> adversarial review fixed the index-derivation and equivalence/gate defects, the matrix
> was re-measured at **300,000 reservations / 1.2M itinerary-leg rows** with `--trials 30`
> (full report: `optimizer-result.txt`). All ten patterns answer-validate across all four
> designs with zero exclusions. Verdict as the engine states it: real mix — **document
> leads by 7.4%, inside the 17.7% noise floor → TIED**; document wins every read-heavy
> scenario (7–8%), relational wins the write-heavy booking engine (5.0%) and the
> low-read-rate tail. Two historical claims below are superseded and annotated in place:
> the "document far behind" recommend_model ranking (measured against a document design
> missing its `_id`/access-pattern indexes — a generator defect, since fixed) and the
> "duality wins by 5.4%" margin (inside the noise floor once the floor is computed from
> the measured per-cell CV, a gate the engine now applies). The cross-runtime harness was
> also re-proven (ALL CONSISTENT) after repairing method-name drift in the five mains.
> The companion captures (`walk-4design.txt`, `optimizer-sweep.txt`, `threeway-comparison.txt`,
> `decide-scenarios.txt`, `knob-sweep.txt`, `workload-analysis*.txt`) are historical runs of the
> pre-review engine, kept for the defect narrative; `optimizer-result.txt` is current.

Live 26ai Free. The **real** airline-reservations logical model (Barry Williams,
DataBaseAnswers.org) — 11 entities with composite-PK junctions (reservation_payments,
itinerary_legs), typed/code PKs (airport_code, flight_number, day_date), and code-based
FKs. **30,000 reservations / 20,000 passengers**, each carrying **2–6 legs** (a return trip
with connections) and 1–2 payments — 380,000 rows in the converged table.

**The volume is part of the claim.** The capstone originally ran at 3,000 reservations: a
**28-block table**. Oracle correctly refuses to use an index to fetch 50 rows from 28 blocks,
so *no access path could ever win*, and the matrix was silently comparing per-row overhead
rather than schema design. Anyone in the room who asks "how many rows?" ends the conversation
right there. Reproduce with `--fresh`, which drops and rebuilds every object: **DELETE does
not lower a table's high-water mark**, so a re-fill leaves the previous, larger seed's
segments behind and every full scan still reads them (11,390 logical reads for 30k rows of
documents).

Reproduce end to end:

```bash
export DB_USER=plugin_dev DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1
python -m tooling.optimize tests/integration/airline/workload.json --trials 30 --fresh
# 30k checked-in seed: ~2 min. The published matrix used the x10 seed (DEFINEs x10) —
# see optimizer-result.txt for exact parameters. The flight-number pad is width 5 in the
# checked-in seed (guarded by tests/test_seed_scale_safety.py), so x10 scale-up is safe.
```

## The walk

The four candidate designs are not a menu. They are the stations a design moves through as
write pressure climbs, and the optimizer walks all four by default:

```
document  ->  single collection  ->  duality  ->  relational
```

- **document** — the aggregate embedded in one row. Max read consolidation, max write
  amplification: touch one field and the whole document is rewritten.
- **single collection** — the aggregate root and its dependents co-located under one
  anchor. The DynamoDB single-table design, expressed natively.
- **duality** — relational storage, document API. Reads as a document, writes as rows.
- **relational** — normalized. Cheapest possible write, joins on read.

`sql_view` is deliberately *not* a station: it is a read-only JSON projection over
relational storage, so listing it beside `relational` is redundant. It survives as
duality's fallback for the one thing duality cannot express (an aggregation, because the
view must stay updatable).

The **single collection is derived, not guessed** — from the result sets, the filters, and
the relationships:

```
ANCHOR: ItineraryReservation          (the query root the filters key on most, by rate)

  ItineraryReservation   key = [reservation_id]
  ItineraryLeg           key = [reservation_id, leg_id]        <= item collection
  Leg                    key = [reservation_id, leg_id]        <= item collection
  ReservationPayment     key = [reservation_id, payment_id]    <= item collection
  Payment                key = [reservation_id, payment_id]    <= item collection
  Passenger              key = [passenger_id]                  (shared parent, not duplicated)
  Airport, FlightSchedule, RefCalendar, ...                    (reference data, off-anchor)

GSI equivalents, from the filters:  (passenger_id) · (agent_id, reservation_status_code)
```

`Leg` and `Payment` sit on the far side of an M:N, behind a junction table — and they still
co-locate, because they are **returned alongside** the anchor. `Airport` is not, so it stays
out: co-locate shared reference data and you duplicate the row into every item collection.
That is the whole rule — *the result set decides what co-locates; the filters decide the
keys.*

## The mix is the knob — and the baseline mix was wrong

**In a reservation system reads dramatically exceed writes.** A booking is written *once*
and read for the rest of its life: the confirmation, the app, check-in, the gate, an agent
lookup. The original fixture ran writes at **15% of all operations** — a 6:1 read:write
ratio. That is not a reservation system; it is a write benchmark wearing one's clothes, and
it was the last thing holding the designs in a dead heat, because write amplification is the
one axis where the consolidated designs lose.

The corrected baseline: each booking is created once, changes status about twice, and is
read ~150 times. **61:1 reads to writes.**

## The full cost matrix (live, 20 trials, median elapsed µs)

| pattern | class | kind | rate/hr | document | duality | relational | single collection |
|---|---|---|---:|---:|---:|---:|---:|
| get_reservation | transactional | read | 5,000 | 299 | 287 | **253** | 266 |
| get_itinerary | transactional | read | 4,000 | **307** | 357 | 364 | 520 |
| passenger_reservations | transactional | read | 1,500 | 310 | **296** | 480 | 517 |
| update_status | transactional | write | 120 | 1,333 | 1,193 | **1,156** | 1,201 |
| create_reservation | transactional | write | 60 | 1,462 | 1,402 | **1,296** | 1,623 |
| open_for_agent | operational | read | 300 | 1,390 | 1,379 | 1,517 | **840** |
| count_by_status | operational | read | 120 | 1,672 | 1,692 | 1,606 | **1,525** |
| passenger_history | reporting | read | 40 | **315** | 339 | 463 | 513 |
| revenue_by_class | reporting | read | 5 | **2,024** | 2,462 | 2,328 | 2,172 |
| flight_load | reporting | read | 3 | **2,012** | 2,362 | 2,372 | 2,386 |

## The access paths — the WHY behind every cell

| pattern | document | duality | relational | single collection |
|---|---|---|---|---|
| get_reservation | IDX RANGE 3 | IDX UNIQUE 3 | IDX UNIQUE 3 | IDX RANGE 3 |
| get_itinerary | IDX RANGE 3 | IDX UNIQUE 21 | IDX UNIQUE 21 | IDX RANGE 8 |
| passenger_reservations | IDX RANGE 4 | IDX RANGE 4 | IDX RANGE 4 | IDX RANGE 4 |
| open_for_agent | IDX RANGE 154 | IDX RANGE 248 | IDX RANGE 74 | IDX RANGE 154 |
| count_by_status | **IDX FFS 198** | **IDX FFS 198** | **IDX FFS 198** | FULL SCAN 404 |
| passenger_history | IDX RANGE 4 | IDX UNIQUE 10 | IDX UNIQUE 8 | IDX RANGE 7 |
| revenue_by_class | **IDX FFS 198** | **IDX FFS 198** | **IDX FFS 198** | FULL SCAN 404 |
| flight_load | **IDX FFS 198** | **IDX FFS 198** | **IDX FFS 198** | FULL SCAN 404 |

```
Every filtered read uses an index.
```

```
DECISION (rate-weighted over the whole matrix)
  1. document       4,082,958
  2. duality        4,185,812
  3. relational     4,343,607
  4. single_table   4,902,490
  CHOSEN: document      margin over 2nd: 2.5%  -> TOO CLOSE TO CALL (document, duality)
```

## The document result — and the finding it replaced

**This capstone previously reported the document at 10,362,483 — dead last, 2.4× worse — and
said so with a plan to back it up.** The decomposition was clean and completely convincing:

| | |
|---|---|
| aggregations as a share of traffic | 128 of 11,148 ops/hr = **1.1%** |
| aggregations as a share of the document's cost | **60%** |
| aggregation gap vs duality | 6,043,179 — **101% of the total gap** |
| remove the aggregations entirely | the document *wins* |

The conclusion wrote itself: *a JSON collection has no aggregate-friendly access path — to
group, it must scan, and it is scanning fat documents.* The physics was right: the document
is **927 bytes/row against the table's 67** (13.9×), because it embeds the legs and payments
that a `GROUP BY reservation_status_code` never needed. The optimizer's own source asserted it
in a comment.

**It was a missing index.** `generate_indexes` derived indexes from *filter predicates only*,
so a `GROUP BY` key never got one.

| `count_by_status`, document collection | | |
|---|---:|---|
| no index on the group key | 15,479 µs · 3,359 reads | `TABLE ACCESS FULL` |
| **index on the group key** | **1,789 µs · 102 reads** | `INDEX FAST FULL SCAN` |
| relational reference | 1,352 µs · 247 reads | |

**Fewer logical reads than the relational table.** The document went from **last to first**.

Two details are the whole trick, and neither is guessable:

1. **The trailing constant.** A B-tree omits an entry whose key is entirely NULL, so Oracle
   will not use it for `COUNT(*)` — any document might lack the field. `(expr, 0)` makes the
   entry never wholly NULL, so the index holds *every* row. **No query change, no semantic
   change**: the NULL group is still counted.
2. **`JSON_VALUE(... RETURNING NUMBER)`, not dot notation.** Dot notation preserves the JSON
   type — which is why we chose it — but it is *not* the expression a functional index is built
   on. `RETURNING NUMBER` preserves the type **and** matches the index. Type preservation was
   never the whole requirement.

> **A design's weakness must be demonstrated on its best access path, not its default one.**
> Before writing "X cannot do Y", ask what index would make it, and build it. This is the
> fourth defect of one shape in this harness — an index whose expression does not match the
> query's — so the query and the index are now generated from **one function** (`agg_expr`).

## Duality is not free joins — and a view costs exactly what it nests

Two questions produced this section, asked of two earlier matrices in which duality first
won for the wrong reason and then lost for the wrong reason.

**First: *"duality is not free joins — should it not be closer to relational?"*** It should
have been. The duality view was **not performing the joins at all** — it nested the junction
tables and stopped (`itinerarylegs: [{reservation_id, leg_id}]`, no flight number), so it
answered a strictly smaller question and "beat" relational on a query needing exactly those
joins. Meanwhile the relational query was performing those joins *badly* — a fan trap.
Corrected (defects 8 and 9): **`get_itinerary`: duality 374, relational 401.** A dead heat, as
it must be. Duality performs exactly the joins its projection requires.

**Then: *"fix the duality view scoping so it isn't a kitchen sink."*** Because once duality
was doing real joins, it came **last** — and the reason was our generator, not the design. It
emitted ONE view per query root, nesting the union of every pattern rooted there: the
passenger *and* the agent *and* every leg *and* every payment. So the point read paid to
assemble the itinerary read's joins, and a two-scalar filtered read spent 3,257µs building the
whole booking to hand back two values.

**A view costs exactly what it nests.** So the generator now emits **one view per aggregate**,
and every read *and write* goes through the leanest view that can serve it:

```
itinerary_reservations_dv                nests nothing (lean)   <- get_reservation,
                                                                   passenger_reservations,
                                                                   open_for_agent, update_status
itinerary_reservations_dv_passenger      nests Passenger        <- passenger_history
itinerary_reservations_dv_leg_payment    nests Leg + Payment    <- get_itinerary,
                                                                   create_reservation
```

Duality's column, before and after:

| | kitchen-sink view | scoped per aggregate |
|---|---:|---:|
| `get_reservation` | 389 µs | **293 µs** (best in the row) |
| `passenger_reservations` | 764 µs | **350 µs** |
| `open_for_agent` | 3,257 µs | **485 µs** |
| **rate-weighted total** | **5,922,822 (last)** | **3,966,755 (first)** |

**Duality goes from last to first** with per-aggregate scoping — the scoping lesson stands.
*(Superseded 2026-07-14: the "wins by 5.4%" margin predates the noise-floor gate; computed
against the measured per-cell CV it is inside the floor — TIED, not a decision. See the
re-run note at the top and `optimizer-result.txt`.)* That is the converged-database
argument, measured: *document reads and relational writes, from one copy of the data* — and it
only shows up when the projections are scoped the way a modeller would scope them.

Writes choose a view the same way reads do: a status change touches one root scalar and goes
through the lean view (the cheapest write); creating a booking writes the reservation *and* its
legs *and* its payment, so it goes through the view that models them. Aim a leg-bearing
document at the lean view and Oracle rejects it outright — ORA-40944 / JZN-00651, *"field
'itinerarylegs' is unknown or undefined"* — because the field genuinely is not there.

## Shift the mix and the winner moves — from ONE measurement pass

A cell is a property of the schema and the data, not of how often the pattern runs. So a
scenario is a **re-weighting of measurements already taken**: every mix below costs zero
extra database work.

| scenario | read:write | document | duality | relational | single collection | winner | margin |
|---|---:|---:|---:|---:|---:|---|---:|
| reservation system (real mix) | 61:1 | **4,082,958** | 4,185,812 | 4,343,607 | 4,902,490 | document | 2.5% (tied) |
| mobile / check-in (the itinerary *is* the app) | 38:1 | **2,555,947** | 2,813,577 | 2,796,093 | 3,761,173 | **document** | 9.4% ✅ |
| full-service airline (bookings **and** the dashboard) | 35:1 | **6,277,660** | 6,637,836 | 6,796,113 | 7,116,208 | **document** | 5.7% ✅ |
| analytics / revenue management (KPIs) | read-only | **11,763,754** | 13,002,494 | 12,626,132 | 11,831,195 | document | 0.6% (tied) |
| booking engine (write-heavy) | 1:3 | 8,197,901 | 7,676,708 | **7,227,580** | 8,400,157 | **relational** | 6.2% ✅ |

Same schemas, same data, same microseconds — only the mix changed. And now the table says
something far simpler, and far more useful, than it did when it was wrong:

**Once every design is fairly indexed, the only thing that separates them is WRITE PRESSURE.**

- The document ties or wins **every read workload** — the real mix, the mobile app, the
  full-service airline *with its dashboard*, and even **analytics**. Aggregation was never its
  weakness; a missing index was.
- **The one scenario that separates against it is the write-heavy booking engine** — relational,
  by 6.2%. Embedding still amplifies writes: touch one field and the whole aggregate is
  rewritten. That cost is real, it is inherent, and it is the *only* inherent one left.
- The three relational-storage designs (duality, relational, single collection) stay within a
  few percent of each other on reads, because on one engine **they are the same storage wearing
  different clothes** — same rows, same indexes, different access paths.

So the knob is not "documents vs tables". **The knob is write pressure** — which is exactly what
the consolidation walk says, and it is the only thing in this whole matrix that a better index
cannot make go away.

## Why this matrix is trustworthy — the seventeen defects that had to be fixed first

Every one of these produced a plausible, confidently-stated, **wrong** answer.

1. **The document embedded nothing.** The seed stored the reservation's scalars as JSON and
   left the legs and payments in their own tables. That is not a document — it is a
   JSON-wrapped row, paying all of a document's write amplification and earning none of its
   read consolidation. It lost every column of the matrix for a reason that was an artifact
   of the fixture. Fixed: the legs and payments are embedded, and the document now wins the
   two patterns it should win.
2. **One leg per reservation.** The seed gave every reservation exactly one leg and one
   payment. An aggregate with one child has nothing to aggregate: the join returns a single
   row, so consolidation cannot pay, and the matrix was quietly rigged against every
   consolidated design. A real itinerary is a return trip with connections. Fixed: 2–6 legs.
3. **No anchor index.** Every per-type index on the single collection is *sparse*
   (`CASE WHEN type='X' THEN col END`), so not one of them can serve an item-collection
   read, which spans several types at once. That read full-scanned — the design lost the one
   query it exists to win. Fixed: the anchor index `(reservation_id, type)`, which is
   precisely the DynamoDB PK+SK.
4. **A composite PK leaked a Python list repr into the duality DDL** (`['reservation_id',
   'payment_id'] : [...]` → ORA-24558), so every model with a junction table dropped duality
   out of the walk entirely — silently.
5. **A design that could not be written to was excluded from the decision, silently.** A
   write with no SQL for a given design raised an `AttributeError` deep in the runner, the
   cell went missing, and the design vanished from the ranking. The runner now prints
   `!! MEASUREMENT ERRORS` and names them.
6. **The mix itself was wrong.** Writes ran at 15% of operations — a 6:1 read:write ratio,
   in a system where a booking is written once and read for the rest of its life. Write
   amplification is the *one* axis on which the consolidated designs lose, so overstating
   writes tenfold held all four in a dead heat and hid the result. At the real ratio (61:1)
   duality separates by 10.4%.

7. **The document could not use its own indexes.** The filter rendered as
   `JSON_EXISTS(data, '$.passenger_id?(@ == 7)')` while the index was built on
   `JSON_VALUE(data, '$.passenger_id')` typed **VARCHAR2** — and `passenger_id` is a NUMBER,
   because it references `passengers.passenger_id`, a fact that lives in the *relationships*
   and not in the name. Oracle uses a functional index on a JSON collection only when the
   query's expression matches the index's **exactly** — function, path *and* returning type.
   Two halves, both wrong: the collection full-scanned every filtered read while a perfectly
   good index sat beside it, unused.

   | | full-scan (shipped) | indexed (fixed) |
   |---|---:|---:|
   | passenger_reservations | 1,403 µs | **322 µs** |
   | open_for_agent | 1,416 µs | **287 µs** |
   | passenger_history | 1,413 µs | **314 µs** |

   This one inverted the entire result. The document went from **6.07M (last)** to **4.05M
   (first)**, and relational fell to last. Every previous run of this capstone had concluded
   "the document loses the filtered reads" — and it was measuring a missing index.

   *Caught by Rick, on intuition, against the numbers: "how is duality winning on heavy read?
   that is counterintuitive... document should be winning that scenario." It should have been,
   and it was.* The query generator and the index generator now derive the expression from a
   single shared helper, so they cannot drift apart again.

8. **The duality view never did the joins.** It nested the junction tables and stopped —
   `itinerarylegs: [{reservation_id, leg_id}]`, no flight number, no payment amount. So it
   was not answering `get_itinerary` at all: it returned a strictly smaller result, skipped
   the joins the query required, and "beat" relational on a query that needs exactly those
   joins. *Duality is not free joins.* The far side of the M:N is now nested in, and duality
   lands where it should — 382 against relational's 399.

   (Getting there found an Oracle bug worth knowing: an `@unnest` block whose far-side PK is
   omitted raises **ORA-00600 [qjsnbzoUpdateRow:zero_pk_cols] and kills the session** on any
   update through the view; putting the PK inside the `@unnest` collides with the junction's
   own copy of it, ORA-40473. A *named* nested object does both correctly. Also ORA-40609: a
   nested parent's FK column may not also be a root scalar — which silently moves
   `passenger_id` from `$.passenger_id` to `$.passenger.passenger_id`, so any query still
   filtering the flat path matches nothing and times beautifully.)

9. **The relational query walked into a fan trap.** `get_itinerary` cross-joined two
   independent child collections — 3 legs × 2 payments = **6 rows**, the reservation repeated
   six times, every payment repeated once per leg. Not the aggregate the query asked for, and
   *more* expensive than the right answer: **528µs cartesian → 377µs** once each branch is
   gathered in its own correlated subquery. Relational had been charged for a query no
   competent developer would write, which flattered every design that assembles the aggregate
   for you.

10. **A pattern that matched zero rows.** `open_for_agent` filtered
    `reservation_status_code = 'OPEN'`; the seeded statuses are PENDING / CONFIRMED /
    CANCELLED. It had been benchmarking an index probe that finds nothing, at 300/hr, in all
    four designs.

11. **The document could not answer `passenger_history`.** It returns the passenger's name,
    and the document embedded no passenger. A real document design denormalizes it — the
    *extended reference* pattern — so the seed now carries `last_name` on the reservation.

### ANSWER VALIDATION — the phase that stops the next one

Defects 1, 8, 10 and 11 are all the same failure: **a design timed as though it had answered
a query it had not answered.** An unanswered query is always fast, and a stopwatch cannot
tell the difference. Every one of them was found by hand, one at a time, each time after a
number looked wrong to a human.

So `optimize()` now runs **ANSWER VALIDATION as a phase before any timing**: every candidate
design must return the same answer as relational for every pattern, or its cells are not
timed at all.

The shapes legitimately differ — relational returns flat columns, the document returns one
nested JSON document, duality nests it differently again, the single collection returns one
row *per item type* — so the raw rows cannot be hashed against each other. What IS comparable
is the **answer**: for every property the query asked for, the set of values that came back.
That is invariant to nesting, to row-vs-column, to key order, to Oracle handing JSON numbers
back as strings, and to a document spelling the root key `_id`. It still catches every way a
design can silently answer a different question.

Re-introduce the original duality bug and it is now caught in one second, by the harness,
instead of in hours, by a human:

```
CAUGHT  get_itinerary / duality: flight_number: returned nothing (expected 3 value(s))
```

The report prints the verdict above the decision, because **if the designs disagree, the
decision is not a decision**:

```
ANSWER VALIDATION: every design returns the same answer for every pattern.
```

*(`tooling/optimize/equivalence.py` had existed since the beginning, and its docstring said
exactly what it was for — "a shape that looks fast because it returns the wrong rows must not
win." It was never called. A guard that is not wired in is worse than no guard: it reads like
the risk is covered.)*

### Then we turned on the plans, and found five more

The runner captured `consistent gets` for every cell and **never once looked at it**, while
these docs claimed an "index-first methodology". Every plan in this session was pulled by
hand, in a throwaway script, after a number looked wrong to a human. Analysing the plans by
default found, in a single run:

12. **The index-name collision — relational had NO indexes, ever.** `generate_indexes` named
    every index after the *entity's table* regardless of shape, so the document's index on
    `reservation_docs` was called `itinerary_reservations_passenger_id_ix`. The relational
    `CREATE INDEX` of that same name then raised **ORA-00955**, which the runner *tolerates as
    "already exists" and swallows*. Relational full-scanned its filtered reads in every run of
    this capstone. **Idempotent error tolerance made a hard failure invisible** — so the runner
    now verifies afterwards that each index landed *on the table it was meant for*.

13. **`TO_NUMBER`.** The single collection typed `passenger_id` VARCHAR2 by name inference —
    but it is *Passenger's primary key*, a NUMBER. Every numeric filter wrapped in
    `TO_NUMBER(...)`, and **Oracle printed the diagnosis itself**:

    ```
    filter(TO_NUMBER(CASE "TYPE" WHEN 'ItineraryReservation' THEN "PASSENGER_ID" END) = 7)
    SQL Analysis Report: The following columns have predicates which preclude their
                         use as keys in index range scan.
    ```

    The index was built, VALID, and unusable. **Same root cause as defect 7** — typing without
    key/FK context has now broken the indexes of two separate designs.

14. **`ORDER BY` and `LIMIT` were silently dropped** for both JSON shapes: the relational query
    sorted, duality and the document did not, so they "won" a row by doing less work. (A
    duality view sorts perfectly well — you order on a `JSON_VALUE` expression.) The
    equivalence gate compares *sets* of values and cannot see an ordering difference; nothing
    caught it.

15. **A sparse index cannot serve a multi-type read.** Every per-type index on the single
    collection is `CASE WHEN type='X' THEN col END`; a read spanning several types filters the
    *plain* column and matches none of them. And the GSI derivation skipped predicates that
    were not on the root — so `passenger_history`, which filters `Passenger.passenger_id`,
    derived **no index at all**.

16. **The dataset was too small to mean anything, and then it was contaminated.** 3,000
    reservations is a **28-block table**: Oracle correctly refuses an index to fetch 50 rows
    from 28 blocks, so no access path could win and the matrix compared round-trip overhead.
    Raised to 30,000. And `DELETE` does not lower the high-water mark, so a re-fill left the
    previous, larger seed's segments behind — 11,390 logical reads for 30k rows. Hence
    `--fresh`, which also exposed a seed bug masked for the entire project by a `NOT EXISTS`
    guard: `LPAD(100, 2, '0')` **truncates** to `'10'` and collides with airport 10.

17. **The aggregation had no index — and that was the whole "document" finding.** Index
    derivation looked at `WHERE` clauses only, so a `GROUP BY` key never got an index and every
    aggregation scanned the entire object. On a JSON collection that means dragging every
    embedded leg and payment past the CPU to read one status field. It made the document
    **2.4× worse and dead last**, and the conclusion — *"a JSON collection has no
    aggregate-friendly access path"* — was asserted in the source. With the index:
    15,479µs/3,359 reads → **1,789µs/102 reads**, and the document went from **last to first**.
    (See *The document result*, above.) This is the **fourth** defect of one shape in this
    harness — an index whose expression does not match the query's — so query and index are now
    generated from one function.

None of the seventeen was a wrong *number*. Every one of them was a wrong *question* — and each
produced a confident, plausible, wrong architecture. Six were biased against the document,
three against relational, two against duality, two against the single collection: that is
exactly how a benchmark quietly becomes an argument.

**Three rules, each bought with a wrong conclusion:**
- When a design cannot win any row of a matrix, **suspect the fixture before you believe the
  finding.**
- **Never trust a timing without its access path.** Oracle will tell you why an index was not
  used — in the plan, in English.
- **A design's weakness must be demonstrated on its best access path, not its default one.**
  Before writing "X cannot do Y", ask what index would make it, and build it.

Plus, from the earlier adversarial review: read cost (logical reads) and write cost (redo
bytes) are **different units** and cannot be summed — the matrix is built in one consistent
unit (median elapsed µs), with the V$MYSTAT counters kept alongside as diagnostics.

## Index-first methodology

Indexes are derived from the access patterns and deployed **before** anything is measured.
Benchmarking un-indexed tables measures full scans that production would never run. When
this was missed, the document full-scanned its own signature point-read (735µs → 289µs once
indexed) and every comparison was biased toward relational.

## Cross-runtime data layer

The generated data layer for the reservation read patterns (including the join to
Passenger) runs against the live schema, and was validated identical across all five
runtimes (see the harness + `compare.py`).

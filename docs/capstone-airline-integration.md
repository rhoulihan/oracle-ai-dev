# Capstone integration test — airline reservations

An end-to-end, adversarial exercise of the whole plugin against **live Oracle AI Database
26ai Free**, using the real airline-reservations logical model (Barry Williams,
DataBaseAnswers.org). It doubles as the plugin's full integration test.

> **The results — the full cost matrix, the access paths, and the seventeen defects — live in
> [`tests/integration/airline/RESULTS.md`](../tests/integration/airline/RESULTS.md).**
> That file is the single source of truth and is regenerated from a live run. This page is the
> map: what the capstone does and why.
>
> *(This page used to carry its own copy of the numbers. They drifted, and a stale copy of a
> benchmark is worse than no copy — so there is now one home for them.)*

Reproduce the whole thing in about 65 seconds:

```bash
export DB_USER=plugin_dev DB_PASSWORD=... DB_DSN=localhost:1521/FREEPDB1
python -m tooling.optimize tests/integration/airline/workload.json --fresh --out ./out
```

## What it does

1. Extracts the real **11-entity model** — composite-PK junctions, typed code/date PKs, code
   FKs — into a [ModelSpec](../tests/integration/airline/model.json).
2. Deploys **all four candidate designs** of the walk on one live database, seeding them all
   from the same relational overlay: **30,000 reservations / 20,000 passengers** by default
   (the checked-in, CI-friendly seed — the published matrix is the 2026-07-14
   **production-volume run at 300,000 reservations / 1.2M itinerary-leg rows**), each booking
   carrying **2–6 legs** (a return trip with connections) and 1–2 payments.
3. Defines a realistic **workload** (transactional / operational-KPI / reporting) as *logical*
   queries — `entity.property` result sets plus filter conditions — each with its own rate.
   A booking is written once and read for the rest of its life: **61 reads per write**.
4. **Derives the indexes the access patterns imply** — from their filters *and their
   aggregations* — and deploys them **before** anything is measured.
5. **Validates that every design returns the same answer**, before a single timing.
6. Measures every pattern against every design, **captures the execution plan for every cell**,
   assembles the cost matrix (reads *and* writes as first-class rows), and decides — refusing
   to name a winner inside the noise floor.
7. Re-weights the same measurements into named **workload scenarios** (mobile check-in,
   analytics, write-heavy booking engine) to show where the winner moves — for free, because a
   cell is a property of the schema, not of how often the pattern runs.
8. Generates the data layer for the chosen shape and validates it returns **identical results
   across all five runtimes**.

## The headline

**Once every design is fairly indexed, the reads converge — and the only thing that separates
them is write pressure.** The document shape ties or wins every read workload (including
analytics); relational wins the write-heavy booking engine. Embedding still amplifies writes,
and after seventeen bug fixes that is the *only* inherent cost left in the matrix — which is
precisely what the consolidation walk claims.

## Read the defects, not just the numbers

Seventeen defects were found **in the measurement harness itself**, and every one had produced
a confident, plausible, **wrong** architecture:

- a "document" that **embedded nothing** — all of a document's write amplification, none of
  its read consolidation, so it could not win a single cell;
- a duality view that **never performed its joins** — it nested the junction keys and stopped,
  answering a strictly smaller question, and so "beat" relational on a query that needs exactly
  those joins;
- a relational query that walked into a **fan trap**, cross-joining two independent child
  collections (3 legs × 2 payments = 6 rows) — the wrong answer, and *more* expensive than the
  right one;
- an index whose **name collided** with another design's, so the second `CREATE INDEX` raised
  ORA-00955 — which the runner *tolerates as "already exists" and swallows* — leaving
  **relational with no access-pattern indexes at all**, in every run;
- a foreign key typed as a **string**, so every numeric filter wrapped in `TO_NUMBER` and the
  index became unusable. Oracle said so, in the plan, in English: *"predicates which preclude
  their use as keys in index range scan."*
- a **`GROUP BY` with no index**, which nearly shipped as the finding *"a JSON collection has
  no aggregate-friendly access path."* It made the document look 30× slower at aggregation and
  lose the entire benchmark. It was a missing index — and with one, the document reads **fewer
  logical reads than the relational table**.

**Six of the seventeen were biased against the same design.** That is exactly how a benchmark
quietly becomes an argument. Which is why the tool now:

- **validates equivalence before speed** — a design that returns less is faster, and a
  stopwatch cannot tell the difference;
- **prints the access path for every cell** — a number without its access path is not evidence,
  and a filtered read that full-scans is a *warning*, not a datapoint;
- **generates each query and its index from one function** — an index whose expression differs
  from the query's by a single character is built, `VALID`, and silently ignored. **Four**
  separate defects had that exact shape.

> **A design's weakness must be demonstrated on its best access path, not its default one.**
> Before writing "X cannot do Y", ask what index would make it — and build it.

## Cross-runtime data layer

The generated data layer for the reservation access patterns (including the join to Passenger)
runs against the live schema and was validated **identical across all five runtimes** —
Python, Node, Java, Go, .NET — hashed and compared.

Raw run artifacts live under
[`tests/integration/airline/`](../tests/integration/airline/): `walk-4design.txt` is the
current matrix, access paths and scenarios. **The other `*.txt` files in that directory are
historical** and hold conclusions since disproved — kept only as a record of how the harness
was wrong.

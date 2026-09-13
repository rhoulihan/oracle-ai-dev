# Unified Model Theory — methodology

Data modeling is a physics problem, not a philosophy problem. Relational and
document are two poles of one spectrum — orthogonal projections of one truth.

## Vocabulary

- **Canonical Form** — the one logical truth of the domain (the ERD). A *logical*
  overlay, not a physical-normalization mandate; physical storage is a separate
  per-entity decision. Sharper still: relational is not the decomposed pole of the
  spectrum — it is the **logical lingua franca spanning the whole line**. Any shape
  can be *described* relationally, and describing data relationally never required
  *storing* it decomposed. The pole you store at is a workload decision; the
  language you reason in stays the same (from the authors' converged-database book
  project).
- **Projected Shape** — how an entity is physically stored for a consumer
  (relational columns, a JSON collection, a hybrid).
- **Shape Projection** — the mapping that renders the Canonical Form into a
  Projected Shape (a duality view, a JSON view, a materialized view, a collection).
- **Access Surface** — the set of access patterns a shape must serve.

## Workflow

1. Build the canonical ERD (the ERD still matters).
2. Enumerate **all** access patterns, each with: what it returns (`entity.property`
   references), frequency, cardinality, predicates, ordering, latency budget, and
   write composition.
3. Rank by frequency (the 70/20/10 rule): the most common patterns earn the
   optimized shape.
4. Read the three dials per entity: pattern complexity; read/write mix; write-size
   vs read-size.
5. Pick one of exactly three physical strategies:
   - **JSON collection** — a single-entity, co-accessed document.
   - **single collection with a (multivalue) index** — the write-hot path; avoids a
     duality view's read-time join on every write.
   - **relational + duality** — normalized tables stitched by a duality view for
     multi-entity, read-mostly consumers.
6. Design one projection per consumer (JSON view / duality view / collection /
   straight SQL / property graph / vector column / materialized view).
7. Run diagnostics: the three signs of trouble and the five architecture questions.

**The four milestone gates.** That workflow has four places where the agent
stops and the user decides — each one is a **pause for review**, not a note
recorded in passing:

1. **Requirements** (steps 1–3: the ERD, the enumerated access patterns, the
   frequency ranking) — present `data_requirements.md` and wait.
2. **Candidate models** (steps 4–6: the diverse candidate set with its
   projections, and the indexes each candidate implies) — present the
   alternatives and the tradeoff you see, and wait.
3. **The measured election** — present the cost matrix, the margin against the
   noise floor, and the `decided by:` disclosure, and wait. A verdict inside
   the noise floor is presented as TOO CLOSE TO CALL, not resolved for the
   user.
4. **The generated artifacts** — present the DDL, the derived indexes, and any
   data-layer output before anything is deployed.

Nothing in a later milestone begins before the earlier one is approved.
Detailed instructions are input to a plan, not a substitute for one
([operating principles](operating-principles.md) §14).

## Data first, schema later — and sometimes never

When the access patterns are unknown or unstable, don't force an up-front normalized
schema. Store the object the moment you have it, then discover structure as the
questions sharpen — "flexibility you cannot query is just a tidy landfill" (from the
authors' converged-database book project). The promotion ladder:

1. **Ingest** into a JSON collection; a broad JSON search index covers exploration.
2. **Discover** with a DataGuide — the computed soft schema of the paths and types
   that actually appear.
3. **Promote** each path the workload proves hot: virtual column → functional
   index → materialized view.
4. **Project** stable contracts as views (or duality views) once the shape settles.

A mature design carries **two index families**: dedicated indexes/MVs for the known
patterns, and the schema-agnostic search index for the questions you haven't asked
yet. Schema-flexible for write, schema-rich for query.

## Reversibility

On a converged engine the shape choice is a **refactor, not a one-way door**: every
shape is a projection of the same canonical form, so pick for today's hot patterns
and re-project when they move. That is what lowers the stakes of the initial call —
and why the optimizer measures candidates instead of litigating philosophy.

## Honesty calibrations

- Duality views are read-time joins — wrong for write-heavy hot paths. "Joins are
  never free — duality trades a costlier read for zero write amplification."
- Nesting on Oracle is a free modeling variable: OSON field access is O(1) in
  document size **by design — a property of the format, not a measured workload
  claim**. Never present a storage-primitive ratio as an expected query speedup.
- A single collection is not a duality view.
- Maintain a precomputed subset only if read-freq × read-cost > write-freq ×
  maintenance-cost.

Framings worth keeping: "Model the domain. Project the access." /
"One truth. Many shapes. Zero tradeoffs." /
"Express the SHAPE. Let the CBO pick the PLAN."

## Sources
- Oracle JSON Developer's Guide (26ai), DataGuide — https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/
- Lingua-franca and data-first framings — from the authors' converged-database book
  project; field-verified, 2025–2026.

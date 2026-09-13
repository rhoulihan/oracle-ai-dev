---
name: oracle-data-modeling
description: Use when designing, reviewing, or migrating a data model or schema, or when a developer wants feedback on a data model or requirements they already have — before choosing tables, collections, or indexes. Applies Unified Model Theory to pick the right shape per access pattern on Oracle's converged engine.
---

# Converged data modeling (Unified Model Theory)

Model the domain once; project it into the shape each access pattern needs.
Oracle's one engine offers relational, JSON collection, duality, graph, and
vector shapes — **choosing the shape is the highest-leverage decision.**

Read [the methodology](references/umt-methodology.md) for the workflow,
[decision rules](references/decision-rules.md),
[the restaurant example](references/restaurant-example.md),
[storage mechanics](references/storage-mechanics.md) for the physics under
the shapes, [duality design gates](references/duality-design-gates.md)
before any duality DDL, [field lessons](references/field-lessons.md),
[claims guardrails](references/claims-guardrails.md) for the never-claim list,
and [operating principles](references/operating-principles.md) for the defaults.
Read the project's own [local knowledge](references/local-knowledge.md) —
`.oracle-ai-dev/standards.md` — first: active directives outrank those defaults.

## Two ways in

**Greenfield** — conduct the modeling intake ([the questions](../../tooling/intake/questions-modeling.md)):
build the canonical ERD, then enumerate every access pattern
(what it returns as `entity.property` refs, frequency, cardinality, predicates,
latency budget, write intensity). Rank by frequency (70/20/10). The shape recommender
(`tooling/recommend/`) proposes a strategy per pattern, citing the UMT rule.

**Four milestones, four pauses.** Requirements (`data_requirements.md`) →
candidate models → measured election → generated artifacts: present each and
**wait for the user's approval before starting the next**. Gate the final
`data_model.md` on the [review checklist](references/review-checklist.md).

**Brownfield / review** — with an existing model, run the intake as a gap
analysis: extract what is answered, ask only what is missing, then return a
severity-ranked critique — unmet patterns, mis-chosen shapes,
write-amplification traps, misbehaving indexes, features that will not work on
Free — and the corrected model.

## Reason about candidates, then measure them
Candidates come from **your reasoning**, not a rule table: propose a *diverse
set* — embed the aggregate, decompose it, reference vs embed per relationship.
The [decision heuristics](references/decision-rules.md) and
[pattern catalog](references/patterns.md) are intuition-pumps, not a decision tree.

**Index first.** Derive the indexes the patterns imply from their filters *before*
measuring, or you benchmark scans production would never run.

**Writes are access patterns too.** Build a **cost matrix** — every pattern a row (reads
*and* writes), every design a column, each cell measured. The
[document-modeling algorithm](references/optimization.md) walks **document → single
collection → hybrid → duality → relational** as write amplification bites. All five
compete by default, and the single collection's keys are **derived** from the result
sets and the filters, not hand-drawn.

Then **benchmark** — the six steps are codified:

```bash
python -m tooling.optimize <workload.json> [--out DIR] [--trials 25]
```

It deploys the indexes and every design, seeds, then — before timing — **validates that
every design returns the same answer**: a design that returns less is faster, and a
stopwatch cannot tell. **Equivalence before speed.** Then it measures every pattern
against every design and emits the winning DDL, printing
`!! ANSWER VALIDATION FAILED` on disagreement, `!! MEASUREMENT ERRORS` over
silently dropping a design, `TOO CLOSE TO CALL` inside the noise floor, and
`decided by:` — point reads (carries to Exadata) or scan economics
(environment-conditional).

## Output
A `data_model.md` with runnable DDL for the chosen strategy per entity, handing
off to the JSON, duality, Mongo API, or vector paths by name.

## Sources
- Oracle JSON Developer's Guide (26ai) — https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/

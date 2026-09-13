# Operating principles — the defaults this plugin brings

How this skill works when nobody has told it otherwise. Every principle below
was paid for by at least one measured incident in this project's history: a
number that turned out to be a measurement error, a generated index that never
matched its predicate, a "done" that had not been run. They ship as **defaults,
not mandates** — a project's own standards outrank them, with the three
exceptions in §D.

> Advisory: this file is doctrine. Where a principle names an enforcing
> mechanism the citation is real and the gate runs; everything else is judgment
> the agent applies, and no code checks it for you.

The agent reconciles this corpus with the project's own operating files once,
on first use, through the gap-fill procedure in
[local knowledge](local-knowledge.md) — silent where the project already covers
a principle, surfacing only the real gaps.

## A. Measurement doctrine — the optimizer's contract, stated as behavior

**1. Equivalence before speed.** Never time a query that has not first been
shown to answer the question. The same answer across every design, compared
shape-independently, or the cell is a measurement error rather than a fast cell
— a design that returns less is faster, and a stopwatch cannot tell. The
principle governs any ad-hoc comparison made outside the harness too.
**Enforced by** `tooling/optimize/equivalence.py` (canonical result hashing) and
`tooling/optimize/runner.py`, which prints `!! ANSWER VALIDATION FAILED` and
refuses to time the disagreeing designs.

**2. A number without its access path explains nothing.** Read the plan, not
just the clock. `TABLE ACCESS FULL` under a filtered read is a defect until
proven otherwise, and Oracle's own SQL Analysis Report says why an index was
ignored — read it before theorizing.
**Enforced by** `tooling/plancheck/check.py` and the per-cell plan capture in
`tooling/optimize/runner.py`; a filtered read that full-scans is reported as a
warning, not as a datapoint.

**3. Report the margin, not just the winner.** Inside the noise floor the
verdict is TOO CLOSE TO CALL, and it is said out loud. A small lead is a coin
flip; deciding architecture on one is malpractice, and the honest verdict is
sometimes no winner at all.
**Enforced by** the noise-floor computation in `tooling/optimize/runner.py`,
which raises the effective floor to the worst run-to-run variation among the
deciding cells before any winner is declared.

**4. Benchmark at production cardinality or call the verdict provisional.** A
small-seed winner has been elected on its incidental costs, not on the shape of
the workload. State the rows the deciding pattern actually touched; if that
pattern degenerated to a handful of rows, say the run cannot decide.
**Enforced by** the `expect_rows` declaration and the `!! PROVISIONAL` verdict
flag in `tooling/optimize/runner.py`.

**5. The fixture is part of the claim.** Before trusting a comparison, ask what
would have to be true for the losing design to win — then check that the
fixture gives it that chance. Assert non-empty results of the expected
magnitude: an unanswered or empty query is always fast.
**Enforced by** the seeded fixtures under `assets/bench/` together with
`expect_rows` in `tooling/optimize/runner.py`; the judgment about what the
loser needed is yours.

**6. "It cannot do X" is a hypothesis.** A design's weakness must be
demonstrated on its best access path, not on the first one that came to mind.
Ask which index or projection would make the disfavored design work, build
that, then measure it. A shape dismissed without its index has been assumed,
not tested.

**7. Disclose every exclusion and assumption.** A design dropped from a
comparison, a pattern nobody could serve, a capped sample — name it, and say
which way the bias runs. No silent caps, no quietly missing columns.
**Enforced by** `tooling/optimize/runner.py`, which prints `!! MEASUREMENT
ERRORS` rather than silently dropping a design from the matrix.

## B. Generation doctrine — for any code, DDL, or SQL the agent produces

**8. One expression, one function.** Anything emitted in two places that must
agree — a query predicate and the index that serves it, a document field and
the seed that fills it — derives from a single shared source. Independent
derivations of "the same" string drift silently, and the drift shows up as a
full scan nobody ordered.
**Enforced by** the shared emitters in `tooling/generate/ddl.py`, which build
predicate and index from one derivation.

**9. Type from structure, not names.** Keys and foreign keys carry their types
through relationships and declarations; inferring a type from a column's name
is the last resort and has broken indexes repeatedly. Insist on a declared type
for anything used as a group-by key or an aggregate argument.
**Enforced by** the model validation in `tooling/generate/model.py`.

**10. A projection costs exactly what it nests — scope it all the way down.**
Entities *and* attributes, at every level: one projection per aggregate, and
read or write through the leanest one that serves the pattern. A projection
scoped at the root while its children stay wide has not been scoped.
**Enforced by** the duality scoping rules in `tooling/duality/` and
`tests/test_duality_scoping.py`.

**11. Prefer the documented idiom that states the intent.** A passing proof
built on internal columns, undocumented byte layouts, or reverse-derived
expressions is not shippable — it works until the release that reorganizes what
it depended on. "Clever" is a warning, not a win.

**12. Tolerated errors require verification.** If a step is allowed to say
"already exists", verify afterwards that the object exists *on the object it
was meant for*. Idempotence without verification hides hard failures behind a
green log line.
**Enforced by** the `ASSERT:<name>:PASS` protocol the configurators and verify
scripts emit — `assets/verify/verify-setup.sh`, `assets/verify/verify-ords.sh`.

**13. Present-on-PATH is not works.** Any adopted external tool must run and
identify itself before being trusted. A binary that resolves is not a binary
that executes, and the difference surfaces on someone else's machine.
**Enforced by** the resolve-and-run checks in `assets/verify/lib.sh`.

## C. Process doctrine — how the agent works

**14. Propose, review, then build.** The data-model milestones — requirements →
candidate models → measured election → generated artifacts — each pause for the
user's review before the next begins. Detailed instructions are input to a
plan, not a substitute for one.
**Enforced by** the milestone gates written into the modeling workflow
([SKILL.md](../SKILL.md), [the methodology](umt-methodology.md)); the pause is a
skill step, and skipping it is visible in the transcript.

**15. Tests first; for guards, the planted defect is the red.** Changes to
generated-code behavior land with a failing test first. A tripwire written over
an already-clean surface proves nothing about itself — it earns trust by
catching a defect deliberately planted for it, then going green when the defect
is removed.

**16. Rehearse the seams from cold.** Unit-green parts still fail in sequence.
Verify restarts, second runs, and clean-machine paths: a fresh clone with a
stripped environment is the only setup test that cannot lie, because it is the
only one that has nothing left over to lean on.
**Enforced by** `assets/verify/verify-setup.sh` and the idempotence re-runs the
configurators are built for.

**17. Degrade honestly.** When a capability is unavailable — no database, no
driver, no license — say "unchecked" or "unavailable". Never present a skipped
path as a verified one. A skip on a completeness tier is not a pass, and a
suite that reports success while silently skipping its live tier is worse than
a red one.

**18. Stay on the primary deliverable.** Mid-task asides get backlogged unless
they are directly relevant to the work in hand, and the primary task is
confirmed done before anything is declared complete. Drift is the most
expensive failure mode that never shows up as an error.

**19. Counterintuitive results are bug reports against the harness.** When a
domain expert pushes back on a number, treat the pushback as a defect lead —
not as a position to defend with the very number that produced it. The
measurement is the hypothesis under test, and the expert's surprise is
evidence.

**20. Tests and the code they test are one commit.** Stage the whole tree: a
commit that carries the fix without its test, or the test without its fixture,
is not reviewable and does not bisect.

**21. Capture learnings at the moment of confirmation.** When Oracle work
surfaces something new — an error the docs do not explain, a non-obvious fix,
documentation that is wrong or missing, behavior that differs across versions
or deployment tiers, a belief disproven by a live test — append it to the
project's lessons ledger (`.oracle-ai-dev/lessons.md`) before moving on, not
at session end when the detail is gone. An entry carries the exact versions,
the error **verbatim** (ORA- codes exactly), the minimal working fix, what did
NOT work, how it was confirmed — an inferred-but-untested entry is marked
**UNVERIFIED** — and whether the behavior is documented, undocumented, or the
docs conflict (cite both). The user reviews entries for accuracy; vetted
entries may then be offered **upstream** for inclusion in this plugin (the
ledger's `offered`/`submitted` statuses). Skill files are never edited
directly — submissions go through the plugin's verification and test pipeline.
**Enforced by** the entry-format lints in `tests/test_local_knowledge_store.py`
and the draft-show-approve gate in [local knowledge](local-knowledge.md); the
capture reflex itself is doctrine.

## D. Safety and confidentiality — non-overridable defaults

These three are the carve-out to the precedence rule. Everywhere else user
standards outrank shipped defaults; here they do not.

**22. Destructive operations require an explicit, named override** on any
target that is not the local disposable container — refuse by default.
**Enforced by** `tooling/optimize/safety.py`, the single source of truth for
that decision: `container` mode is local, `easy` and `wallet` are external, and
external writes need the named override.

**23. Nothing identifying ever ships**: no people, customers, engagements, or
codenames; distinctive constants are fingerprints — round them; a ban must not
teach what it bans; secret registers live outside any shared artifact.
**Enforced by** `tests/lint/banned_strings.py` (the maintainer-local
confidential register and the do-not-cite figure scan) and
`tests/test_banned_strings.py`.

**24. Claims guardrails are normative**: never claim unreleased syntax or
unsupported capabilities; version-note anything release-sensitive.
**Enforced by** [claims-guardrails](claims-guardrails.md) and
`tests/test_duality_ddl_blocklist.py`.

**The precedence rule, with the carve-out.** User standards > shipped defaults,
EXCEPT the non-overridable three:

1. **the destructive-operation override requirement** (destructive ops on any
   target that is not the local disposable container need an explicit, named
   override — refuse by default);
2. **nothing-identifying-ships** (no people, customers, engagements, or
   codenames; distinctive constants are fingerprints — round them; a ban must
   not teach what it bans; secret registers live outside any shared artifact);
3. **the claims guardrails** (never claim unreleased syntax or unsupported
   capabilities; version-note anything release-sensitive).

A standard that would override one of the three is refused with the reason;
conflicts between two user standards are surfaced at approval time, never
resolved silently.

## E. How these ship

- **Defaults, not mandates.** User standards win, except §D.
- **Gap-fill, once per project.** Compare this corpus against the project's own
  operating files at the router's first use; stay silent where covered; surface
  the real gaps once, each with its concrete behavioral consequence; the user
  picks project-level adoption, global adoption, or decline. The procedure and
  the recorded-decision contract live in [local knowledge](local-knowledge.md).
- **Adopted principles are standards.** An adoption writes a `category: process`
  entry to the project's `standards.md`; a decline writes the same entry marked
  declined, so the question is never re-asked. One ledger, one gate, one
  precedence rule.

## F. Companion skills — soft dependencies, never hard ones

The agent can read its own available-skills list, so the rule is **detect, then
"if present, invoke"**. A missing companion never blocks anything: each row's
fallback below is what the agent does instead, and it is sufficient on its own.

| Companion | Why it helps here | If absent |
|---|---|---|
| `superpowers: test-driven-development` | §15 — generated-code changes and harness fixes | the red→green discipline stated inline, below |
| `superpowers: verification-before-completion` | §16/§17 — evidence before any "done" claim | the verify scripts and plancheck remain the floor |
| `superpowers: systematic-debugging` | §19 — harness-first debugging of surprising numbers | §19 stands alone as the rule |
| `superpowers: brainstorming` | §14 — before proposing candidate models | the modeling intake questions are the structured substitute |

**Fallback — test-driven development.** With no TDD skill loaded, the agent
runs the discipline itself: for any change to generated-code behavior, write
the failing test first, run it, and show the red output before writing the
implementation; then make it pass and show the green. For a guard or tripwire,
the red comes from a *planted* defect — introduce the thing the guard is
supposed to catch, watch the guard catch it, remove the defect, watch the guard
go quiet. A guard that has only ever been green has not been tested.

**Fallback — verification before completion.** With no verification skill
loaded, nothing is called done, fixed, or passing until the agent has run the
command that proves it and shown the output. The floor is already in the
plugin: the verify scripts (`assets/verify/`) with their `ASSERT:<name>:PASS`
lines, `python -m tooling.plancheck` for anything query-shaped, and the offline
suite. A claim that rests on a skipped or unavailable check is reported as
unchecked (§17), never as verified.

**Fallback — systematic debugging.** With no debugging skill loaded, the agent
treats a surprising number as a defect lead against the harness first: restate
what was measured, list the ways the harness could produce that number without
the world being that way (empty fixture, wrong access path, unequal answers,
timing outside the measured region), and eliminate them in that order before
defending the result. The user's pushback is evidence, not an objection to be
argued down (§19).

**Fallback — brainstorming.** With no brainstorming skill loaded, the modeling
intake ([the questions](../../../tooling/intake/questions-modeling.md)) is the
structured substitute: work the requirements and access patterns first, then
propose a *diverse* candidate set — embed the aggregate, decompose it into
meaningful containers, reference versus embed per relationship — and present
the alternatives for review before building any of them (§14).

Built-ins already cover the rest, with no external plugin needed:
`python -m tooling.plancheck` (§2), the verify scripts (§16), the optimizer's
equivalence and noise gates (§1, §3), and the safety guard (§22).

## Sources

- This project's measured history: the optimizer's design incidents, the lesson
  ledger, and the doctrines proven across the capstone and exercise runs. Each
  principle traces to at least one measured event; all identifying detail was
  removed at capture time and stays removed (§23).
- [Claims guardrails](claims-guardrails.md) — the normative never-claim list
  behind §23.
- [Field lessons](field-lessons.md) — the measured war stories the measurement
  doctrine generalizes.

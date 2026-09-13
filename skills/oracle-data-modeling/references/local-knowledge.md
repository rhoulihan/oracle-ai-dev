# Local knowledge — the project's own lessons and standards

One project-local store the skill reads before any modeling work: what this
project has *measured* (lessons) and what this project has *decided* (standards).
Lessons inform; standards govern; the
[shipped operating principles](operating-principles.md) fill the gaps the
project's own operating files leave open. All three share one lifecycle —
capture → distill to a structured entry → **user-gated review** → activate.

> Advisory: the workflows below are skill steps the agent performs, not code
> that runs. Nothing here writes a file without showing the user the exact text
> first; the enforcement cited in each section is the code that exists today.

## The store

```
.oracle-ai-dev/
├── lessons.md        # observations — measured facts from this project's work
└── standards.md      # directives — org standards AND adopted operating principles
```

Plain files, in the project, committable on purpose: a team lead approves once
and every teammate's agent inherits the same knowledge. Starter headers ship in
`assets/templates/` — copy them in when the store is first created.

A third tier is specified but **not shipped yet**: a compiled `standards.json`,
generated (never hand-edited) from the active standards, which will let the
generators and the optimizer enforce a subset mechanically. Until it exists,
enforcement is the agent tier only — read `standards.md`, apply the `active`
directives, and say so in the output. Do not create a `standards.json`; nothing
reads it.

**Read order, every modeling session:** `standards.md` first (it governs), then
`lessons.md` (it informs), then the shipped guidance. Where an `active` standard
conflicts with a shipped default, the standard wins — with the carve-out below.

## Lessons pipeline

**Triggers.** Capture a lesson after any `tooling.optimize` or benchmark run
whose outcome *surprised* or *decided* something; on a live-verification
surprise (the database did something the docs did not promise); and whenever the
user asks. Nothing is automatic, nothing is a hook, nothing reads as telemetry —
the agent notices, drafts, and asks.

**Entry format** — mirrors [field lessons](field-lessons.md) so a promotion
upstream is mechanical:

```markdown
## <kebab-case-title>
status: local | offered | submitted | declined     # the file is its own ledger
captured: <date> · context: <26ai RU, shape(s), workload class — auto-filled>
**Lesson.** <the rule>
**What happened.** <evidence with numbers>
**Apply.** <what an agent does differently>
```

**CHECK.** `tests/test_local_knowledge_store.py` lints the format — an entry
missing `**Apply.**` is a war story with no instruction, and a `status:` outside
the legend is an entry in no state at all.

**The gate.** The agent drafts the entry, **shows it verbatim**, and writes it
only on the user's approval. Nothing enters `lessons.md` unreviewed and nothing
is written silently. Rewrite on request; abandon on refusal.

**Status stops at `local`.** The upstream contribution offer and maintainer
triage are a later phase — until they ship, every entry stays `local`, and the
agent does not offer to submit anything anywhere. A `contribution: never` line
in the file header is the project's standing opt-out; honor it without asking.

**Confidentiality.** A lesson is shipped content the moment it is committed:
generalize the engagement, round distinctive constants, and name no person,
customer, or codename (operating principle §23 — non-overridable).
**CHECK.** `tests/lint/banned_strings.py` scans shipped content for the
maintainer-local confidential register and the do-not-cite figures.

## Standards pipeline

**Detection.** Listen for directive phrasing about how this project models
data — "our tables are always plural snake_case", "we never use triggers", "all
money columns are NUMBER(18,2)", "make that a standard", "that's our house
rule". A statement about *this project's practice*, not about Oracle's behavior,
is a candidate standard.

**Entry format:**

```markdown
## <kebab-case-title>
status: proposed | active | retired | declined
category: naming | shape | keys | indexing | integrity | process
**Directive.** <what is required or forbidden>
**Enforcement.** <agent tier: what the agent does; a tooling path once compiled>
**Consequence.** <what changes in generated output because this is active>
```

**CHECK.** `tests/test_local_knowledge_store.py` — the status legend, the
category allowlist (`process` included, since gap-fill outcomes land there), and
the rule that an `active` standard always carries a `**Consequence.**` line.

**The gate.** The agent drafts the entry, shows it verbatim, and states the
**concrete behavioral consequence** — "with this active, the generator emits
`customer_orders` rather than `CustomerOrder`, and the review checklist flags
any singular table name in a model you bring me". A standard whose consequence
cannot be stated concretely is not yet a standard; sharpen it or leave it
`proposed`. The user approves before anything is written; `status: active` is
never set without that approval, and an `active` entry always carries a
consequence line.

**The conflict check.** Before proposing `active`, compare against the shipped
guidance and against every other `active` standard. Conflicts between two user
standards are surfaced at approval time and resolved by the user — never
silently. A conflict with a shipped default is fine and expected: say which
default it displaces, so the user sees what they are turning off.

**Precedence, with the carve-out.** User standards > shipped defaults, EXCEPT
the non-overridable three:

1. **the destructive-operation override requirement** (destructive ops on any
   target that is not the local disposable container need an explicit, named
   override — refuse by default);
2. **nothing-identifying-ships** (no people, customers, engagements, or
   codenames; distinctive constants are fingerprints — round them; a ban must
   not teach what it bans; secret registers live outside any shared artifact);
3. **the claims guardrails** (never claim unreleased syntax or unsupported
   capabilities; version-note anything release-sensitive).

A standard that would override one of the three is **refused with the reason**
— name which of the three it collides with and what the agent will do instead.
**CHECK.** The destructive-operation policy is code, not prose:
`tooling/optimize/safety.py` classifies the target and requires the named
override; the confidentiality scan is `tests/lint/banned_strings.py`.

## Gap-fill — reconciling the shipped principles with the project's own

The [operating principles](operating-principles.md) are defaults. Most projects
already express some of them in their own operating files; the gap-fill exists
to find the ones nobody has covered, ask about those *once*, and then never
raise the subject again.

**When it runs.** On the router's first use in a project, detected by the
**absence of `.oracle-ai-dev/standards.md`**. The store's presence is the
marker — there is no hidden state. A team that creates the store by hand puts a
`gapfill: <date>` line in the header to say the pass has already happened.

**The procedure:**

1. **Read the project's own operating files** — `CLAUDE.md`, `AGENTS.md`, and
   anything they import — plus any existing `.oracle-ai-dev/standards.md`.
2. **Stay silent where covered.** A principle the project's files already
   express, in whatever words, is never mentioned. Coverage is about substance,
   not phrasing: a file that says "always show a failing test first" covers §15
   even though it never says "planted defect".
3. **Surface the real gaps once, grouped, in one pass.** Each uncovered
   principle is presented with its **concrete behavioral consequence** — what
   the agent will do differently in this project if it is adopted — not with its
   rationale. Group by section (measurement / generation / process) so the user
   answers a short list, not twenty-four questions.
4. **The user picks, per principle:**
   - **adopt (project)** — the agent writes the entry to
     `.oracle-ai-dev/standards.md`;
   - **adopt (global)** — the agent *offers the text* for the user's own
     user-level operating file and the user pastes it. **The agent never edits
     files outside the project.** The project-local entry is still recorded, so
     the pass is complete either way;
   - **decline** — recorded, and never asked again.
5. **Record every outcome** through the standards ledger, then proceed with the
   actual work. The gap-fill is a one-time preamble, not a recurring interview,
   and it never runs inside a modeling session that already has a store.

**Adopted principles ARE standards** — the unification. An adoption writes:

```markdown
## <principle-slug>
status: active
category: process
source: shipped operating principle <id>
**Directive.** <the principle's rule>
**Enforcement.** agent tier — applied in every session in this project
**Consequence.** <what changes in this project's output>
```

A decline writes the same entry with `status: declined` (and no consequence
line required) so the flow never re-asks. Both are reversible by editing the
file — it is the user's ledger, not the agent's. No second store, no second
format, one gate, one precedence rule.

**Never re-ask.** Once `.oracle-ai-dev/standards.md` exists, the gap-fill is
done for that project. If the user later wants another pass, they ask for it.

## Sources

- The local-knowledge feature specification (this repo's `docs/specs/`) — the
  store layout, entry formats, gate contract, and the phasing that leaves the
  compiled tier and the contribution flow for later.
- [Operating principles](operating-principles.md) — the corpus the gap-fill
  reconciles, and the §D carve-out quoted above.

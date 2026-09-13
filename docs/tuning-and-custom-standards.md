# Tuning the engines & injecting your own standards

Every knob the deterministic tooling exposes, what the non-knobs are and why
they don't move, and the honest state of custom-rule injection: what you can
do today, how to make a rule *enforced*, and which tier of the standards
pipeline has shipped and which has not.

The rules themselves are documented in
[model-rules-reference.md](model-rules-reference.md).

## Engine knobs

### `python -m tooling.optimize` — the measured election

Needs the driver once per machine: `pip install oracledb` (the generation-only
commands run on the standard library).

| Knob | Default | What it tunes |
|---|---|---|
| `--shapes` | all declared | restrict the candidate designs (`relational,document,...`) |
| `--trials` | 7 | measured executions per (pattern × design) cell |
| `--warmup` | 2 | discarded executions per cell before timing |
| `--no-seed` | off | skip the seed step (data already loaded) |
| `--fresh` | off | drop and rebuild every object first — a re-fill leaves the old high-water mark behind; refused off-localhost without the safety override |
| `--write-scale` | 1.0 | multiply every write row's rate in the election — model a heavier or lighter write mix **without re-measuring** |
| `--walk-scales` | `0.1,1,3,10,30,100` | the write-rate multipliers swept for the consolidation walk, reported as `walk` (where the choice flips as writes scale) |
| `--no-sparse` | off | single-table: plain per-type indexes instead of sparse CASE-filtered ones |
| `--no-partition-by-type` | off | single-table: skip automatic list partitioning by the discriminator |
| `--no-partition` | off | suppress every per-entity `partition` block (the partition dimension) — measure the same designs unpartitioned; deploy and the emitted winner always match |
| `--no-iot` | off | suppress every per-entity `organization` block (the IOT dimension) — measure the same designs heap-organized; deploy and the emitted winner always match |
| `--no-compress` | off | suppress every per-entity `compress` block (the row compression dimension) — measure the same designs uncompressed; deploy and the emitted winner always match |
| `--flex-limit N` | 8192 | hybrid: the flex column's `JSON ... LIMIT n` inline guarantee — flex documents can never fall to LOB storage |
| `--no-flex-limit` | off | hybrid: drop the LIMIT clause (inline storage no longer guaranteed; the OSON inline-to-LOB cliff returns) |
| `--out DIR` | — | write the winning schema's DDL |
| `--json` | off | raw result (matrix, ranked, walk, break-points) as JSON |

The `summary` design has no dedicated knob: its candidacy is projection-gated
(`projections.summary`, auto-nominated per distinct aggregation signature when
the model declares none), and `--shapes` restricts it exactly like any other
candidate.

The workload JSON is the bigger tuning surface than any flag:

- **Per-pattern `rate`** — the primary knob. The election is
  rate-weighted; getting the rates right IS the tuning. "Count is not load":
  rank by frequency × measured cost, not by how many patterns exist.
- **Per-pattern `kind`** — writes are first-class rows, never a discount on
  reads. Include infrastructure writes (sessions, audit, telemetry).
- **`scenarios`** — named rate re-weightings evaluated against the SAME
  measurements (re-weighting is free; no re-measure). Ask "what if reads
  10×?" as a scenario, not a new benchmark run.
- **`seed`** — representative volume; every candidate is populated from one
  source so the comparison measures the shape, not the seed.

Environment: `DB_USER` / `DB_PASSWORD` / `DB_DSN` select the target;
`OPT_ALLOW_EXTERNAL_WRITES=1` is the explicit override that lets destructive
operations (`--fresh`) touch a non-local DSN (`tooling/optimize/safety.py`
refuses otherwise).

### The other CLIs

| Command | Knobs |
|---|---|
| `python -m tooling.datalayer <spec.json> <out_dir>` | `--platforms py,node,java,go,dotnet` (subset; aliases accepted); the spec's `patterns[].shape` decides which schema and write helpers are generated |
| `python -m tooling.duality <model.json>` | `--root R` validates one projection root; exit 1 on blockers |
| `python -m tooling.plancheck "SELECT ..."` | `-` reads stdin; exit 1 when a filtered query full-scans; reads `DB_*` |

### Programmatic-only knobs

These exist as function parameters with defaults and are deliberately not CLI
flags today — callable from Python, documented here so they are not secret:

| Knob | Default | Where | Meaning |
|---|---|---|---|
| `rel_margin` | 0.05 | `tooling/optimize/analyze.py` (`optimal_shape_with_confidence`) | winner-vs-runner-up margin under which the call is flagged too close to call |
| `washout_threshold` | 0.05 | `tooling/optimize/analyze.py` (`recommend_model`) | weighted-cost fraction below which a pattern is reported as washed out |
| per-pattern `read_rate`, `write_rate`, `interval`, `latency_budget_ms` | — | `tooling/optimize/analyze.py` | the recommend-API's richer pattern schema: rates normalized to a common window, plus a latency budget that flags patterns a winning design would silently sacrifice |

### The non-knobs (deliberate)

Two things look like knobs and are not, because they are honesty gates:

- **The noise floor.** `NOISE_FLOOR = 0.05` in `tooling/optimize/runner.py`
  is a *floor*: the effective gate rises to the worst per-cell coefficient of
  variation among the cells the verdict rests on. If the trials disagree with
  themselves more than the designs disagree with each other, no winner is
  declared. Lowering it would manufacture verdicts from noise.
- **The equivalence gate.** Every design must return the same answer before
  anything is timed (`tooling/optimize/equivalence.py`). A design that
  returns less is faster, and a stopwatch cannot tell the difference. There
  is no flag to skip it.

## Injecting custom rules and standards — what exists today

### In the model itself

The ModelSpec is the first place org standards land, because everything
downstream is generated from it:

- **Typing standards** — `column_types` and `pk_type` override every
  inference; declare your org's types once per entity and the relational DDL,
  the typed JSON item methods (`.numberOnly()`/`.string()`), and the index
  expressions all follow
  (`tooling/generate/ddl.py`).
- **Least-privilege projections** — duality `includes`/`columns` scoping is
  an authorization surface: a consumer literally cannot see what its view
  does not project. Encode "the mobile API never sees cost fields" as a
  scoped view, not a code-review comment.
- **Array declarations** — `arrays: [...]` is what routes a property to
  MULTIVALUE indexing and containment predicates; an undeclared array is a
  full scan waiting to happen.

### The project-local knowledge store (agent tier — shipped)

`.oracle-ai-dev/standards.md` (directives — what this project has *decided*)
and `.oracle-ai-dev/lessons.md` (observations — what it has *measured*) are
plain, committable files the modeling skill reads before any modeling work:
standards govern, lessons inform. A team lead approves once and every
teammate's agent inherits the same knowledge. Starter headers ship in
`assets/templates/standards.md` and `assets/templates/lessons.md`; the
capture workflows, entry formats and gate contract are in
[local-knowledge.md](../skills/oracle-data-modeling/references/local-knowledge.md).

- **The gate.** The agent drafts an entry, shows it **verbatim** with its
  concrete behavioral consequence and a conflict check against shipped
  guidance, and writes nothing without approval. An `active` standard always
  carries a `**Consequence.**` line; the format, the status legend and the
  `category: naming | shape | keys | indexing | integrity | process`
  allowlist are linted by `tests/test_local_knowledge_store.py`.
- **The gap-fill, once per project.** On the router's first use — detected by
  the *absence* of `.oracle-ai-dev/standards.md`, so there is no hidden state
  — the agent reads your `CLAUDE.md`/`AGENTS.md`, stays silent on every
  [shipped operating principle](../skills/oracle-data-modeling/references/operating-principles.md)
  your files already cover, and asks once about the rest. Adopt or decline,
  both are recorded as `category: process` standards, and the pass never runs
  again.
- **Precedence, with the carve-out.** An `active` user standard beats a
  shipped default (and the agent names the default it displaces) — except the
  non-overridable three: the destructive-operation override requirement
  (`tooling/optimize/safety.py`), nothing-identifying-ships
  (`tests/lint/banned_strings.py`), and the claims guardrails. A standard
  that collides with one of the three is refused *with the reason*.

Enforcement here is the **agent tier**: the directives are read and applied
every session and the output says so. Mechanical enforcement is the compiled
tier, which has not shipped — see the last section.

### The confidential register

The maintainer-side file-based injection point. Maintainers place an
org-specific register of banned tokens at
`~/.oracle-ai-dev/confidential-register.txt` (override the path with
`ORACLE_AI_DEV_CONFIDENTIAL_REGISTER`); format: one lowercased token per
line, two-word lines matched as adjacent pairs, `#` comments allowed. The
content lint (`tests/lint/banned_strings.py`) then gates releases on it.
Absent the file, the scan is a clean no-op — the repo ships only the
mechanism, never the register.

### The advisory gates are yours to arbitrate

Warnings and advisory rules are design-quality calls you may legitimately
override — that is what the severity means. A `-- WARN [gate-12]` comment on
a writable view is satisfied by *recording the decision*, not by making the
view read-only. The gates file
(`skills/oracle-data-modeling/references/duality-design-gates.md`) marks
exactly which gates are yours to run against the live dictionary and judge.

### Making a rule ENFORCED — the contribution recipe

The standing rule (CONTRIBUTING.md, enforced by
`tests/test_rule_provenance.py`): prose in RULE/CHECK form must cite the code
that enforces it or admit it is advisory. So a custom rule becomes real in
exactly three moves — the same template the shipped gates followed:

1. **Write the failing test first.** A tripwire
   (`tests/test_duality_ddl_blocklist.py` is the pattern: plant the defect,
   prove the detector catches it) or a validator test
   (`tests/test_duality_gates.py` is the pattern: assert the blocker fires on
   a bad model and stays silent on a clean one).
2. **Enforce at the choke point.** Model-level rules go in a validator the
   emit path runs (`tooling/duality/validate.py` shows the
   blocker/warning split); output-level bans go in a build-failing scan.
3. **Cite it from the prose.** Add the rule to the relevant reference with
   the enforcing path next to it — or mark it `> Advisory:` and it stays
   judgment, honestly labeled.

### Steering the agent (prose-level standards)

Project-level conventions you write in your own `CLAUDE.md`/`AGENTS.md` reach
the agent that runs these skills, and the skills' judgment calls (embed vs
reference, view-per-consumer) will follow stated house rules. This is real
but soft — nothing validates it. The store above is the harder version of the
same idea: an entry there is reviewed, carries a stated consequence, and is
read at a fixed point in every modeling session. Turning either into
something a *program* checks is the compiled tier below, still pending.

## The standards pipeline — agent tier SHIPPED, compiled tier NOT YET

The local-knowledge mechanism specified in the internal design document (the
2026-07-15-local-knowledge-spec, maintained outside the shipped tree) landed
in phases, and only the first of them is in your clone.

**Phase A — the agent tier — is shipped.** The committable store, the entry
formats and status legend, the user gate, the one-time router gap-fill
against the shipped operating-principles corpus
(`skills/oracle-data-modeling/references/operating-principles.md`), and the
precedence rule with its non-overridable carve-out. The workflows are documented
in `skills/oracle-data-modeling/references/local-knowledge.md` and linted by
`tests/test_local_knowledge_store.py`; the section
[above](#the-project-local-knowledge-store-agent-tier--shipped) is the
operator's view of it.

**Phase B — the compiled tier — is NOT yet shipped.** Nothing mechanical
exists: no `standards.json` loader, no compiler, no generator or optimizer
that reads a standard. Documented here so you know what is coming and don't
hunt for it today:

- A generated (never hand-edited) `standards.json`, compiled from the
  `active` entries. **Do not create one; nothing reads it.**
- Naming templates honored by DDL generation, and required columns injected
  into generated DDL.
- Shapes banned by an active standard excluded from the optimizer's candidate
  walk **with the exclusion visibly annotated in the cost matrix** (never
  silently dropped).
- An `**Enforcement.**` line that can name a *tooling* path — intake,
  recommender, DDL generation — rather than only the agent tier.

**Phase C — upstream contribution — is not yet shipped either.** There is no
submissions repo and no triage flow, so every lesson stays `status: local`
and the agent offers to submit nothing anywhere.

Until the compiled tier ships, the honest split is: model-level standards are
enforced by the generators today; standards in `.oracle-ai-dev/standards.md`
are reviewed, recorded, and applied by the agent every session — but no
program checks them; content standards ride the register; new *hard* rules
follow the contribution recipe; everything else is prose the agent respects
but nothing validates.

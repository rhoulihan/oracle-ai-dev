# Advisor — from a goal to a plan

When the developer's goal is unclear or spans several paths, or when they bring
requirements or an architecture spec, act as an advisor before routing.

## Flow

1. **Intake.** Conduct the architecture interview
   ([questions](../../../tooling/intake/questions-architecture.md)) — at most
   three questions per turn — and record answers into a `requirements.md`
   scratchpad shaped by the intake schema (`tooling/intake/schema.json`). Hand the
   data-shape questions to the `oracle-data-modeling` skill rather than duplicating them.
   **1.5 Gap-fill (first use in a project only).** When
   `.oracle-ai-dev/standards.md` does not exist, run the one-time
   operating-principles gap-fill described in
   [local knowledge](../../oracle-data-modeling/references/local-knowledge.md):
   read the project's own `CLAUDE.md`/`AGENTS.md`, stay silent on every
   principle they already cover, and present the real gaps once — grouped, each
   with its concrete behavioral consequence — for adopt (project) / adopt
   (global, offered as text the user pastes; never edit files outside the
   project) / decline. Record every outcome as a `category: process` entry in
   `.oracle-ai-dev/standards.md`, then continue the intake. Once the store
   exists the question is never re-asked.
2. **Recommend.** The deterministic recommender (`tooling/recommend/`) turns a
   validated answer set into a plan: guided paths to follow, features + the exact
   configurator scripts to run, the compose profile, per-access-pattern shape, and
   resource sizing against the Free envelope. Because the recommendation logic is
   code (not the model guessing), it is reproducible and testable.
3. **Critique.** Never silently accept a provided spec. Surface, ranked by impact:
   conflicts, unmet access patterns, features that will not work on Free (e.g.
   vector search through the Mongo API), and over-provisioning.

## Output
An ordered task list that names the next skills and configurators, plus the
`requirements.md` and any critique. Then route into the named paths.

## Feedback on an existing spec
If the developer already has requirements or an architecture doc, run the same
intake as a gap analysis: extract what is answered, ask only what is missing, then
return the recommendation plus the ranked critique.

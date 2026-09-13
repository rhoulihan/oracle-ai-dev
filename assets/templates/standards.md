# Standards — directives this project's agents must follow

Org standards plus adopted operating principles. Active directives outrank the
plugin's shipped defaults, except the non-overridable three (destructive-op
override, nothing-identifying-ships, claims guardrails).

- **status:** `proposed` (drafted, not yet in force) | `active` (in force) |
  `retired` (no longer applied) | `declined` (considered and rejected — recorded
  so it is never re-asked).
- **category:** `naming` | `shape` | `keys` | `indexing` | `integrity` |
  `process` (`process` holds adopted or declined operating principles).
- Every `active` entry carries a **Consequence** line: what actually changes in
  generated output. No consequence, no `active`.

<!-- gapfill: 2026-01-15 -->
The `gapfill:` marker records that the one-time operating-principles gap-fill
has run for this project. The presence of this file is itself the marker; add
the line explicitly when the store was created by hand, so the agent does not
open the question again.

<!-- Example entry — copy the shape, delete the comment markers.

## plural-snake-case-table-names
status: active
category: naming
**Directive.** Table names are plural and snake_case.
**Enforcement.** agent tier — applied to every generated model and DDL.
**Consequence.** The generator emits `customer_orders`, not `CustomerOrder`,
and the review checklist flags any singular or camelCase table name.

-->

# Duality-view design gates

A mechanical rulebook for JSON Relational Duality views. Every gate is
**RULE / WHY / CHECK** — the CHECK is what an agent actually runs, against the
data dictionary where the dictionary can answer. Run the structural gates on the
canonical ERD **before** shape selection, not after `CREATE VIEW` fails: a keyless
table or an untraceable FK is a model defect, and discovering it at DDL time wastes
every decision built on top.

These gates gate both directions: generating duality DDL and reviewing
hand-written views. For the read-time-join cost model and the ORA-40477 array-PK
rule, see the duality skill's
[design reference](../../json-duality-dev/references/duality-design.md); for
operations a duality view cannot express at all, its
[limitations](../../json-duality-dev/references/limitations.md).

## Enforcement

The spec-decidable gates are CODE, not prose — review any ModelSpec with
`python -m tooling.duality <model.json> [--root R]` (exit 1 on blockers), and
the DDL emit path runs the same validator so a blocker cannot reach `CREATE`:

- **Gates 1, 2, 3, 9, 11 — blockers** in `tooling/duality/validate.py`;
  `generate_ddl(model, "duality")` refuses to emit (`DualityGateError`).
- **Gates 12, 18 — warnings**: emitted and annotated as `-- WARN [gate-N]`
  comments above the affected view by `tooling/generate/ddl.py`.
- **Gates 5, 7 (`_id` first), 13, 14 — by construction** in
  `tooling/generate/ddl.py`: cardinality decides object vs array, `_id` is
  emitted first, junction arrays keep `@delete`, and a junction's far side
  ships as a named nested object carrying its payload.
- **Gate 16 — generated mechanism**: the datalayer's `replace_<root>_doc`
  refuses a stripped `_metadata` and maps ORA-42699 to a conflict
  (`tooling/datalayer/platforms.py`); the stale-etag behavior is proven live by
  `tests/test_write_conflict_live.py`.
- **Gates 22, 23 — tripwires**: `tests/test_duality_ddl_blocklist.py` fails the
  build if anything we generate or ship indexes a duality view or applies VPD
  to one.

> Advisory: the remaining gates (4, 6, 8, 10, 15, 17, 19–21, 24) need the live
> data dictionary or human judgment — run their CHECK blocks as written against
> the target database; no offline validator can decide them from a ModelSpec.

## Structural gates

### Gate 1 — A root must own a PK or UK

**RULE** — A table can root a duality view only if it declares a primary key or a
unique key (a `RELY` unenforced key qualifies); a keyless table is un-rootable,
full stop.
**WHY** — The root key becomes the document `_id`; with no declared key there is
no stable document identity to project.
**CHECK** —

```sql
SELECT constraint_name, constraint_type, rely
FROM   user_constraints
WHERE  table_name = :root_table
AND    constraint_type IN ('P', 'U');
```

Zero rows means refuse to root the table.

### Gate 2 — Exactly one root; everything else nests via a traceable FK

**RULE** — A duality view has exactly one root table, and every other table nests
under it through an FK relationship traceable to its parent — there is no
two-root view and no document that "starts" at a nested path.
**WHY** — Rootability is a key property; nestability is a relationship property.
A design that introduces a second root or a floating nested entity generates DDL
that cannot exist.
**CHECK** —

```sql
SELECT view_name, root_table_name
FROM   user_json_duality_views;
```

One root per view; then confirm each nested table carries an `R` constraint in
`USER_CONSTRAINTS` pointing (possibly transitively) at its parent in the view.

### Gate 3 — FK target must be the parent's PK or UK

**RULE** — The parent side of every nesting join must be exactly the parent's PK
or a declared UK — never an arbitrary or merely-indexed column.
**WHY** — Joining to a non-unique column fans rows out and breaks the
one-document-per-root guarantee.
**CHECK** —

```sql
SELECT c.constraint_name, c.r_constraint_name, p.constraint_type
FROM   user_constraints c
JOIN   user_constraints p ON p.constraint_name = c.r_constraint_name
WHERE  c.table_name = :child_table
AND    c.constraint_type = 'R';
```

Every nested block's parent-side join columns must equal the referenced
constraint's columns in `USER_CONS_COLUMNS`.

### Gate 4 — Nesting joins are directed column pairs

**RULE** — Model every nesting as parent-side and child-side column lists of
equal length; never assume the join columns share a name across tables.
**WHY** — A shared-name assumption cannot express the normal case
(`orders.id` ⟷ `order_items.order_id`) and silently produces wrong or
self-referential join predicates.
**CHECK** —

```sql
SELECT constraint_name, column_name, position
FROM   user_cons_columns
WHERE  table_name IN (:parent_table, :child_table)
ORDER  BY constraint_name, position;
```

Pair the FK and its referenced key by `POSITION`, and verify the view DDL joins
on exactly those pairs.

### Gate 5 — Cardinality decides object vs array, mechanically

**RULE** — Child-side FK columns unique on the child (they are its PK or a UK)
⇒ 1:1 ⇒ nest as a single object (or UNNEST); otherwise ⇒ 1:N ⇒ nest as an
array. A 1:1 singleton must never be emitted as a one-element array.
**WHY** — Document shape is forced by FK cardinality, not taste; get it wrong and
the generated DDL joins wrong or the document contradicts the schema.
**CHECK** —

```sql
SELECT cc.column_name
FROM   user_cons_columns cc
JOIN   user_constraints c ON c.constraint_name = cc.constraint_name
WHERE  c.table_name = :child_table
AND    c.constraint_type IN ('P', 'U');
```

FK columns covered by a `P`/`U` constraint ⇒ object/UNNEST; not covered ⇒ array.

### Gate 6 — Three embed options: object, UNNEST, opaque JSON column

**RULE** — A 1:1 child nests as a named sub-object or flattens inline with
`UNNEST` (a consumer-shape call); substructure with no independent identity and
no relational access pattern rides an opaque JSON column on the parent — not a
child table, not a nested block.
**WHY** — `UNNEST` merges a 1:1 table's fields into the parent object with no key
prefix; nested blocks are reserved for children that need their own identity,
constraints, or indexes.
**CHECK** — For each embedded substructure ask: own identity? own relational
access pattern? Both no ⇒ JSON column passthrough. Confirm the column exists
natively typed:

```sql
SELECT column_name, data_type
FROM   user_tab_columns
WHERE  table_name = :parent_table
AND    data_type = 'JSON';
```

### Gate 7 — `_id` first; composite `_id` columns all NOT NULL

**RULE** — `_id` is the FIRST projected field and maps to the root key; a
composite `_id` projects every key column, and each must be NOT NULL.
**WHY** — A nullable identifying column cannot participate in a stable document
identity (unique keys, unlike PKs, admit NULLs).
**CHECK** —

```sql
SELECT column_name, nullable
FROM   user_tab_columns
WHERE  table_name = :root_table
AND    column_name IN (SELECT column_name
                       FROM   user_cons_columns
                       WHERE  constraint_name = :root_key_constraint);
```

Every row must show `NULLABLE = 'N'`.

### Gate 8 — Choose the `_id` supplier; IDENTITY roots refuse client `_id`

**RULE** — Decide client-supplied vs DB-generated `_id` as an explicit modeling
decision, then keep the DDL consistent: a `GENERATED ... AS IDENTITY` root key
must not be modeled as accepting a client-supplied `_id` on insert.
**WHY** — Mismatch surfaces as insert conflicts through the view. Document
consumers usually want a client-settable string `_id` (they know it before
insert); state the trade — 16-byte RAW vs 36-char string in every index.
**CHECK** —

```sql
SELECT column_name, identity_column, data_type, data_default
FROM   user_tab_columns
WHERE  table_name = :root_table;
```

`IDENTITY_COLUMN = 'YES'` on the key ⇒ the document model must not supply `_id`.

### Gate 9 — The column-type allowlist is a hard gate

**RULE** — Every projected column's type must be on the duality allowlist (JSON,
character types, RAW, BOOLEAN, NUMBER, BINARY_DOUBLE/BINARY_FLOAT, DATE,
TIMESTAMP [WITH TIME ZONE], intervals, LOBs, VECTOR). An unsupported type is a
blocker — exclude, retype, or project around it; there is no silent passthrough.
**WHY** — Assuming passthrough hides the failure until DDL time; the fix (retype
or exclude) is a modeling decision, so make it during modeling.
**CHECK** —

```sql
SELECT column_name, data_type
FROM   user_tab_columns
WHERE  table_name = :base_table;
```

Review every type against the allowlist before proposing the projection.

### Gate 10 — No duality over textual JSON

**RULE** — Base columns must be native `JSON` type or relational scalars; a
VARCHAR2/CLOB/BLOB column holding JSON text (even with an `IS JSON` constraint)
cannot participate — convert to `JSON` type first.
**WHY** — The sneakiest brownfield blocker: a migrated collection stored as
textual JSON cannot be stitched by duality until it is physically converted.
**CHECK** —

```sql
SELECT table_name, column_name, data_type, format
FROM   user_json_columns
WHERE  data_type <> 'JSON';
```

Any listed column feeding a proposed view converts before the view ships.

### Gate 11 — No duplicate keys, no unconstrained self-nesting

**RULE** — No duplicate JSON keys at the same object level; a self-referential
nesting (a table under itself) requires an explicit distinct join predicate.
**WHY** — Duplicate keys make invalid documents; unconstrained self-nesting
defines an infinitely recursive one.
**CHECK** —

```sql
SELECT DBMS_METADATA.GET_DDL('VIEW', :view_name) FROM dual;
```

Verify key uniqueness per level and the distinct predicate on any self-join —
before creation, not by letting `CREATE` fail.

## Write-path gates


The engine is looser than this gate, and the difference is measured rather
than assumed: In Oracle 26ai, a JSON Relational Duality view rooted at table T
can nest T again under a child array via @link (to: [FK_COL]) on a
self-referencing FK on T; the engine accepts the CREATE and the resulting view
is readable, even though the oracle-ai-dev plugin's own duality-view validator
(gate 11) rejects/flags this pattern — the validator is stricter than the
actual engine here. Treat the blocker as unconfirmed-strict until someone
reproduces the CREATE here; it may be the gate that needs loosening, not the
model.

### Gate 12 — Read-only by default; DML is a per-table opt-in

**RULE** — Design every view read-only first; grant INSERT/UPDATE/DELETE per
contributing table only where the write path requires it, and record every
writable table as a deliberate decision in `data_model.md`.
**WHY** — Updatability as an additive grant is what contains write amplification
and accidental writes; a default-writable view is an unaudited mutation surface.
**CHECK** —

```sql
SELECT view_name, table_name, allow_insert, allow_update, allow_delete
FROM   user_json_duality_view_tabs
ORDER  BY view_name, table_name;
```

Every `YES` needs a recorded reason.

### Gate 13 — Junction tables never get NODELETE

**RULE** — A mapping table under an editable N:M array must allow DELETE; never
annotate the junction `NODELETE`.
**WHY** — Removing an array element must delete the mapping row; a NODELETE
junction orphans rows silently.
**CHECK** — In the Gate 12 query, `ALLOW_DELETE = 'NO'` on a table classified as
a pure junction under an editable array is a defect.

### Gate 14 — Pure-junction test before collapsing

**RULE** — Collapse a mapping table out of the document only if it is a *pure*
junction: exactly two FKs, every column participates in an FK, and the PK equals
the union of the two FK column sets. Any payload column (quantity, role,
effective_date) makes it an associative entity that keeps its own nested object.
**WHY** — Flattening a payload-carrying junction silently drops business data
from the document.
**CHECK** —

```sql
SELECT constraint_name, constraint_type
FROM   user_constraints
WHERE  table_name = :junction_table
AND    constraint_type IN ('P', 'R');
```

Exactly two `R` rows; then confirm in `USER_CONS_COLUMNS` that every table column
sits inside the two FK column sets and the PK is their union.

### Gate 15 — ETag scope is a concurrency decision, not a convenience

**RULE** — Exclude a column from the ETag (`NOCHECK`) only for genuinely
volatile, non-business metadata. `NOCHECK` on a mutable business scalar means
concurrent edits silently overwrite each other.
**WHY** — The ETag is a content hash over the checked fields: it detects
out-of-band writes too. Excluding volatile fields avoids false conflicts;
excluding real fields removes the protection entirely.
**CHECK** — Pull the DDL (`DBMS_METADATA.GET_DDL`) and justify every `NOCHECK`;
flag any mutable business-meaningful field found outside ETag scope.

### Gate 16 — The write path round-trips `_metadata.etag` unmodified

**RULE** — Read-modify-write through the view writes the whole document back
INCLUDING the original `_metadata.etag`; no serializer, ORM, or "sanitizing"
layer may strip `_metadata`.
**WHY** — Oracle compares the embedded etag and raises ORA-42699 on a stale
write. Stripping `_metadata` does NOT error — it silently disables conflict
detection, the single most likely duality integration bug.
**CHECK** — Behavioral, not dictionary: write a deliberately stale etag and
assert ORA-42699 (map it to your API's 409/conflict). A concurrency test that
never sees ORA-42699 proves nothing.

## Projection-scope gates

Which entities get a projection, which fields each carries, and which tables may
write are three distinct least-privilege layers — projection scope *is*
authorization, a framing developed in the authors' converged-database book
project. The gates below make it checkable.


The same hole is open through the Mongo lane, so the rule is not just about
our generated datalayer. Oracle's API for MongoDB's `replaceOne` against a
JSON Relational Duality View performs no optimistic-concurrency check when the
document's `_metadata` (ETag) field is stripped before the call — the write is
accepted unconditionally and silently overwrites the current row. Concurrency
protection only triggers when `_metadata` is present with a mismatched ETag,
in which case the write correctly fails with `ORA-42699: ... The ETAG of
document with ID '...' in the database did not match the ETAG passed in.`
Applications must explicitly preserve/pass `_metadata` on every replace —
concurrency protection is opt-in by payload shape, not enforced by default.

### Gate 17 — Entity views plus a small, named composite set

**RULE** — Emit one CRUD-shaped *entity* view per aggregate for the write path,
plus a deliberately small, named set of read-only *composite* views — one per
hot, join-shaped read pattern; nested tables in composites are explicitly
read-only.
**WHY** — Composites are where the app's join-shaped reads are encoded; routing
writes through single-root entity views avoids ambiguous multi-table mutations.
One write path, two read paths.
**CHECK** — Count composites against the ranked hot read patterns (no orphan
composites, no hot pattern without one); the Gate 12 query must show all-`NO`
write flags on every composite's tables.

### Gate 18 — One view per aggregate root: re-root, never overload

**RULE** — When consumers need different roots over the same tables, create
another view rooted there; never widen one view to serve two aggregates.
**WHY** — A kitchen-sink view makes every point read pay for the widest read's
joins — a view costs exactly what it nests.
**CHECK** —

```sql
SELECT view_name, root_table_name
FROM   user_json_duality_views
ORDER  BY root_table_name;
```

Two consumers sharing a view whose fields neither fully uses ⇒ split and re-root.

### Gate 19 — One projection per consumer contract, minimum fields

**RULE** — Scope each projection to one consumer screen or API contract and
project only the fields that contract needs — never the whole row by reflex.
Sensitive and mechanical fields (password hash, optimistic-lock version) live
only on the narrow trusted-path view.
**WHY** — Field-level projection means a consumer — including an AI agent —
literally cannot see undeclared fields.
**CHECK** —

```sql
SELECT view_name, table_name, column_name
FROM   user_json_duality_view_tab_cols
WHERE  column_name = :sensitive_column;
```

Every view returned must be a trusted-path view; diff each view's projected
field list against its consumer's contract.

### Gate 20 — Some entities get NO view; record the absence

**RULE** — Auth/token tables, audit logs, append-only ledgers, and migration
bookkeeping touched only by trusted server SQL get no duality view at all;
record the deliberate absence in `data_model.md`.
**WHY** — The absence of a projection is an access-control decision: a document
API must not be able to reach secrets or ledgers in any shape.
**CHECK** —

```sql
SELECT table_name
FROM   user_tables
WHERE  table_name NOT IN (SELECT table_name
                          FROM   user_json_duality_view_tabs);
```

Every listed table is either intentionally unprojected (with the reason written
down) or a gap in the projection layer.

### Gate 21 — Write flags are least-privilege surfaces; audit them per consumer

**RULE** — When consumers need different mutation rights over the same canonical
tables, build one view per consumer, each granting exactly the writes that
consumer needs; computed/expression fields are read-only by construction.
**WHY** — Per-table write flags are an authorization model, not bookkeeping —
the auditable mutation surface of each consumer.
**CHECK** — The Gate 12 query is the audit; review it grouped by consumer, not
by view, and challenge any grant no consumer's contract requires.

### Gate 22 — VPD/RAS policy goes on base tables, never on the view

**RULE** — Row/column/cell security (VPD, Real Application Security, redaction)
is applied to the BASE TABLES and inherited through the projection. VPD and RAS
are NOT supported on duality views — "put VPD on the view" does not work.
**WHY** — Base-table policy is enforced below every consumer of every shape —
SQL, document API, or an AI agent — where a compromised prompt cannot rewrite it.
**CHECK** —

```sql
SELECT object_name, policy_name
FROM   user_policies;
```

Every policy object is a base table; none targets a duality view.

### Gate 23 — Index the base tables, never the view's DATA column

**RULE** — Functional, JSON search, and multivalue indexes cannot be created on
a duality view's `DATA` column; derive the indexes each access pattern implies
and create them on the base tables.
**WHY** — The view is a projection; physical structures belong to the canonical
tables. This rule pre-empts the "why is my index on the view ignored" class of
confusion.
**CHECK** —

```sql
SELECT index_name, table_name
FROM   user_indexes
WHERE  table_name = :base_table;
```

Every hot predicate in the pattern list resolves to a base-table index.

## Packaging

### Gate 24 — Views ship in their own migration layer

**RULE** — Base tables and constraints migrate first; duality views live in a
separate, replayable migration layer of pure `CREATE OR REPLACE` statements.
**WHY** — The projection layer then evolves — drop, rebuild, iterate — without
touching table DDL or data.
**CHECK** — The views layer contains no `CREATE TABLE`; the tables layer contains
no `CREATE JSON RELATIONAL DUALITY VIEW`; re-running the views layer is a no-op
for data.

## Oracle Version Notes

- Written against Oracle AI Database 26ai. Duality views do not exist before
  23ai; on anything older these gates are moot.
- The column-type allowlist grows across releases (BOOLEAN and VECTOR are recent
  additions) — verify Gate 9's list against the JSON-Relational Duality guide for
  the target RU.
- Dictionary shapes are RU-sensitive: confirm the exact columns of
  `USER_JSON_DUALITY_VIEWS`, `USER_JSON_DUALITY_VIEW_TABS`, and
  `USER_JSON_DUALITY_VIEW_TAB_COLS` (`DESC` them) on the target before scripting
  the checks.

## Sources

- Oracle Database JSON-Relational Duality Developer's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/jsnvu/
- Oracle Database Reference (26ai), `USER_JSON_DUALITY_VIEW%` dictionary views —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/refrn/
- Duality-view validator/generator rules and iterated application-schema
  corrections — field-verified, 2025–2026.
- Projection-as-authorization framing — from the authors' converged-database
  book project.

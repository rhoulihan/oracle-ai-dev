# Designing a duality view

A duality view maps normalized tables to one document. Design it from the
canonical model (hand off from the modeling skill), not the other way around.

## Rules

- **Array children must project their full primary key — and this failure is
  SILENT until read.** A duality view whose composite-PK array child omits any
  PK column **CREATEs successfully and even answers `COUNT(*)`**, then throws
  **`ORA-40477: internal JSON error ''`** the first time a document is read —
  an error that names nothing useful (field-verified twice, on two- and
  three-column child keys). Always project the full child PK, or use a
  surrogate single-column PK. The seeded `order_dv` projects `order_item_id`
  for exactly this reason.
- **An `@unnest` sub-object is flattened into the parent — never give it a
  field name.** `country : ref_countries @unnest {...}` fails at CREATE with
  **ORA-42679** ("Cannot @UNNEST sub-object ... mentioned with the alias").
  Correct form: `ref_countries @unnest { ... }`.
- **An `@unnest` block must project its linking column.** Omitting the FK the
  unnest joins on fails loudly at CREATE with **ORA-42550** ("linking column
  ... should be selected") — include the join column in the block.
- **A duality view projects the REAL column types — Mongo clients must match.**
  A `DATE` column comes back as a date, not a string: a Java client's
  `getString("date_from")` throws `ClassCastException`, and writing an ISO
  string back fails **ORA-40944 / JZN-00672**. Use the driver's date type
  (UTC-anchored). Code that worked against a native collection (which stores
  whatever the writer sent) breaks on BOTH paths when pointed at a duality
  view — a real porting hazard.
- **Duality views are read-time joins.** They trade a costlier read for zero write
  amplification. A write-hot access path (a cart being updated constantly) should
  not pay that join on every write — model it as a single collection instead.
  "Joins are never free."
- **Annotate mutability per table.** `@insert @update @delete` (or their `@no…`
  negations) control which base tables a document write may change. Reference,
  read-only lookups use `@noinsert @update @nodelete` or fully read-only.
- **Creation is SQL-only.** A Mongo client can CRUD a duality view as a collection
  but cannot create one; unquoted view names resolve uppercase.

## When NOT to use one
Write-heavy hot paths; single-entity documents with no relational consumer (use a
JSON collection); pure analytics (use SQL over the base tables).

## Sources
- Oracle JSON-Relational Duality Developer's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/jsnvu/

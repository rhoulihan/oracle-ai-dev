# Duality-view limitations — when to use a SQL view instead

A JSON Relational Duality view is the first choice when relational storage wins
(write-efficient) but the app wants a document API: it gives both, from one truth.
But a duality view's SELECT is restricted so the view stays updatable, so it
**cannot express** some operations. When the projection needs one of those, keep a
**traditional SQL view** as the shape instead — read-only, but full SQL expressiveness.

## Operations a duality view cannot express
A duality view's columns must map to underlying table columns for round-trip
updatability, so these are not allowed in the view definition:
- **`COALESCE`** and other value-substitution/derived expressions.
- Computed/derived columns (`col_a + col_b`, `CASE … END` producing a new value,
  `DECODE`).
- Aggregation / `GROUP BY`, window functions, `DISTINCT`.
- `UNION` / set operators, and many multi-table shapes beyond simple parent/child
  nesting.

A `@NOCHECK` nested singleton is a fourth thing it cannot express, and it only
shows up on the write. A JSON-relational duality view with a `@NOCHECK` nested
singleton whose foreign key is NULL renders that nested object as `{}` on
read, but writing the unmodified document back fails with ORA-40943 (nested
object's primary key required) because Oracle demands the nested PK on write
despite omitting it on read; there is no client-side workaround (stripping the
`{}` before write, or replaying the equivalent plain SQL, both still fail), so
treat it as a modeling constraint rather than a bug to code around.

Shredding one back into rows is the other trap, and this one is a performance
cliff rather than an error. In Oracle 26ai, a JSON_TABLE-shred query that
joins a JSON Relational Duality view to a CTE on JSON_VALUE(data,'$._id')
starts on a keyed access plan (one document per matched key) and is then
re-optimized by statistics feedback into a full assembly of every duality-view
document plus a semi-join, measured ~30x slower (1.2 s -> 32 s; 3.5M buffer
gets vs 122K). Root cause: the optimizer has no cardinality statistics for a
JSON_TABLE shred over a duality-view document (E-Rows 1 per document vs ~40K
actual), so feedback from the first run re-costs the per-key nested loop as
expensive and prefers one pass over the whole view, whose per-document
assembly it does not cost. The flip is not permanent: a third parse, fed back
again from the slow plan's own misestimate, reselects the keyed plan (child
cursors 0 -> 1 -> 2, plan hash returns to the original, is_reoptimizable = N).
But any cursor that stays open or cached after obtaining the slow plan keeps
it (PL/SQL cursor cache, JDBC statement cache, pooled connections) — so
production latency is bimodal across connections rather than uniformly slow,
and the fix is structural (do not shred documents to answer a relational
question); gathering statistics or hinting one cursor does not address it.
Rewriting the join predicate as a nested-path JSON_EXISTS on the view keeps
the keyed plan on every parse.

## The rule
- **Relational shape wins → lean into a duality view** (keeps the document API over
  write-efficient tables).
- **The projection needs COALESCE / a derived column / aggregation → use a
  traditional SQL view** (read-only) for that query. The optimizer treats
  `sql_view` as its own candidate shape and routes to it when duality can't express
  the query.

## Make the SQL view return documents
A traditional view still gives the app a JSON/document result: **wrap the
projection in `JSON_OBJECT`** (one row → one object) or **`JSON_ARRAYAGG`** (a set
of rows → a JSON array). This keeps the document-shaped output that duality would
have provided, while gaining COALESCE/derived-column/aggregation expressiveness —
the tradeoff is that a plain SQL view is read-only (writes go to the base tables).
```sql
-- read-only, but expresses COALESCE and returns a document
CREATE VIEW order_summary_v AS
SELECT JSON_OBJECT(
         'orderId'    VALUE o.order_id,
         'restaurant' VALUE COALESCE(r.name, 'Unknown'),
         'items'      VALUE (SELECT JSON_ARRAYAGG(JSON_OBJECT('qty' VALUE oi.quantity))
                             FROM order_item oi WHERE oi.order_id = o.order_id)
       ) AS doc
FROM orders o JOIN restaurant r ON r.restaurant_id = o.restaurant_id;
```

## Sources
- Oracle JSON-Relational Duality Developer's Guide (26ai), restrictions —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/jsnvu/

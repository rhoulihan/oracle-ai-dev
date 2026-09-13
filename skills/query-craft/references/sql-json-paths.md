# SQL/JSON path expressions

Path expressions address into a JSON document. Used by `JSON_VALUE`,
`JSON_QUERY`, `JSON_EXISTS`, and `JSON_TABLE`.

## Basics
- `$` — the whole document; `$.field` — a member; `$.arr[*]` — all array elements.
- Filters: `$.items[*]?(@.qty > 1)` — array elements matching a predicate.
- `JSON_VALUE(data, '$.total' RETURNING NUMBER)` — one scalar, typed.
- `JSON_QUERY(data, '$.items')` — a fragment (array/object).
- `JSON_EXISTS(data, '$.items[*].name?(@ == "Margherita")')` — a predicate.

## Turning arrays into rows
```sql
SELECT j.name, j.qty
FROM order_docs,
     JSON_TABLE(data, '$.items[*]'
       COLUMNS (name PATH '$.name', qty NUMBER PATH '$.qty')) j;
```

## Gotchas
- Dot notation (`d.data.total`) returns VARCHAR2; use `JSON_VALUE ... RETURNING`
  for typed comparisons and indexable predicates.
- Match the indexed path exactly for a multivalue index to be used.

Translating a Mongo filter is where this one bites, because the same literal
means something narrower there. In Oracle SQL/JSON path expressions, the ==
comparison operator is type-lax: $.items[*]?(@.item_id == 1000) also matches
the string "1000", not just the number 1000. mongosh's arrayFilter {item_id:
1000} is strict and only matches the number. A SQL/JSON translation of a
MongoDB update query therefore silently updates more rows than the Mongo
original unless a type check is added: @.item_id.type() == "number" &&
@.item_id == 1000. Measured on Oracle AI Database 26ai 23.26.3.2.0.

## Sources
- Oracle JSON Developer's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/

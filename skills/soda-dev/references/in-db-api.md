# SODA in-database API (DBMS_SODA)

Create and use collections from PL/SQL. A no-metadata create makes a native JSON
collection table: content column `DATA JSON`, plus a `RESID RAW` key column whose
`assignmentMethod` is `EMBEDDED_OID` — Oracle extracts `_id` from the document body,
MongoDB-style — and which carries the table's **primary key**. That constraint already
enforces `_id` uniqueness, so **do not add a separate `_id` index**. (Also present: an
`ETAG` version column and an internal `SYS_IME_OSON_*` column.)

## Create + insert + query
```sql
DECLARE
  coll SODA_COLLECTION_T;
  doc  SODA_DOCUMENT_T;
  n    NUMBER;
BEGIN
  coll := DBMS_SODA.CREATE_COLLECTION('reviews_soda');
  n := coll.INSERT_ONE(SODA_DOCUMENT_T(b_content => UTL_RAW.CAST_TO_RAW(
         '{"restaurant":"Trattoria Uno","rating":5}')));
  COMMIT;
END;
/
```
Query with QBE: `coll.FIND().FILTER('{"rating": {"$gte": 4}}').GET_CURSOR`.

## Gotchas
- **`DROP_COLLECTION` is a FUNCTION, not a procedure.** `dbms_soda.drop_collection(x);`
  fails to compile with **PLS-00221** — the error prints, but SQL*Plus still **exits 0**,
  so a cleanup script gated on the exit status reports success and drops nothing. Assign
  the result, add `whenever sqlerror exit failure`, and verify with a count:
  ```sql
  declare n number;
  begin
    for r in (select uri_name from user_soda_collections) loop
      n := dbms_soda.drop_collection(r.uri_name);   -- returns 1 when dropped
    end loop;
  end;
  /
  select count(*) from user_soda_collections;       -- must be 0
  ```
- **Commit before `create_index`.** SODA's index DDL runs recursive DDL; an
  uncommitted collection transaction causes **ORA-00054** (resource busy). Commit
  the inserts first, then create the index.
- A whole-anonymous-block rollback silently discards prior inserts — commit
  deliberately.
- QBE supports the operator set (`$eq`..`$regex`, `$and`/`$or`, `$orderby`, spatial,
  `$contains`) but **not aggregation** — for pipelines use SQL/JSON or the Mongo API.
- **Never let two collection names differ only by case.** Oracle SODA creates two
  objects per collection: a case-preserved quoted backing table, and a case-FOLDED
  (uppercased) PUBLIC synonym pointing at it. Two collections whose names differ only by
  case (e.g. 'Widgets' and 'widgets') cannot coexist: the second CREATE COLLECTION
  succeeds at the table level but fails at the synonym level with ORA-00955 ('name is
  already used by an existing object'), because both names fold to the same synonym.
  USER_OBJECTS also returns both folded and case-preserved identifiers in the same
  OBJECT_NAME column of one result set, so no per-column case-folding rule can be
  applied uniformly when reading names back from it. Pick one casing convention per
  schema; to recover the spelling you stored, read `URI_NAME` from
  `USER_SODA_COLLECTIONS` rather than parsing `USER_OBJECTS`.
- **Query `USER_SODA_COLLECTIONS` by column name, not by guesswork.**
  USER_SODA_COLLECTIONS has no SCHEMA_NAME column, despite that being the obvious name
  to guess. It is a PUBLIC synonym for XDB.JSON$USER_COLLECTION_METADATA; querying
  SCHEMA_NAME raises ORA-00904. The real columns are URI_NAME, OBJECT_TYPE,
  OBJECT_SCHEMA, OBJECT_NAME, CREATED_ON, CREATE_MODE, JSON_DESCRIPTOR — the owning
  schema is OBJECT_SCHEMA, and JSON_DESCRIPTOR is VARCHAR2(4000), not a CLOB. Name the
  columns you want rather than `SELECT *` into a positional reader, and treat the
  descriptor as a string to parse as JSON.

## Interop
A collection created here is visible via `db.<coll>.find()` through the Mongo API,
SQL/JSON over its table, and SODA for REST — one collection, many surfaces.

## Sources
- Oracle SODA for PL/SQL Developer's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/adsdp/

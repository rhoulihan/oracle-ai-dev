# GraphQL over duality views

Oracle AI Database 26ai serves GraphQL natively over JSON Relational Duality
views, both in SQL (the `GRAPHQL()` operator / table function) and over REST via
ORDS (`/ords/{schema}/_/graphql`).

## In SQL
Query a duality view with a GraphQL selection instead of SQL/JSON path
expressions — the shape of the returned document follows the GraphQL query.

## Over REST (ORDS)
When ORDS is running (the `db+ords` profile), REST-enabled objects expose a
GraphQL endpoint. Enable the schema and REST-enable the duality view, then POST
GraphQL queries to `/ords/{schema}/_/graphql`.

## Defining a view in GraphQL syntax
Duality views can be defined in a GraphQL-style DDL as well as the SQL
`SELECT JSON {…}` form. The seeded `order_dv` uses the GraphQL-style `@insert`/
`@update`/`@delete` annotations.

## Sources
- Oracle JSON-Relational Duality Developer's Guide (26ai), GraphQL —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/jsnvu/

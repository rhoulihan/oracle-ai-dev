---
name: ords-rest-sql-headless-adb
description: Drive a wallet-less/green-button Autonomous Database headlessly (no SQLcl, no Cloud Shell, no wallet/1521/mTLS) by POSTing SQL text to ORDS REST-Enabled SQL. Use when scripting or CI-verifying SQL/PLSQL against a sandbox ADB where only the Database Actions URL is available.
---
# ords-rest-sql-headless-adb

## Procedure

1. Identify the ORDS base URL exposed by the sandbox's Database Actions link (form: `{ords_base}/ords/{schema}/`).
2. POST the full SQL/PLSQL script as the request body to `{ords_base}/ords/{schema}/_/sql`.
3. Set `Content-Type: application/sql` and use HTTP basic auth with the schema's DB credentials.
4. The endpoint parses the body exactly like the SQL Worksheet's "Run as script" — multi-statement scripts and PL/SQL blocks terminated by `/` are supported in one request. **Each request runs in its own session with autocommit**: anything depending on it must be submitted together in a single POST. The common case is `EXPLAIN PLAN` followed by `dbms_xplan.display()`, which fails with "cannot fetch last explain plan" when split across two requests; temp table contents and session settings behave the same way.
5. Read the response: JSON with one result entry per statement; failures surface in an `errorDetails` field per statement rather than aborting the whole batch silently.

## Failure pattern

Assumed a green-button/wallet-less sandbox needed a wallet, port 1521, or mTLS client config to run SQL headlessly — none of that is available or needed. The only thing the sandbox actually exposes is the Database Actions URL, and ORDS REST-Enabled SQL at `_/sql` is the correct headless entry point for it.

Second trap, once connected: treating the endpoint as a persistent session. It is not. Splitting `EXPLAIN PLAN` from `dbms_xplan.display()` across two requests returns "cannot fetch last explain plan", because the plan table content is session-scoped and each request gets a new session.

The scope of that is wider than this one endpoint. Every HTTP request to an
ORDS SQL-over-HTTPS surface runs in its own new database session with
autocommit; session-scoped state does not survive across requests. This holds
for both ORDS REST-Enabled SQL (`{ords_base}/ords/{schema}/_/sql`) and Oracle
Database Actions (SQL Worksheet). Concretely, PLAN_TABLE output from EXPLAIN
PLAN is lost before a following request can read it, so EXPLAIN PLAN and
`dbms_xplan.display()` must be submitted together in a single request —
splitting them produces "cannot fetch last explain plan". Anything else
session-scoped (temp table contents, session settings, `DBMS_SESSION` state)
behaves the same way.

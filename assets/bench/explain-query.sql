-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Capture the ACTUAL execution plan for a candidate query, off the timing path —
-- the explanatory layer over the measured cost (why a shape reads what it reads).
-- Uses gather_plan_statistics + DBMS_XPLAN.DISPLAY_CURSOR('ALLSTATS LAST'), which
-- shows real A-Rows vs estimated E-Rows and per-operation Buffers (logical reads),
-- exposing cardinality misestimates and where the reads go (index range scan,
-- nested-loop vs hash join, single LOB fetch, JSON operator pushdown).
--
-- This is the free, always-available per-statement equivalent of SQL Monitor / AWR
-- (which require the Tuning / Diagnostics Pack license and are unavailable on Free);
-- it needs only SELECT on the V$SQL* views (SELECT_CATALOG_ROLE).
--
-- The query is wrapped in COUNT(*) so all rows are fetched (populating rowsource
-- stats) with one line of output; the plan beneath the SORT AGGREGATE is the
-- candidate's real access/join structure. Substitutions: &label &query_text.
-- Not run inside the timed loop — call it once per shape after warmup.
SET VERIFY OFF
SET FEEDBACK OFF
SET PAGESIZE 200
SET LINESIZE 200
-- SERVEROUTPUT must be OFF: with it ON, SQL*Plus runs a DBMS_OUTPUT.GET_LINES call
-- after each statement, which would become the "previous cursor" and defeat
-- DISPLAY_CURSOR(NULL). The plan is emitted as query rows, not DBMS_OUTPUT.
SET SERVEROUTPUT OFF
ALTER SESSION SET STATISTICS_LEVEL = ALL;

SELECT /* EXPLAIN:&label */ COUNT(*) AS rows_fetched FROM (&query_text);

PROMPT PLAN:&label
SELECT plan_table_output
  FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(NULL, NULL, 'ALLSTATS LAST +COST'));

ALTER SESSION SET STATISTICS_LEVEL = TYPICAL;

-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Server-side DML timing harness for WRITE AMPLIFICATION (methodology hardened).
-- Write amplification — a single-row UPDATE vs a whole-document JSON_TRANSFORM
-- rewrite vs a duality fan-out — shows up far more sharply in REDO SIZE than in
-- wall-clock, so redo bytes per iteration is the primary cost.        [P5,P1]
--   * &warmup iterations discarded (rolled back) in their own call     [P3]
--   * &trials trials, each &iters executions, each ROLLBACK'd          [P4]
--   * SYSTIMESTAMP microseconds per trial -> MEDIAN + coefficient of variation
-- Emits: BENCH:<label>:<redo_per_iter>:cg=<redo_per_iter>:us=<median_us>:cv=<cv>
-- (cg carries redo bytes so analyze.py reads one integer primary cost; falls back
-- to µs if 'redo size' is not visible). ROLLBACK keeps the seed intact.
--
-- Redo/block-change statistics flush to V$MYSTAT only at CALL boundaries (unlike
-- consistent gets, which updates live), so redo is bracketed ACROSS calls: warm
-- up, snapshot redo, run the trials block, then read redo again. The figure
-- includes each trial's ROLLBACK redo — deterministic and proportional across
-- shapes, so the amplification ratio is preserved. The µs median/CV come out of
-- the trials block via bind variables. Substitutions: &label &iters &dml (no ';').
-- Reading V$MYSTAT needs SELECT_CATALOG_ROLE.
SET SERVEROUTPUT ON
SET VERIFY OFF
DEFINE warmup = 5
DEFINE trials = 7
VARIABLE med_us NUMBER
VARIABLE cvout  NUMBER

-- Call 1: warm up (hard-parse + cold cache excluded) and roll back.
BEGIN
  FOR w IN 1 .. &warmup LOOP EXECUTE IMMEDIATE q'[&dml]'; END LOOP;
  ROLLBACK;
END;
/

-- Call 2: snapshot redo AFTER warmup has flushed (excludes warmup from the count).
COLUMN r0 NEW_VALUE r0 NOPRINT
SELECT NVL(SUM(s.value), 0) AS r0
  FROM v$mystat s JOIN v$statname n ON n.statistic# = s.statistic#
 WHERE n.name = 'redo size';

-- Call 3: the trials. Per-trial microseconds -> median + CV, returned via binds.
DECLARE
  TYPE num_tab IS TABLE OF NUMBER;
  us_costs num_tab := num_tab();
  ts0 TIMESTAMP; us NUMBER;

  PROCEDURE isort(t IN OUT NOCOPY num_tab) IS
    tmp NUMBER; j PLS_INTEGER;
  BEGIN
    FOR i IN 2 .. t.COUNT LOOP
      tmp := t(i); j := i - 1;
      WHILE j >= 1 AND t(j) > tmp LOOP t(j + 1) := t(j); j := j - 1; END LOOP;
      t(j + 1) := tmp;
    END LOOP;
  END;
  FUNCTION med(t num_tab) RETURN NUMBER IS  -- MEDIAN of a sorted collection
    n PLS_INTEGER := t.COUNT;
  BEGIN
    IF n = 0 THEN RETURN 0; END IF;
    IF MOD(n, 2) = 1 THEN RETURN t((n + 1) / 2);
    ELSE RETURN (t(n / 2) + t(n / 2 + 1)) / 2; END IF;
  END;
  FUNCTION cvof(t num_tab) RETURN NUMBER IS
    n PLS_INTEGER := t.COUNT; s NUMBER := 0; m NUMBER; sq NUMBER := 0;
  BEGIN
    IF n < 2 THEN RETURN 0; END IF;
    FOR i IN 1 .. n LOOP s := s + t(i); END LOOP;
    m := s / n;
    IF m = 0 THEN RETURN 0; END IF;
    FOR i IN 1 .. n LOOP sq := sq + (t(i) - m) * (t(i) - m); END LOOP;
    RETURN SQRT(sq / (n - 1)) / m;
  END;
BEGIN
  FOR t IN 1 .. &trials LOOP
    ts0 := SYSTIMESTAMP;
    FOR i IN 1 .. &iters LOOP
      EXECUTE IMMEDIATE q'[&dml]';
    END LOOP;
    us  := EXTRACT(DAY    FROM (SYSTIMESTAMP - ts0)) * 86400e6
         + EXTRACT(HOUR   FROM (SYSTIMESTAMP - ts0)) * 3600e6
         + EXTRACT(MINUTE FROM (SYSTIMESTAMP - ts0)) * 60e6
         + EXTRACT(SECOND FROM (SYSTIMESTAMP - ts0)) * 1e6;
    us_costs.EXTEND; us_costs(t) := us / &iters;
    ROLLBACK;
  END LOOP;
  isort(us_costs);
  :med_us := med(us_costs);
  :cvout  := cvof(us_costs);
END;
/

-- Call 4: redo has flushed; combine with the µs binds and emit BENCH.
DECLARE
  redo_total NUMBER; per_iter NUMBER; primary_cost NUMBER;
BEGIN
  SELECT NVL(SUM(s.value), 0) - &r0 INTO redo_total
    FROM v$mystat s JOIN v$statname n ON n.statistic# = s.statistic#
   WHERE n.name = 'redo size';
  per_iter := redo_total / (&trials * &iters);
  IF per_iter > 0 THEN primary_cost := ROUND(per_iter);
  ELSE primary_cost := ROUND(:med_us); END IF;
  DBMS_OUTPUT.PUT_LINE(
    'BENCH:&label:' || TO_CHAR(primary_cost)
    || ':cg=' || TO_CHAR(ROUND(per_iter))
    || ':us=' || TO_CHAR(ROUND(:med_us))
    || ':cv=' || TO_CHAR(ROUND(:cvout, 3)));
END;
/

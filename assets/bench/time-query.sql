-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Server-side query timing harness (measurement-methodology hardened).
--   * primary cost = per-execution LOGICAL READS (consistent gets) — an integer,
--     cache-independent metric that separates shapes even on a tiny seed, where a
--     10 ms wall-clock reads 0 (docs/research/benchmark-methodology-notes.md P1).
--   * &warmup runs are discarded (hard-parse + cold cache excluded)          [P3]
--   * &trials trials, each &iters executions; reports the MEDIAN per-exec cost
--     and the coefficient of variation (noise gate)                          [P4]
--   * SYSTIMESTAMP microseconds as the secondary/tiebreak metric             [P2]
--   * RESULT_CACHE_MODE=MANUAL so a cached result can't mask execution       [P8]
-- Emits: BENCH:<label>:<median_cost>:cg=<median_gets>:us=<median_us>:cv=<cv>
-- where median_cost = median logical reads (or rounded µs if catalog views are
-- not granted). Substitutions: &label &iters &query_text &warmup &trials.
-- Reading V$MYSTAT needs SELECT_CATALOG_ROLE; without it the harness degrades to
-- microseconds only (cg=0) rather than failing.
SET SERVEROUTPUT ON
SET VERIFY OFF
DEFINE warmup = 5
DEFINE trials = 7
DECLARE
  TYPE num_tab IS TABLE OF NUMBER;
  cg_costs num_tab := num_tab();
  us_costs num_tab := num_tab();
  cg0 NUMBER; cg1 NUMBER;
  ts0 TIMESTAMP; us NUMBER;
  c   PLS_INTEGER := 0;
  med_cg NUMBER; med_us NUMBER; cv NUMBER; primary_cost NUMBER;

  -- Dynamic so a missing catalog grant degrades gracefully (returns 0) instead
  -- of failing the whole block at compile time.
  FUNCTION stat(p_name VARCHAR2) RETURN NUMBER IS
    v NUMBER;
  BEGIN
    EXECUTE IMMEDIATE
      'SELECT NVL(SUM(s.value),0) FROM v$mystat s '
      || 'JOIN v$statname n ON n.statistic# = s.statistic# WHERE n.name = :1'
      INTO v USING p_name;
    RETURN v;
  EXCEPTION WHEN OTHERS THEN RETURN 0;
  END;

  -- Median/CV are computed in pure PL/SQL: a local collection type cannot be used
  -- with the SQL TABLE() operator (PLS-00642), so no aggregate-over-collection.
  PROCEDURE isort(t IN OUT NOCOPY num_tab) IS
    tmp NUMBER; j PLS_INTEGER;
  BEGIN
    FOR i IN 2 .. t.COUNT LOOP
      tmp := t(i); j := i - 1;
      WHILE j >= 1 AND t(j) > tmp LOOP t(j + 1) := t(j); j := j - 1; END LOOP;
      t(j + 1) := tmp;
    END LOOP;
  END;
  FUNCTION med(t num_tab) RETURN NUMBER IS
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
  BEGIN EXECUTE IMMEDIATE 'ALTER SESSION SET RESULT_CACHE_MODE = MANUAL';
  EXCEPTION WHEN OTHERS THEN NULL; END;

  FOR w IN 1 .. &warmup LOOP
    FOR rec IN (&query_text) LOOP c := c + 1; END LOOP;
  END LOOP;

  FOR t IN 1 .. &trials LOOP
    cg0 := stat('consistent gets');
    ts0 := SYSTIMESTAMP;
    FOR i IN 1 .. &iters LOOP
      FOR rec IN (&query_text) LOOP c := c + 1; END LOOP;
    END LOOP;
    us  := EXTRACT(DAY    FROM (SYSTIMESTAMP - ts0)) * 86400e6
         + EXTRACT(HOUR   FROM (SYSTIMESTAMP - ts0)) * 3600e6
         + EXTRACT(MINUTE FROM (SYSTIMESTAMP - ts0)) * 60e6
         + EXTRACT(SECOND FROM (SYSTIMESTAMP - ts0)) * 1e6;
    cg1 := stat('consistent gets');
    cg_costs.EXTEND; cg_costs(t) := (cg1 - cg0) / &iters;
    us_costs.EXTEND; us_costs(t) := us / &iters;
  END LOOP;

  isort(cg_costs); isort(us_costs);
  med_cg := med(cg_costs); med_us := med(us_costs);
  -- CV of the metric we actually report as primary.
  IF med_cg > 0 THEN
    cv := cvof(cg_costs); primary_cost := ROUND(med_cg);
  ELSE
    cv := cvof(us_costs); primary_cost := ROUND(med_us);
  END IF;

  DBMS_OUTPUT.PUT_LINE(
    'BENCH:&label:' || TO_CHAR(primary_cost)
    || ':cg=' || TO_CHAR(ROUND(med_cg))
    || ':us=' || TO_CHAR(ROUND(med_us))
    -- Explicit format + NLS: the parser contract is dot-decimal, and this script runs
    -- in whatever locale the caller's SQLcl session has (easy/wallet mode pins none).
    || ':cv=' || TO_CHAR(ROUND(cv, 3), 'FM99990.999', 'NLS_NUMERIC_CHARACTERS=''.,'''));
END;
/

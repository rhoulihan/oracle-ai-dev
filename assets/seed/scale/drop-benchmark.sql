-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Drop ONLY the known benchmark objects, in FK-safe order. Names are a fixed
-- allow-list — this never drops an arbitrary user object. Missing objects are
-- ignored. Reached only through db-lifecycle.sh, which refuses to run this
-- against an external target without an explicit override.
SET FEEDBACK OFF
DECLARE
  PROCEDURE drop_obj(p_kind VARCHAR2, p_name VARCHAR2) IS
  BEGIN
    EXECUTE IMMEDIATE 'DROP ' || p_kind || ' ' || p_name
      || CASE WHEN p_kind = 'TABLE' THEN ' PURGE' ELSE '' END;
  EXCEPTION WHEN OTHERS THEN
    -- ORA-00942 table/view missing, ORA-04043 object missing, ORA-02289 seq missing
    IF SQLCODE NOT IN (-942, -4043, -2289) THEN RAISE; END IF;
  END;
BEGIN
  drop_obj('VIEW',  'order_dv');     -- duality view over the base tables first
  drop_obj('TABLE', 'order_docs');   -- document collection
  drop_obj('TABLE', 'order_item');
  drop_obj('TABLE', 'review');
  drop_obj('TABLE', 'address');
  drop_obj('TABLE', 'orders');
  drop_obj('TABLE', 'menu_item');
  drop_obj('TABLE', 'customer');
  drop_obj('TABLE', 'restaurant');
END;
/
PROMPT dropped benchmark objects (fixed allow-list only).

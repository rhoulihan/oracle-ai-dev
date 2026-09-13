-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Read-only: report which benchmark objects exist and their sample row counts.
-- Safe on any target (no DML/DDL) so you can inspect before init/load/reset.
SET FEEDBACK OFF
SET PAGESIZE 50
-- the row counts below come from DBMS_OUTPUT; without this they are discarded
SET SERVEROUTPUT ON
COLUMN object_name FORMAT A16
COLUMN object_type FORMAT A14
PROMPT === benchmark objects present ===
SELECT object_name, object_type
FROM user_objects
WHERE object_name IN ('ORDERS', 'ORDER_ITEM', 'ORDER_DOCS', 'ORDER_DV',
                      'RESTAURANT', 'CUSTOMER', 'MENU_ITEM')
ORDER BY object_type, object_name;

PROMPT === sample row counts (0 if table absent) ===
DECLARE
  FUNCTION cnt(p_tab VARCHAR2) RETURN NUMBER IS
    n NUMBER;
  BEGIN
    EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM ' || p_tab INTO n;
    RETURN n;
  EXCEPTION WHEN OTHERS THEN RETURN 0;  -- absent table -> 0
  END;
BEGIN
  DBMS_OUTPUT.PUT_LINE('orders=' || cnt('orders')
    || ' order_item=' || cnt('order_item')
    || ' order_docs=' || cnt('order_docs'));
END;
/

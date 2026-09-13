-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Idempotently create the least-privilege plugin_dev user (Class A-E model).
-- Positional arg &1 is the plugin_dev password.
DECLARE
  n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM all_users WHERE username = 'PLUGIN_DEV';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'CREATE USER plugin_dev IDENTIFIED BY "&1"';
    EXECUTE IMMEDIATE 'GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW, '
      || 'CREATE SEQUENCE TO plugin_dev';
    EXECUTE IMMEDIATE 'ALTER USER plugin_dev QUOTA 512M ON USERS';
  END IF;
  -- The measured optimizer reads V$MYSTAT (logical reads / redo) to explain WHY a shape
  -- costs what it does. Without this the app user cannot run the plugin's own flagship
  -- measurement (ORA-00942 on V_$STATNAME). Re-granted on every run so an existing user
  -- picks it up too.
  EXECUTE IMMEDIATE 'GRANT SELECT_CATALOG_ROLE TO plugin_dev';
END;
/

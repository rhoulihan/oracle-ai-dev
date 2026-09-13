-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Vector projection: add an embedding column to reviews. The IVF index is
-- created in 06 after data exists (IVF partitions need rows). IVF is the Free
-- default — HNSW would require VECTOR_MEMORY_SIZE (gap-3).
DECLARE
  n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM user_tab_columns
   WHERE table_name = 'REVIEW' AND column_name = 'EMBEDDING';
  IF n = 0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE review ADD (embedding VECTOR)';
  END IF;
END;
/

-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Verify the seed loaded. Emits ASSERT:<name>:PASS|FAIL lines (parsed by CI and
-- by the skills). Run against a connection with the seed schema loaded.
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0

SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_restaurant:PASS'
            ELSE 'ASSERT:seed_restaurant:FAIL' END FROM restaurant;
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_menu_item:PASS'
            ELSE 'ASSERT:seed_menu_item:FAIL' END FROM menu_item;
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_customer:PASS'
            ELSE 'ASSERT:seed_customer:FAIL' END FROM customer;
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_address:PASS'
            ELSE 'ASSERT:seed_address:FAIL' END FROM address;
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_orders:PASS'
            ELSE 'ASSERT:seed_orders:FAIL' END FROM orders;
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_order_item:PASS'
            ELSE 'ASSERT:seed_order_item:FAIL' END FROM order_item;
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_review:PASS'
            ELSE 'ASSERT:seed_review:FAIL' END FROM review;
SELECT CASE WHEN COUNT(*) = 2 THEN 'ASSERT:seed_order_docs:PASS'
            ELSE 'ASSERT:seed_order_docs:FAIL' END FROM order_docs;
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_vector_index:PASS'
            ELSE 'ASSERT:seed_vector_index:FAIL' END
       FROM user_indexes WHERE index_name = 'REVIEW_VEC_IVF';
SELECT CASE WHEN COUNT(*) > 0 THEN 'ASSERT:seed_graph:PASS'
            ELSE 'ASSERT:seed_graph:FAIL' END
       FROM GRAPH_TABLE (dining_graph MATCH (v IS customer) COLUMNS (v.customer_id AS cid));

-- Copyright (c) 2026 Oracle and/or its affiliates.
-- SQL/PGQ property graph over the canonical tables: customers place orders at
-- restaurants. Enables GRAPH_TABLE queries over the same one truth.
CREATE PROPERTY GRAPH IF NOT EXISTS dining_graph
  VERTEX TABLES (
    customer   KEY (customer_id),
    restaurant KEY (restaurant_id),
    orders     KEY (order_id)
  )
  EDGE TABLES (
    orders AS placed
      SOURCE KEY (customer_id) REFERENCES customer (customer_id)
      DESTINATION KEY (order_id) REFERENCES orders (order_id),
    orders AS at_restaurant
      SOURCE KEY (order_id) REFERENCES orders (order_id)
      DESTINATION KEY (restaurant_id) REFERENCES restaurant (restaurant_id)
  );

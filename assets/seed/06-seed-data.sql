-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Deterministic seed rows for the restaurant domain, plus the JSON-collection
-- documents and the IVF vector index (created here, after review rows exist).
-- Idempotent: clears the seed rows first (child-first FK order) so a re-run
-- produces the same state rather than ORA-00001 or duplicate rows.

DELETE FROM order_item;
DELETE FROM orders;
DELETE FROM address;
DELETE FROM review;
DELETE FROM menu_item;
DELETE FROM customer;
DELETE FROM restaurant;
DELETE FROM order_docs;

INSERT INTO restaurant (restaurant_id, name, cuisine, city) VALUES (1, 'Trattoria Uno', 'Italian', 'Redwood City');
INSERT INTO restaurant (restaurant_id, name, cuisine, city) VALUES (2, 'Sushi Nord', 'Japanese', 'Austin');

INSERT INTO menu_item (menu_item_id, restaurant_id, name, price, category) VALUES (10, 1, 'Margherita', 14.00, 'Pizza');
INSERT INTO menu_item (menu_item_id, restaurant_id, name, price, category) VALUES (11, 1, 'Carbonara', 17.50, 'Pasta');
INSERT INTO menu_item (menu_item_id, restaurant_id, name, price, category) VALUES (20, 2, 'Salmon Nigiri', 6.00, 'Nigiri');

INSERT INTO customer (customer_id, name, email) VALUES (100, 'Ada Lovelace', 'ada@example.com');
INSERT INTO customer (customer_id, name, email) VALUES (101, 'Alan Turing', 'alan@example.com');

INSERT INTO address (customer_id, line1, city, postal_code) VALUES (100, '1 Analytical Way', 'Redwood City', '94063');
INSERT INTO address (customer_id, line1, city, postal_code) VALUES (101, '2 Enigma Rd', 'Austin', '78701');

INSERT INTO orders (order_id, customer_id, restaurant_id, total) VALUES (1000, 100, 1, 31.50);
INSERT INTO orders (order_id, customer_id, restaurant_id, total) VALUES (1001, 101, 2, 12.00);

INSERT INTO order_item (order_id, menu_item_id, quantity, unit_price) VALUES (1000, 10, 1, 14.00);
INSERT INTO order_item (order_id, menu_item_id, quantity, unit_price) VALUES (1000, 11, 1, 17.50);
INSERT INTO order_item (order_id, menu_item_id, quantity, unit_price) VALUES (1001, 20, 2, 6.00);

INSERT INTO review (restaurant_id, customer_id, rating, body, embedding)
  VALUES (1, 100, 5, 'Best carbonara in town', TO_VECTOR('[0.90, 0.10, 0.05]'));
INSERT INTO review (restaurant_id, customer_id, rating, body, embedding)
  VALUES (1, 101, 4, 'Great pizza, cozy room', TO_VECTOR('[0.80, 0.20, 0.10]'));
INSERT INTO review (restaurant_id, customer_id, rating, body, embedding)
  VALUES (2, 100, 5, 'Fresh nigiri, fast service', TO_VECTOR('[0.10, 0.85, 0.20]'));
INSERT INTO review (restaurant_id, customer_id, rating, body, embedding)
  VALUES (2, 101, 3, 'Good but pricey', TO_VECTOR('[0.15, 0.70, 0.30]'));

-- Document projection into the JSON collection.
INSERT INTO order_docs (data) VALUES (
  JSON('{"_id": 1000, "total": 31.50, "restaurant": "Trattoria Uno",
         "items": [{"name": "Margherita", "qty": 1}, {"name": "Carbonara", "qty": 1}]}'));
INSERT INTO order_docs (data) VALUES (
  JSON('{"_id": 1001, "total": 12.00, "restaurant": "Sushi Nord",
         "items": [{"name": "Salmon Nigiri", "qty": 2}]}'));

COMMIT;

-- IVF vector index (Free default; created after rows exist).
CREATE VECTOR INDEX IF NOT EXISTS review_vec_ivf ON review (embedding)
  ORGANIZATION NEIGHBOR PARTITIONS
  DISTANCE COSINE;

SELECT o.order_id, o.total, r.name AS restaurant, oi.menu_item_id, oi.quantity
FROM orders o
JOIN restaurant r ON r.restaurant_id = o.restaurant_id
JOIN order_item oi ON oi.order_id = o.order_id
WHERE o.order_id = 1000

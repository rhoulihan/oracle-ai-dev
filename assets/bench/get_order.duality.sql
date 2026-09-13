SELECT o.data
FROM order_dv o
WHERE JSON_VALUE(o.data, '$._id' RETURNING NUMBER) = 1000

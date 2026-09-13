SELECT d.data
FROM order_docs d
WHERE JSON_VALUE(d.data, '$._id' RETURNING NUMBER) = 1000

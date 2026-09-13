# Worked example — the restaurant domain

The canonical schema and every projection ship in
[`assets/seed/`](../../../assets/seed/README.md) — load it and follow along.

## Canonical form (7 entities)
`restaurant`, `menu_item`, `customer`, `address`, `orders`, `order_item`, `review`
(see `assets/seed/01-canonical.sql`).

## Access patterns → shapes

| Access pattern | Returns | Freq | Write | Chosen shape | Why |
|---|---|---|---|---|---|
| Show an order to the customer | order + items + restaurant | high | low | **duality view** `order_dv` | multi-entity, read-mostly; one truth, both views |
| Add item to an open cart | cart + items | very high | high | **single collection** | write-hot — a duality read-time join per write is wrong |
| Store a user's preferences | user.prefs | medium | medium | **JSON collection** | single-entity, co-accessed |
| "Customers who ordered here also ordered…" | traversal | low | low | **property graph** | real graph traversal, GRAPH_TABLE |
| Semantic review search | review.body ~ query | low | low | **vector column + IVF** | similarity, offline embeddings on Free |

Each projection is a Shape Projection of the same Canonical Form — the order
document via `order_dv` (duality), the vector via the `embedding` column, the
graph via `dining_graph`. One truth, many shapes.

## The tradeoff to watch
`order_dv` is perfect for reading an order but wrong for a write-hot cart — that
pattern routes to a single collection instead. This is the break-point the
measured optimization workflow (v0.2.5) will quantify.

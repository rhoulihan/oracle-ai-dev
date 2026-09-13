<!-- Copyright (c) 2026 Oracle and/or its affiliates. -->
# Architecture & feature intake (S0 advisor)

Conduct this as a structured interview — at most three questions per turn, and
record answers into a `requirements.md` scratchpad shaped by the intake schema.
Each question notes the schema `field:` it fills and how the answer steers the
recommendation.

## 1. What are you building?
Ask for the application in one or two sentences, then classify the dominant workload.
- field: workload
- Why: OLTP, analytics, search, and RAG pull toward different shapes and features.
  A mixed workload means the recommender weighs several access patterns.

## 2. What entities does the domain have?
- field: entities
- Why: the entity set bounds the modeling work and the `entity.property` references
  used to define query results.

## 3. Which Oracle AI capabilities do you need?
Offer the menu: vector search, MongoDB-compatible API, JSON Relational Duality,
property graph, Select AI, SODA.
- field: required_features
- Why: each feature maps to a guided path and a configurator, and some combinations
  (vector via the Mongo API on Free) trigger a critique.

## 4. Where will this run?
- field: deployment
- Why: the Free container has hard limits (2 CPU / 2 GB / 12 GB data) and a few
  features behave differently there; ADB/EE lift those.

## 5. How large is the dataset?
Ask for a rough row count and typical document size.
- field: scale
- Why: sizing is sanity-checked against the 12 GB Free cap.

## 6. What is already in your stack?
- field: existing_stack
- Why: an existing MongoDB or Postgres footprint changes the migration framing.

## 7. Any latency or availability SLAs?
- field: slas
- Why: tight latency budgets push toward denormalized shapes and specific indexes.

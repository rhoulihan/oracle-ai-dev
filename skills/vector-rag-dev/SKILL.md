---
name: vector-rag-dev
description: Use when adding vector search, embeddings, semantic or hybrid search, or RAG to an app on Oracle. Offline-first — in-database ONNX embeddings and local models run entirely on the Free container.
---

# Vector search & RAG

Oracle AI Database runs the whole vector stack locally: the `VECTOR` type,
in-database ONNX embeddings, vector indexes, and chunk→embed→generate pipelines —
no cloud dependency on Free. The seeded `review.embedding` column
([`assets/seed/04-vector.sql`](../../assets/seed/04-vector.sql)) is a worked example.

## Index choice on Free
Read [vector search](references/vector-search.md): **IVF** builds with zero config
and is the Free default; **HNSW** needs `VECTOR_MEMORY_SIZE` set (the
`enable-vector-memory` configurator) within the ~2 GB cap.

## Embeddings
Load Oracle's prebuilt all-MiniLM-L12-v2 ONNX model and embed in-database with
`VECTOR_EMBEDDING()`; see [embeddings](references/embeddings.md).

## RAG
Build offline pipelines with `DBMS_VECTOR_CHAIN` (chunk, embed, generate) and
local Ollama; see [the RAG pipeline](references/rag-pipeline.md). Hybrid search
combines vector similarity with text and relational predicates in one SQL query.

## Modeling calibrations
Freshness vs recall drift, the filtered-ANN shape, hybrid-index triggers, and
when a dedicated vector store is (and is not) warranted:
[modeling calibrations](references/modeling-calibrations.md).

## Sources
- Oracle AI Vector Search User's Guide (26ai) —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/vecse/

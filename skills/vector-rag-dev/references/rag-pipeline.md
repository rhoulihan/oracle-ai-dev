# RAG pipelines (offline-first)

Build retrieval-augmented generation entirely in the database on Free.

## Ingest
`DBMS_VECTOR_CHAIN` provides the pipeline primitives:
- `UTL_TO_TEXT` — extract text from documents.
- `UTL_TO_CHUNKS` — chunk with overlap.
- `UTL_TO_EMBEDDINGS` — embed each chunk with the loaded ONNX model.
Store chunks + embeddings in a table with a `VECTOR` column and an IVF index.

## Retrieve + generate
- Retrieve: a `VECTOR_DISTANCE` similarity query (optionally hybrid with text and
  relational predicates in the same SQL).
- Generate: call a local **Ollama** model (or an external provider) with the
  retrieved context. Ollama keeps the whole loop offline.

## Hybrid search
`DBMS_HYBRID_VECTOR.SEARCH` combines vector similarity with Oracle Text — one call,
one ranked result set.

## Porting cloud RAG
Oracle's cloud RAG samples use `DBMS_CLOUD` + OCI GenAI. On Free, swap those for
the local ONNX model and Ollama — same pipeline shape, no cloud.

## Sources
- Oracle AI Vector Search User's Guide (26ai), DBMS_VECTOR_CHAIN —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/vecse/

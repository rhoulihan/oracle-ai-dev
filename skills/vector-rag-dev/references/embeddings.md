# In-database embeddings

Generate embeddings inside the database — no external API call.

## Load a model
Load Oracle's prebuilt augmented `all-MiniLM-L12-v2` ONNX model (or convert a
Hugging Face model with OML4Py) with `DBMS_VECTOR.LOAD_ONNX_MODEL`. This is a
one-time step, **not** automatic on container boot. One command does the whole
thing — download, stage, grant, load, verify — idempotently:

```bash
assets/tooling/configure/setup-embedding-model.sh <container> <pdb> <user> <password>
```

It downloads Oracle's prebuilt model, stages the `.onnx` into the container, creates
the directory object, grants the user `CREATE MINING MODEL` + `READ` on the directory,
loads it, and verifies `VECTOR_EMBEDDING()`. The download link is a rotating OCI
pre-authenticated URL; if it 404s, grab a fresh one from the stable docs entry point
(`docs.oracle.com/pls/topic/lookup?...&id=oml_ai_models_object_storage`) and pass it
as the last argument (or `ONNX_MODEL_URL`). The lower-level `load-onnx-model.sh`
loads an already-staged model dir. **External / wallet DBs (no Docker):** the
auto-installer's `docker cp` staging doesn't apply — stage the model server-side
(DBA copies the dir, or `DBMS_CLOUD` from object storage), create a directory object
over it, then run `load-onnx-model.sh` with your wallet/easy-connect connection. Until
a model is loaded, `VECTOR_EMBEDDING()` has none — embed client-side and store the `VECTOR`.

Rankings measured on the local container carry to Autonomous Database, so a
relevance result proven on Free does not need re-proving in the cloud.
Oracle's augmented all_MiniLM_L12_v2 ONNX embedding model produces
bit-identical vector search rankings on Autonomous Database 23.26.3.2.0 and
the local 26ai Free container — the same probe query returned a 0.0803
cosine-similarity margin on both, matching to four decimal places. This means
vector search rankings can be developed and validated on a local Free
container and quoted as-is for an Autonomous Database target without
re-verifying on ADB; only the data-load mechanism differs (ADB loads via
`DBMS_CLOUD.GET_OBJECT` from object storage, taking about a minute, vs. local
file load on Free).

## Embed
```sql
SELECT VECTOR_EMBEDDING(all_minilm_l12_v2 USING 'great pizza' AS data) AS v;
```
Use it inline to populate a `VECTOR` column or to embed a query at search time.

## Grants
The embedding user needs execute on the model and the `DBMS_VECTOR` package; the
configurator grants these. On the slim image Oracle Text is stripped (ORA-29833) —
use the full image for pipelines that need it.

## Local generation
For generation (not just embeddings), point `DBMS_VECTOR_CHAIN` at a local Ollama
endpoint — fully offline on the developer's machine.

## Sources
- Oracle AI Vector Search User's Guide (26ai), ONNX models —
  https://docs.oracle.com/en/database/oracle/oracle-database/26/vecse/

#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Automatically download and install Oracle's prebuilt all-MiniLM-L12-v2 ONNX
# embedding model so server-side VECTOR_EMBEDDING() works — the engine behind RAG
# and the Oracle agent-memory pattern. Downloads the model, stages it into the
# container, grants the required privileges, loads it, and verifies. Idempotent.
#
# Usage: setup-embedding-model.sh <container> <pdb> <user> <password> [model-url]
#   container  docker container running the DB   (e.g. oracle-ai-dev-db)
#   pdb        pluggable database                (e.g. FREEPDB1)
#   user       schema that will OWN the model    (e.g. plugin_dev)
#   password   that user's password
#   model-url  optional override for the download (or set ONNX_MODEL_URL)
#
# The download link is a rotating pre-authenticated OCI URL. If the default 404s,
# fetch a fresh one from the stable docs entry point and pass it as model-url:
#   https://docs.oracle.com/pls/topic/lookup?ctx=en/database/oracle/oracle-database/26/vecse&id=oml_ai_models_object_storage
#
# This installer stages the model into a container via `docker cp`. For an external /
# wallet DB (no Docker), stage the model dir server-side (DBA copy or DBMS_CLOUD from
# object storage), create a directory object, then use load-onnx-model.sh with your
# wallet/easy-connect connection instead — see vector-rag-dev/references/embeddings.md.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export OAD_NO_SQL=1  # this script never calls sql — skip SQLcl resolution
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"

# Default to Oracle's current prebuilt all_MiniLM_L12_v2 augmented model; overridable.
DEFAULT_URL="https://adwc4pm.objectstorage.us-ashburn-1.oci.customer-oci.com/p/TtH6hL2y25EypZ0-rrczRZ1aXp7v1ONbRBfCiT-BDBN8WLKQ3lgyW6RxCfIFLdA6/n/adwc4pm/b/OML-ai-models/o/all_MiniLM_L12_v2_augmented.zip"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/oracle-ai-dev"
ZIP="${CACHE}/all_MiniLM_L12_v2_augmented.zip"

# --download-only: warm the cache without a database (CI pre-flight, offline prep).
# Best-effort — exits 0 whether or not the rotating URL is currently live, so a cold,
# offline environment degrades to the one sanctioned live-test skip rather than failing.
if [ "${1:-}" = "--download-only" ]; then
  ONNX_MODEL_URL="${2:-${ONNX_MODEL_URL:-$DEFAULT_URL}}"
  mkdir -p "${CACHE}"
  if [ -s "${ZIP}" ]; then
    echo "embedding model already cached → ${ZIP}"
    exit 0
  fi
  echo "downloading embedding model → ${ZIP}"
  curl -fL -C - -o "${ZIP}" "${ONNX_MODEL_URL}" \
    && echo "cached." \
    || echo "download unavailable (rotating URL); the live test will skip honestly." >&2
  exit 0
fi

CONTAINER="${1:?usage: setup-embedding-model.sh <container> <pdb> <user> <password> [model-url]}"
PDB="${2:?pdb required (e.g. FREEPDB1)}"
USR="${3:?user required (schema that owns the model)}"
PW="${4:?password required}"
ONNX_MODEL_URL="${5:-${ONNX_MODEL_URL:-$DEFAULT_URL}}"
MODEL_NAME="${ONNX_MODEL_NAME:-ALL_MINILM_L12_V2}"
DIR_OBJ="ONNX_MODEL_DIR"
STAGE="/opt/oracle/onnx"

# --- SQL helpers (run inside the container's sqlplus) ---------------------------
sysdba() { docker exec -i "${CONTAINER}" sqlplus -S -L / as sysdba; }
asuser() { docker exec -i "${CONTAINER}" sqlplus -S -L "${USR}/${PW}@localhost:1521/${PDB}"; }

model_present() {
  local out
  out="$(printf 'SET HEAD OFF FEEDBACK OFF PAGES 0\nSELECT '\''MODEL_OK_'\'' || COUNT(*) FROM user_mining_models WHERE model_name=%s;\nEXIT\n' \
    "'${MODEL_NAME}'" | asuser 2>/dev/null)"
  sql_success "${out}" 'MODEL_OK_[1-9]'
}

# --- 0. idempotency short-circuit ----------------------------------------------
if model_present; then
  echo "embedding model ${MODEL_NAME} already loaded for ${USR} — nothing to do."
  echo "ASSERT:embedding_model:PASS"
  exit 0
fi

# --- 1. download (idempotent, resumable) ---------------------------------------
mkdir -p "${CACHE}"
if [ ! -s "${ZIP}" ]; then
  echo "downloading embedding model → ${ZIP}"
  if ! curl -fL -C - -o "${ZIP}" "${ONNX_MODEL_URL}"; then
    echo "ERROR: download failed. The pre-authenticated URL may have rotated." >&2
    echo "Get a fresh link for all_MiniLM_L12_v2_augmented.zip from:" >&2
    echo "  https://docs.oracle.com/pls/topic/lookup?ctx=en/database/oracle/oracle-database/26/vecse&id=oml_ai_models_object_storage" >&2
    echo "then re-run with it as the model-url argument (or ONNX_MODEL_URL)." >&2
    exit 1
  fi
fi

# --- 2. extract and find the .onnx ---------------------------------------------
unzip -o -q "${ZIP}" -d "${CACHE}/model" || { echo "ERROR: unzip failed" >&2; exit 1; }
ONNX_PATH="$(find "${CACHE}/model" -name '*.onnx' | head -1)"
[ -n "${ONNX_PATH}" ] || { echo "ERROR: no .onnx in the archive" >&2; exit 1; }
ONNX_FILE="$(basename "${ONNX_PATH}")"

# --- 3. stage into the container where the DB can read it -----------------------
docker exec "${CONTAINER}" mkdir -p "${STAGE}"
docker cp "${ONNX_PATH}" "${CONTAINER}:${STAGE}/${ONNX_FILE}"

# --- 4. grant the required privileges + directory object (as sysdba) ------------
sysdba <<SQL
ALTER SESSION SET CONTAINER = ${PDB};
CREATE OR REPLACE DIRECTORY ${DIR_OBJ} AS '${STAGE}';
GRANT READ ON DIRECTORY ${DIR_OBJ} TO ${USR};
GRANT CREATE MINING MODEL TO ${USR};
EXIT
SQL

# --- 5. load the model into the user's schema (idempotent) ---------------------
asuser <<SQL
SET SERVEROUTPUT ON
DECLARE n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM user_mining_models WHERE model_name = '${MODEL_NAME}';
  IF n = 0 THEN
    DBMS_VECTOR.LOAD_ONNX_MODEL('${DIR_OBJ}', '${ONNX_FILE}', '${MODEL_NAME}',
      JSON('{"function":"embedding","embeddingOutput":"embedding","input":{"input":["DATA"]}}'));
    DBMS_OUTPUT.PUT_LINE('loaded ${MODEL_NAME}');
  END IF;
END;
/
EXIT
SQL

# --- 6. verify server-side embedding actually works -----------------------------
verify() {
  local out
  out="$(printf 'SET HEAD OFF FEEDBACK OFF PAGES 0\nSELECT '\''EMBED_OK_'\'' || TO_CHAR(VECTOR_DIMENSION_COUNT(VECTOR_EMBEDDING(%s USING '\''hello world'\'' AS DATA))) FROM dual;\nEXIT\n' \
    "${MODEL_NAME}" | asuser 2>/dev/null)"
  sql_success "${out}" 'EMBED_OK_[1-9]'
}
assert embedding_model verify

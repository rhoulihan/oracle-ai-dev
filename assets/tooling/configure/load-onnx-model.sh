#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Load Oracle's prebuilt all-MiniLM-L12-v2 ONNX embedding model into the database
# so VECTOR_EMBEDDING() works fully offline. Idempotent: skips if already loaded.
# Usage: load-onnx-model.sh <sqlcl-connection> <path-to-model-dir> [onnx-file]
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "${DIR}/../../verify/lib.sh"
CONN="${1:?usage: load-onnx-model.sh <connection> <model-dir> [onnx-file]}"
MODEL_DIR="${2:?model directory containing the .onnx file is required}"
ONNX_FILE="${3:-all_MiniLM_L12_v2.onnx}"
MODEL_NAME="ALL_MINILM_L12_V2"
load() {
  local out
  out="$(echo "DECLARE n INTEGER;
BEGIN
  SELECT COUNT(*) INTO n FROM user_mining_models WHERE model_name = '${MODEL_NAME}';
  IF n = 0 THEN
    DBMS_VECTOR.LOAD_ONNX_MODEL('MODEL_DIR', '${ONNX_FILE}', '${MODEL_NAME}',
      JSON('{\"function\":\"embedding\",\"embeddingOutput\":\"embedding\",\"input\":{\"input\":[\"DATA\"]}}'));
  END IF;
END;
/
SELECT 'ONNX_OK_' || COUNT(*) AS result FROM user_mining_models
 WHERE model_name = '${MODEL_NAME}';" \
    | sql -S "${CONN}" 2>/dev/null)"
  sql_success "${out}" 'ONNX_OK_[1-9]'
}
echo "NOTE: a DIRECTORY object 'MODEL_DIR' pointing at ${MODEL_DIR} must exist and be readable by the DB."
assert onnx_model load

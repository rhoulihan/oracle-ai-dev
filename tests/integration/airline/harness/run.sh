#!/usr/bin/env bash
# Build + run all five runtime harnesses against the live airline schema, then
# check every datalayer method returns identical results. Requires: the airline
# schema loaded, and DB reachable at DB_HOST:1521/DB_SERVICE as DB_USER.
# Env: DB_USER DB_PASSWORD DB_DSN (py/node/java/dotnet), DB_HOST DB_SERVICE (go).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${TMPDIR:-/tmp}/airline_out"; mkdir -p "$OUT"
cp "$HERE/../datalayer/repository.py" "$HERE/repository.py"
cp "$HERE/../datalayer/repository.js" "$HERE/repository.js"
python3 "$HERE/main_py.py"           > "$OUT/python.json"
node   "$HERE/main_node.js"          > "$OUT/node.json"
( cd "$HERE/dotnet" && dotnet run -c Release --no-build ) > "$OUT/dotnet.json"
( cd "$HERE/java" && java -cp "target/classes:lib/*" Main ) > "$OUT/java.json"
( cd "$HERE/go" && ./harness )       > "$OUT/go.json"
python3 "$HERE/compare.py" "$OUT"

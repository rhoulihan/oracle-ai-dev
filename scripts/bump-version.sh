#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Rewrites the "version" field in every manifest listed in .version-bump.json.
set -euo pipefail
NEW="${1:?usage: bump-version.sh <new-version>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$NEW" "$ROOT" <<'PY'
import json, sys
new, root = sys.argv[1], sys.argv[2]
reg = json.load(open(f"{root}/.version-bump.json"))
for rel in reg["manifests"]:
    p = f"{root}/{rel}"
    m = json.load(open(p))
    m["version"] = new
    with open(p, "w") as f:
        json.dump(m, f, indent=2)
        f.write("\n")
    print(f"bumped {rel} -> {new}")
PY

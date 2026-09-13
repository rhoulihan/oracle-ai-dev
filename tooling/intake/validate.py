# Copyright (c) 2026 Oracle and/or its affiliates.
"""Validate an intake answer set against the shared schema.

Pure, stdlib-only. Returns a list of human-readable violation messages
(empty list == valid). This is the contract shared by the S0 advisor and
the S3 modeling skill; the deterministic recommender validates through it.
"""

WORKLOADS = {"oltp", "analytics", "mixed", "search", "rag"}
FEATURES = {"vector", "mongo_api", "duality", "graph", "select_ai", "soda"}
DEPLOYMENTS = {"free", "adb", "ee"}
WRITE_LEVELS = {"none", "low", "medium", "high"}

_REQUIRED_TOP = ("workload", "entities", "access_patterns", "required_features", "deployment")
_REQUIRED_AP = ("name", "returns", "frequency")


def validate_answers(obj) -> list:
    v = []
    if not isinstance(obj, dict):
        return ["answer set must be an object"]

    for key in _REQUIRED_TOP:
        if key not in obj:
            v.append(f"missing required field: {key}")

    if "workload" in obj and obj["workload"] not in WORKLOADS:
        v.append(f"workload {obj['workload']!r} not in {sorted(WORKLOADS)}")

    if "deployment" in obj and obj["deployment"] not in DEPLOYMENTS:
        v.append(f"deployment {obj['deployment']!r} not in {sorted(DEPLOYMENTS)}")

    if "entities" in obj and (not isinstance(obj["entities"], list) or not obj["entities"]):
        v.append("entities must be a non-empty list")

    for feat in obj.get("required_features", []) or []:
        if feat not in FEATURES:
            v.append(f"unknown required_feature: {feat}")

    scale = obj.get("scale")
    if scale is not None:
        if not isinstance(scale, dict):
            v.append("scale must be an object")
        else:
            for key in ("rows_estimate", "doc_size_kb", "doc_size_p99_kb",
                        "indexes_per_collection", "hot_set_pct"):
                val = scale.get(key)
                # bool is an int subclass — reject it explicitly
                if val is not None and (isinstance(val, bool) or not isinstance(val, (int, float))):
                    v.append(f"scale.{key} must be a number")
            basis = scale.get("sizing_basis")
            if basis is not None and not isinstance(basis, str):
                v.append("scale.sizing_basis must be a string")

    aps = obj.get("access_patterns")
    if aps is not None:
        if not isinstance(aps, list) or not aps:
            v.append("access_patterns must be a non-empty list")
        else:
            for i, ap in enumerate(aps):
                if not isinstance(ap, dict):
                    v.append(f"access_pattern[{i}] must be an object")
                    continue
                for key in _REQUIRED_AP:
                    if key not in ap:
                        v.append(f"access_pattern[{i}] ({ap.get('name', '?')}) missing {key}")
                if "returns" in ap:
                    rets = ap["returns"]
                    if not isinstance(rets, list) or not rets:
                        v.append(f"access_pattern[{i}] returns must be a non-empty list of entity.property")
                    elif not all(isinstance(r, str) for r in rets):
                        v.append(f"access_pattern[{i}] returns must be a list of entity.property strings")
                if "write" in ap and ap["write"] not in WRITE_LEVELS:
                    v.append(f"access_pattern[{i}] write {ap['write']!r} not in {sorted(WRITE_LEVELS)}")
    return v

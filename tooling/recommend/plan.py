# Copyright (c) 2026 Oracle and/or its affiliates.
"""Deterministic recommendation plan builder.

Turns a validated intake answer set into an actionable plan: guided paths,
features + configurators to run, compose profile, sizing sanity vs the Free
envelope, per-access-pattern shape strategy, and honest critique. Pure and
unit-tested — the agent narrates, this code decides.
"""

from tooling.intake.validate import validate_answers
from tooling.recommend.shapes import recommend_shape

FREE_DATA_CAP_GB = 12

# feature -> (guided-path skill, configurator script stem)
# features whose configurators call ORDS (enable-mongo-api, enable-duality-graphql)
# and therefore need the ORDS-including compose profile to be runnable/served
_ORDS_FEATURES = {"mongo_api", "duality"}

_FEATURE_MAP = {
    "vector": ("vector-rag-dev", "enable-vector-memory"),
    "mongo_api": ("mongodb-api-dev", "enable-mongo-api"),
    "duality": ("json-duality-dev", "enable-duality-graphql"),
    "graph": ("query-craft", "enable-property-graph"),
    "select_ai": ("ai-agent-dev", "enable-select-ai"),
    "soda": ("soda-dev", "enable-soda"),
}


def build_plan(answers: dict) -> dict:
    errors = validate_answers(answers)
    if errors:
        raise ValueError("invalid intake answer set: " + "; ".join(errors))

    features = list(answers.get("required_features", []))
    paths, configurators = [], ["create-plugin-user"]
    for f in features:
        path, cfg = _FEATURE_MAP[f]
        paths.append(path)
        configurators.append(cfg)

    compose_profile = "db+ords" if _ORDS_FEATURES & set(features) else "db"

    critique = []
    # Free-tier ceiling: vector/text search do not work through the Mongo API on Free.
    if "mongo_api" in features and "vector" in features and answers.get("deployment") == "free":
        critique.append(
            "Vector search does not work through the Mongo API on Free — "
            "route vector queries to native SQL (vector-rag-dev), not the Mongo API."
        )

    sizing_warnings = []
    scale = answers.get("scale") or {}
    rows = scale.get("rows_estimate", 0)
    doc_kb = scale.get("doc_size_kb", 0)
    if rows and doc_kb:
        est_gb = (rows * doc_kb) / (1024 * 1024)
        if est_gb > FREE_DATA_CAP_GB and answers.get("deployment") == "free":
            sizing_warnings.append(
                f"Estimated {est_gb:.1f} GB exceeds the Free 12 GB user-data cap "
                f"(ORA-12954); trim the dataset or move to ADB/EE."
            )
    if "vector" in features and answers.get("deployment") == "free":
        sizing_warnings.append(
            "HNSW vector indexes need VECTOR_MEMORY_SIZE set on Free (IVF is the "
            "zero-config default); the enable-vector-memory configurator handles it."
        )

    shapes = [recommend_shape(ap, answers.get("entities", []))
              for ap in answers.get("access_patterns", [])]

    return {
        "paths": paths,
        "features": features,
        "configurators": configurators,
        "compose_profile": compose_profile,
        "sizing_warnings": sizing_warnings,
        "critique": critique,
        "shapes": shapes,
    }

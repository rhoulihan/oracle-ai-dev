# Copyright (c) 2026 Oracle and/or its affiliates.
"""Deterministic per-access-pattern physical-shape recommender.

Encodes Unified Model Theory's decision rules over the three physical
strategies (umt-distill.md). Pure function: the agent gathers requirements
and narrates; this code decides, so recommendations are reproducible and
unit-testable.
"""

# The three physical strategies UMT chooses among.
JSON_COLLECTION = "json_collection"
SINGLE_COLLECTION_MULTIVALUE = "single_collection_multivalue"
RELATIONAL_DUALITY = "relational_duality"

# Verbatim UMT rules (umt-distill.md — Decision rules / honesty calibrations).
_RULE_WRITE_HOT = (
    "Duality views are read-time joins — wrong for write-heavy hot paths; "
    "keep a write-hot access pattern in a single collection."
)
_RULE_MULTI_ENTITY = (
    "When one dataset serves multiple entities to read-mostly consumers, "
    "stitch them with a duality view (a costlier read for zero write amplification)."
)
_RULE_EMBED_BOUNDED = (
    "Embed bounded/owned/co-accessed children; a single-entity, co-accessed "
    "result is a pure JSON collection."
)


def _entities_in_returns(access_pattern) -> set:
    ents = set()
    for ref in access_pattern.get("returns", []):
        ents.add(ref.split(".", 1)[0])
    return ents


def recommend_shape(access_pattern: dict, entities: list) -> dict:
    """Return {strategy, rationale, umt_rule} for one access pattern."""
    write = access_pattern.get("write", "low")
    ref_entities = _entities_in_returns(access_pattern)

    # Rule 1: a write-hot path must not pay duality's read-time join on every write.
    if write == "high":
        if len(ref_entities) >= 2:
            # Single-collection is only right if the extra entities are owned,
            # bounded children. Shared/independent entities must be referenced
            # (umt-distill.md §3.1/§3.8) — flag it rather than silently collapse.
            return {
                "strategy": SINGLE_COLLECTION_MULTIVALUE,
                "rationale": "Write is high, but this pattern touches multiple "
                             "entities — confirm the non-primary entities are "
                             "owned/bounded children before collapsing into one "
                             "collection; if any is shared or independently changing, "
                             "reference it and use a hybrid design.",
                "umt_rule": _RULE_WRITE_HOT + " Shared/independent entities must be "
                            "referenced, not embedded.",
            }
        return {
            "strategy": SINGLE_COLLECTION_MULTIVALUE,
            "rationale": "Write is high; a duality view would amplify write cost — "
                         "keep this in a single collection with a multivalue index.",
            "umt_rule": _RULE_WRITE_HOT,
        }

    # Rule 2: multiple distinct entities in the result, read-mostly -> duality view.
    if len(ref_entities) >= 2:
        return {
            "strategy": RELATIONAL_DUALITY,
            "rationale": "Result spans multiple entities and is read-mostly; a duality "
                         "view serves both relational and document consumers from one truth.",
            "umt_rule": _RULE_MULTI_ENTITY,
        }

    # Rule 3: single entity, co-accessed -> pure JSON collection.
    return {
        "strategy": JSON_COLLECTION,
        "rationale": "Single-entity, co-accessed result; embed it as a JSON collection.",
        "umt_rule": _RULE_EMBED_BOUNDED,
    }

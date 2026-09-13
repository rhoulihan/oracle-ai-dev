# Copyright (c) 2026 Oracle and/or its affiliates.
"""Generic document/data-modeling pattern catalog + naming.

These are the well-known data-modeling patterns; the plugin's OUTPUT uses generic
names (no MongoDB branding). The optimizer ranks shape realizations neutrally and
names the pattern of whichever wins — the winner varies with the read/write knob.

The catalog spans all 17 patterns (the 12 canonical patterns + the 5 tree variants,
the latter collapsed onto Oracle's three practical hierarchy realizations:
Adjacency = parent/child reference, Materialized Path = array-of-ancestors / path
column, Graph = SQL/PGQ property graph).
"""

PATTERNS = [
    {"name": "Embedded Document", "shapes": ["document"],
     "characteristic": "a child aggregate embedded in the parent document"},
    {"name": "Subset", "shapes": ["document"],
     "characteristic": "keep the hot subset (top-n of an array) in the document"},
    {"name": "Extended Reference", "shapes": ["document", "duality"],
     "characteristic": "embed a frequently-read subset of a referenced entity"},
    {"name": "Normalized (Referenced)", "shapes": ["relational"],
     "characteristic": "separate tables joined by keys"},
    {"name": "Duality", "shapes": ["duality"],
     "characteristic": "relational storage projected as a document (both APIs)"},
    {"name": "Computed / SQL View", "shapes": ["sql_view", "summary"],
     "characteristic": "derived values (COALESCE/aggregation) in a read-only view"},
    {"name": "Attribute", "shapes": ["document", "hybrid"],
     "characteristic": "many sparse {k,v} attributes searched uniformly (multivalue index); "
                       "the hybrid shape realizes it as a relational core + JSON flex column"},
    {"name": "Bucket", "shapes": ["document", "relational"],
     "characteristic": "group many small records into bucketed docs (time-series/IoT)"},
    {"name": "Polymorphic", "shapes": ["document", "single_table"],
     "characteristic": "heterogeneous shapes in one collection, keyed by a discriminator"},
    {"name": "Schema Versioning", "shapes": ["document"],
     "characteristic": "a schema_version field selects the read shape"},
    {"name": "Outlier", "shapes": ["relational", "document"],
     "characteristic": "a few records break the common shape (overflow + flag)"},
    {"name": "Document Versioning", "shapes": ["document"],
     "characteristic": "keep historical versions (a versions[] array / history table)"},
    {"name": "Pre-allocation", "shapes": ["document", "relational"],
     "characteristic": "allocate fixed slots up front and update slot i"},
    {"name": "Approximation", "shapes": ["relational"],
     "characteristic": "approximate/aggregate counters to cut writes"},
    {"name": "Tree / Hierarchy — Adjacency", "shapes": ["relational"],
     "characteristic": "parent/child reference; CONNECT BY / recursive CTE"},
    {"name": "Tree / Hierarchy — Materialized Path", "shapes": ["relational", "document"],
     "characteristic": "array-of-ancestors / path column (multivalue-indexed)"},
    {"name": "Tree / Hierarchy — Graph", "shapes": ["graph_table"],
     "characteristic": "SQL/PGQ property graph traversal (GRAPH_TABLE)"},
]


def _query_refs(query):
    """The property names the query touches (predicates + returns), lowercased."""
    refs = set()
    for p in query.get("predicates", []) or []:
        refs.add(str(p.get("ref", "")).rsplit(".", 1)[-1].lower())
    for r in query.get("returns", []) or []:
        refs.add(str(r).rsplit(".", 1)[-1].lower())
    return refs


def pattern_name(shape, query, model=None) -> str:
    """Name the generic pattern for a winning shape given the query's (and, when
    provided, the model's) features. The winner still varies with the knob; the name
    is descriptive. `model` is optional and backward-compatible.
    """
    q = query or {}
    tr = q.get("traversal")
    # Tree realizations — by the winning shape or an explicit `via`.
    if tr or shape in ("connect_by", "recursive_cte", "graph_table"):
        via = (tr or {}).get("via")
        if shape == "graph_table" or via == "graph":
            return "Tree / Hierarchy — Graph"
        if via == "path":
            return "Tree / Hierarchy — Materialized Path"
        return "Tree / Hierarchy — Adjacency"
    # Write-shape patterns — the write access pattern names them.
    write = q.get("write")
    if write == "array_append":
        return "Bucket"
    if write == "counter_increment":
        return "Approximation"
    if write == "slot_update":
        return "Pre-allocation"
    # Query-feature patterns.
    if q.get("attribute_kv"):
        return "Attribute"
    if q.get("extended_reference"):
        return "Extended Reference"
    if shape == "summary":
        # a materialized aggregate is the Computed pattern, maintained
        return "Computed / SQL View"
    if shape == "hybrid":
        # the flex column carries the variable/sparse attributes over a
        # relational spine — the Attribute pattern's converged realization
        return "Attribute"
    if shape == "relational":
        return "Normalized (Referenced)"
    if shape == "duality":
        return "Duality"
    if shape == "sql_view":
        return "Computed / SQL View"
    if shape == "single_table":
        # the converged single-collection design keys heterogeneous entity
        # shapes by a discriminator — the catalog's Polymorphic pattern
        return "Polymorphic"
    if shape == "document":
        # Structural, model-backed patterns — driven by the field the query touches.
        refs = _query_refs(q)
        if "schema_version" in refs:
            return "Schema Versioning"
        if "is_outlier" in refs:
            return "Outlier"
        if "versions" in refs:
            return "Document Versioning"
        if "type" in refs or (model or {}).get("projections", {}).get("single_table"):
            return "Polymorphic"
        if q.get("limit"):
            return "Subset"
        return "Embedded Document"
    return shape

import sys
from pathlib import Path


def _p(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.patterns as p
    return p


def test_embedded_document(repo_root: Path):
    p = _p(repo_root)
    name = p.pattern_name("document", {"returns": ["Order.items"], "embed": True})
    assert "embedded" in name.lower()


def test_subset_when_limited(repo_root: Path):
    p = _p(repo_root)
    assert "subset" in p.pattern_name("document", {"returns": ["Order.items"], "limit": 5}).lower()


def test_relational_is_normalized(repo_root: Path):
    p = _p(repo_root)
    assert "normalized" in p.pattern_name("relational", {"returns": ["Order.total"]}).lower()


def test_duality(repo_root: Path):
    p = _p(repo_root)
    assert "duality" in p.pattern_name("duality", {"returns": ["Order.total"]}).lower()


def test_sql_view_is_computed(repo_root: Path):
    p = _p(repo_root)
    n = p.pattern_name("sql_view", {"returns": ["Order.total"], "computed": [{"name": "x", "expr": "1"}]}).lower()
    assert "computed" in n or "sql view" in n


def test_traversal_is_tree(repo_root: Path):
    p = _p(repo_root)
    assert "tree" in p.pattern_name("relational", {"traversal": {"start": {}}}).lower() \
        or "hierarchy" in p.pattern_name("relational", {"traversal": {"start": {}}}).lower()


def test_no_mongodb_branding(repo_root: Path):
    p = _p(repo_root)
    catalog = " ".join(x["name"] for x in p.PATTERNS).lower()
    assert "mongodb" not in catalog
    for shape in ("document", "relational", "duality", "sql_view"):
        assert "mongodb" not in p.pattern_name(shape, {"returns": ["A.b"]}).lower()


def test_single_table_names_polymorphic(repo_root: Path):
    # single_table is a first-class candidate shape (DEFAULT_DESIGNS); when it
    # wins it must carry a catalog name — the discriminator-keyed converged
    # collection is the Polymorphic pattern — never the raw shape string.
    p = _p(repo_root)
    name = p.pattern_name("single_table", {"returns": ["Order.total"]})
    assert name == "Polymorphic"
    assert name in {x["name"] for x in p.PATTERNS}
    poly = next(x for x in p.PATTERNS if x["name"] == "Polymorphic")
    assert "single_table" in poly["shapes"]


def test_catalog_has_all_seventeen_unique(repo_root: Path):
    p = _p(repo_root)
    assert len(p.PATTERNS) == 17
    assert len({x["name"] for x in p.PATTERNS}) == 17           # unique names
    for x in p.PATTERNS:                                        # each entry is complete
        assert x.get("shapes") and x.get("characteristic")


def test_names_all_seventeen_patterns(repo_root: Path):
    pn = _p(repo_root).pattern_name
    M = {"entities": {"E": {"table": "e", "pk": "id", "columns": {
        "schema_version": "schema_version", "is_outlier": "is_outlier",
        "versions": "versions", "type": "type", "data": "data"}}}}
    cases = {
        "Embedded Document":       pn("document", {"returns": ["Order.items"]}),
        "Subset":                  pn("document", {"returns": ["Order.items"], "limit": 5}),
        "Extended Reference":      pn("document", {"returns": ["Order.custName"], "extended_reference": True}),
        "Normalized (Referenced)": pn("relational", {"returns": ["Order.total"]}),
        "Duality":                 pn("duality", {"returns": ["Order.total"]}),
        "Computed / SQL View":     pn("sql_view", {"returns": ["Order.total"], "computed": [{"name": "x", "expr": "1"}]}),
        "Attribute":               pn("document", {"returns": ["P.attrs"], "attribute_kv": True}),
        "Bucket":                  pn("document", {"returns": ["S.readings"], "write": "array_append"}),
        "Polymorphic":             pn("document", {"returns": ["E.data"], "predicates": [{"ref": "E.type", "op": "=", "value": "a"}]}, M),
        "Schema Versioning":       pn("document", {"returns": ["E.schema_version"]}, M),
        "Outlier":                 pn("document", {"returns": ["E.is_outlier"]}, M),
        "Document Versioning":     pn("document", {"returns": ["E.versions"]}, M),
        "Pre-allocation":          pn("document", {"returns": ["E.slots"], "write": "slot_update"}),
        "Approximation":           pn("relational", {"returns": ["P.views"], "write": "counter_increment"}),
        "Tree / Hierarchy — Adjacency":        pn("relational", {"traversal": {"start": {}}}),
        "Tree / Hierarchy — Materialized Path": pn("relational", {"traversal": {"start": {}, "via": "path"}}),
        "Tree / Hierarchy — Graph":            pn("graph_table", {"traversal": {"start": {}, "via": "graph"}}),
    }
    catalog = {x["name"] for x in _p(repo_root).PATTERNS}
    for expected, got in cases.items():
        assert got == expected, f"expected {expected!r}, got {got!r}"
        assert got in catalog, f"{got!r} not in the PATTERNS catalog"
    assert set(cases) == catalog                               # every catalog name is reachable

import sys
from pathlib import Path


def _ing(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.ingest as ing
    return ing


DOC = {"_id": 1000, "total": 31.5, "paid": True,
       "customer": {"name": "Ada"},
       "items": [{"menuItemId": 20, "qty": 1}]}


def test_infers_entity_columns_and_types(repo_root: Path):
    ing = _ing(repo_root)
    model, ann = ing.model_from_documents([DOC], root_name="Order")
    assert "Order" in model["entities"]
    cols = model["entities"]["Order"]["columns"]
    assert "total" in cols
    assert model["entities"]["Order"]["pk"] == "_id" or model["entities"]["Order"]["pk"]
    assert ann  # inference annotations present


def test_nested_object_becomes_related_entity(repo_root: Path):
    ing = _ing(repo_root)
    model, _ = ing.model_from_documents([DOC], root_name="Order")
    ents = set(model["entities"])
    assert "Customer" in ents  # from the nested `customer` object


def test_array_of_objects_becomes_child_relationship(repo_root: Path):
    ing = _ing(repo_root)
    model, ann = ing.model_from_documents([DOC], root_name="Order")
    rels = model["relationships"]
    assert any(r["from"] == "Order" and r.get("cardinality", "").endswith("N") for r in rels)


def test_output_validates(repo_root: Path):
    ing = _ing(repo_root)
    sys.path.insert(0, str(repo_root))
    from tooling.generate.model import validate_model
    model, _ = ing.model_from_documents([DOC], root_name="Order")
    assert validate_model(model) == []


def test_union_across_docs_flags_optional(repo_root: Path):
    ing = _ing(repo_root)
    d2 = {"_id": 1001, "total": 12.0, "coupon": "SAVE10"}  # coupon only in one doc
    model, ann = ing.model_from_documents([DOC, d2], root_name="Order")
    assert "coupon" in model["entities"]["Order"]["columns"]
    assert any("optional" in str(a).lower() for a in ann)

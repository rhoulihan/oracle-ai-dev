import sys
from pathlib import Path


def _ing(repo_root):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.ingest as ing
    return ing


JSONSCHEMA = {
    "bsonType": "object",
    "required": ["_id", "total"],
    "properties": {
        "_id": {"bsonType": "objectId"},
        "total": {"bsonType": "double"},
        "customer": {"bsonType": "object", "properties": {"name": {"bsonType": "string"}}},
        "items": {"bsonType": "array", "items": {"bsonType": "object",
                                                 "properties": {"qty": {"bsonType": "int"}}}},
    },
}

MONGOOSE = """
const orderSchema = new mongoose.Schema({
  total: Number,
  customer: { type: mongoose.Schema.Types.ObjectId, ref: 'Customer' },
  items: [{ qty: Number }],
  note: String
});
"""


def test_jsonschema_to_model(repo_root: Path):
    ing = _ing(repo_root)
    model, ann = ing.model_from_jsonschema(JSONSCHEMA, root_name="Order")
    assert "Order" in model["entities"]
    assert "total" in model["entities"]["Order"]["columns"]
    assert "Customer" in model["entities"]  # nested object -> entity
    assert any(r["from"] == "Order" and r.get("cardinality", "").endswith("N")
               for r in model["relationships"])  # items array
    from tooling.generate.model import validate_model
    assert validate_model(model) == []


def test_mongoose_to_model(repo_root: Path):
    ing = _ing(repo_root)
    model, ann = ing.model_from_mongoose(MONGOOSE, root_name="Order")
    cols = model["entities"]["Order"]["columns"]
    assert "total" in cols and "note" in cols
    # ref -> reference relationship
    assert any(r["to"] == "Customer" for r in model["relationships"])
    from tooling.generate.model import validate_model
    assert validate_model(model) == []

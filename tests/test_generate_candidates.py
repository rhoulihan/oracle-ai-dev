import json
import sys
from pathlib import Path


def _load(repo_root: Path):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    model = json.loads((repo_root / "tests/fixtures/restaurant_model.json").read_text())
    return s, model


GET_ORDER = {
    "root": "Order",
    "returns": ["Order.total", "Restaurant.name", "OrderItem.quantity"],
    "predicates": [{"ref": "Order.orderId", "op": "=", "value": 1000}],
}


def test_generate_candidates_yields_three_shapes(repo_root: Path):
    s, model = _load(repo_root)
    cands = s.generate_candidates(model, GET_ORDER)
    assert set(cands) == {"relational", "duality", "document"}
    assert all(cands.values())


def test_generated_relational_matches_handwritten_tables(repo_root: Path):
    s, model = _load(repo_root)
    gen = s.generate_candidates(model, GET_ORDER)["relational"].lower()
    hand = (repo_root / "assets/bench/get_order.relational.sql").read_text().lower()
    for tbl in ("orders", "order_item", "restaurant"):
        assert tbl in gen and tbl in hand


def test_generated_json_shapes_target_same_objects(repo_root: Path):
    s, model = _load(repo_root)
    cands = s.generate_candidates(model, GET_ORDER)
    assert "order_dv" in cands["duality"]
    assert "order_docs" in cands["document"]
    hand_dv = (repo_root / "assets/bench/get_order.duality.sql").read_text()
    hand_doc = (repo_root / "assets/bench/get_order.document.sql").read_text()
    assert "order_dv" in hand_dv and "order_docs" in hand_doc

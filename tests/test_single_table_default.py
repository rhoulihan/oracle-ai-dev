# Copyright (c) 2026 Oracle and/or its affiliates.
"""Single collection as a first-class station on the consolidation walk.

document -> single collection -> duality -> relational. For a RELATIONAL model (not just
a DynamoDB-ingested one) the single-collection design must be deployable, queryable,
aggregatable and writable, or it can't compete by default.
"""
import sys
from pathlib import Path

MODEL = {
    "entities": {
        "Order": {"table": "orders", "pk": "order_id",
                  "columns": {"total": "total", "status": "status"}},
        "Item": {"table": "items", "pk": "item_id",
                 "columns": {"order_id": "order_id", "qty": "qty"}},
    },
    "relationships": [{"from": "Order", "to": "Item", "from_key": "order_id",
                       "to_key": "order_id", "cardinality": "1:N"}],
    "projections": {},
}


def _mods(repo_root):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.sql as s
    import tooling.generate.ddl as d
    import tooling.optimize.runner as r
    return s, d, r


def test_single_table_ddl_includes_the_pk_columns(repo_root: Path):
    """The union of columns skipped each entity's PK, so the key index referenced a column
    the table didn't have. A relational model's PK must be a real column here."""
    s, d, r = _mods(repo_root)
    m = dict(MODEL, projections={"single_table": r.propose_single_table(MODEL)})
    ddl = d.generate_ddl(m, "single_table")
    create = ddl.split(";")[0]                 # the CREATE TABLE, not the indexes
    # the key index references these columns — they must EXIST on the table
    assert "order_id" in create and "item_id" in create, create
    assert "type" in create.lower()


def test_single_table_supports_aggregation(repo_root: Path):
    """A single collection is still SQL — it must be able to GROUP BY, or it gets
    excluded from every workload with a KPI pattern."""
    s, d, r = _mods(repo_root)
    m = dict(MODEL, projections={"single_table": r.propose_single_table(MODEL)})
    q = {"root": "Order", "type": "Order",
         "group_by": ["Order.status"],
         "aggregates": [{"fn": "COUNT", "ref": "*", "name": "n"}]}
    sql = s.generate_single_table(m, q).upper()
    assert "GROUP BY" in sql and "COUNT(*)" in sql


def test_single_table_supports_writes(repo_root: Path):
    """Writes are first-class rows in the cost matrix — a design that can't be written
    to is excluded from the decision entirely."""
    s, d, r = _mods(repo_root)
    m = dict(MODEL, projections={"single_table": r.propose_single_table(MODEL)})
    q = {"root": "Order", "returns": ["Order.total"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}
    upd = s.generate_update(m, q, "single_table", "Order.total", delta=1).lower()
    assert "update converged_items" in upd and "total = total + 1" in upd
    assert "type" in upd                       # scoped to the item type
    ins = s.generate_insert(m, q, "single_table").lower()
    assert "insert into converged_items" in ins and "type" in ins


def test_duality_view_renders_a_composite_child_key_as_columns(repo_root):
    """A composite PK is a LIST. Rendering it with str() leaks a Python repr into the
    DDL — `['reservation_id', 'payment_id'] : [...]` — and Oracle rejects the whole view
    (ORA-24558), silently dropping duality out of the walk. Every join table has one."""
    import sys
    sys.path.insert(0, str(repo_root))
    from tooling.generate.ddl import generate_ddl

    model = {
        "entities": {
            "Order": {"table": "orders", "pk": "order_id", "columns": {"total": "total"}},
            "OrderPayment": {"table": "order_payments", "pk": ["order_id", "payment_id"],
                             "columns": {}},
        },
        "relationships": [{"from": "Order", "to": "OrderPayment", "cardinality": "1:N",
                           "from_key": "order_id", "to_key": "order_id"}],
        "projections": {"duality": {"Order": "orders_dv"}},
    }
    ddl = generate_ddl(model, "duality")
    assert "[" not in ddl.split("CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW")[1].replace(
        "[ {", "").replace("} ]", ""), f"python list repr leaked into the DDL:\n{ddl}"
    body = ddl.split("order_payments @insert")[1]
    assert "order_id : order_id" in body and "payment_id : payment_id" in body


AGG_MODEL = {
    "entities": {
        "Order":     {"table": "orders", "pk": "order_id",
                      "columns": {"status": "status", "customer_id": "customer_id"}},
        "OrderItem": {"table": "order_items", "pk": "item_id",
                      "columns": {"order_id": "order_id", "sku": "sku", "qty": "qty"}},
        "OrderPay":  {"table": "order_pays", "pk": ["order_id", "payment_id"], "columns": {}},
        "Payment":   {"table": "payments", "pk": "payment_id",
                      "columns": {"amount": "amount"}},
        "Customer":  {"table": "customers", "pk": "customer_id",
                      "columns": {"name": "name"}},
    },
    "relationships": [
        {"from": "Order", "to": "OrderItem", "cardinality": "1:N",
         "from_key": "order_id", "to_key": "order_id"},
        {"from": "Order", "to": "OrderPay", "cardinality": "1:N",
         "from_key": "order_id", "to_key": "order_id"},
        {"from": "OrderPay", "to": "Payment", "cardinality": "N:1",
         "from_key": "payment_id", "to_key": "payment_id"},
        {"from": "Order", "to": "Customer", "cardinality": "N:1",
         "from_key": "customer_id", "to_key": "customer_id"},
    ],
}
AGG_PATTERNS = [
    {"name": "get_order", "kind": "read", "rate": 5000,
     "query": {"root": "Order",
               "returns": ["Order.status", "OrderItem.sku", "Payment.amount"],
               "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}},
]


def test_the_result_set_decides_what_co_locates(repo_root):
    """Rick's rule: the entity properties in the RESULT SET plus the filters deduce the
    keys. `get_order` returns Order + OrderItem + Payment together, so all three must key
    anchor-first — even Payment, which only reaches the anchor through a join table. The
    parent (Customer) is shared reference data and stays off-anchor."""
    import sys
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r

    st = r.propose_single_table(AGG_MODEL, AGG_PATTERNS)
    assert st["anchor"] == "Order"
    types = st["types"]
    assert types["Order"]["key"] == ["order_id"]
    assert types["OrderItem"]["key"][0] == "order_id"
    assert types["OrderPay"]["key"][0] == "order_id"
    # the far side of the M:N — co-retrieved with the anchor, so it must co-locate
    assert types["Payment"]["key"][0] == "order_id", \
        "Payment is returned with the order; it must be in the item collection"
    # a shared parent is NOT duplicated into every item collection
    assert types["Customer"]["key"] == ["customer_id"]


def test_item_collection_read_is_one_indexed_scan_not_a_type_filter(repo_root):
    """When the result set spans co-located types, the single collection must read the
    whole item collection by the ANCHOR key. Filtering on the root's discriminator alone
    returns the order row with NULL items and NULL payments — wrong answer, fast."""
    import sys
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    from tooling.generate.sql import generate_single_table

    model = r.propose_projections(AGG_MODEL, AGG_PATTERNS)
    sql = generate_single_table(model, AGG_PATTERNS[0]["query"])
    up = sql.upper()
    assert "ORDER_ID = 1" in up, f"must key on the anchor:\n{sql}"
    for t in ("'ORDER'", "'ORDERITEM'", "'PAYMENT'"):
        assert t in up, f"the item collection must include {t}:\n{sql}"
    assert "CASE WHEN" not in up, \
        f"the anchor column is shared by every co-located type — no sparse CASE:\n{sql}"


def test_the_anchor_index_exists(repo_root):
    """The single table's defining index. Every per-type key gets a SPARSE index
    (CASE WHEN type='X' THEN col END), but an item-collection read spans several types at
    once, so no sparse index can serve it — it full-scans, and the design loses the one
    read it exists to win. The anchor index (anchor_col, type) IS the DynamoDB PK+SK:
    one range scan returns the whole item collection."""
    import sys
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    from tooling.generate.ddl import generate_ddl

    model = r.propose_projections(AGG_MODEL, AGG_PATTERNS)
    ddl = generate_ddl(model, "single_table").upper()
    assert "(ORDER_ID, TYPE)" in ddl.replace('"', ""), \
        f"no anchor index — the item-collection read will full-scan:\n{ddl}"


def test_a_composite_anchor_carries_its_whole_key(repo_root):
    """An anchor with a composite key must carry EVERY key column onto its co-located
    items. Carry only the first and the item collection lands half-keyed — and the anchor
    index, which spans the full key, is never used by the read it was built for."""
    import sys
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r
    from tooling.generate.ddl import generate_ddl

    model = {
        "entities": {
            "Tenant": {"table": "tenants", "pk": ["tenant_id", "shard_id"],
                       "columns": {"name": "name"}},
            "Doc": {"table": "docs", "pk": "doc_id",
                    "columns": {"tenant_id": "tenant_id", "shard_id": "shard_id",
                                "title": "title"}},
        },
        "relationships": [{"from": "Tenant", "to": "Doc", "cardinality": "1:N",
                           "from_key": "tenant_id", "to_key": "tenant_id"}],
    }
    pats = [{"name": "t", "rate": 9,
             "query": {"root": "Tenant", "returns": ["Tenant.name", "Doc.title"],
                       "predicates": [{"ref": "Tenant.tenant_id", "op": "=", "value": 1}]}}]
    st = r.propose_single_table(model, pats)
    assert st["types"]["Doc"]["key"][:2] == ["tenant_id", "shard_id"]
    ddl = generate_ddl(r.propose_projections(model, pats), "single_table")
    assert "(tenant_id, shard_id, type)" in ddl, f"anchor index lost a key column:\n{ddl}"


def test_a_self_referencing_hierarchy_terminates(repo_root):
    """The descent follows relationships; an org chart points at itself. Terminate, or the
    derivation hangs before it ever reaches the database."""
    import sys
    sys.path.insert(0, str(repo_root))
    import tooling.optimize.runner as r

    model = {"entities": {"E": {"table": "e", "pk": "eid",
                                "columns": {"mgr": "mgr_id", "name": "name"}}},
             "relationships": [{"from": "E", "to": "E", "cardinality": "1:N",
                                "from_key": "eid", "to_key": "mgr_id"}]}
    st = r.propose_single_table(model, [{"name": "t", "rate": 9, "query": {
        "root": "E", "returns": ["E.name"],
        "predicates": [{"ref": "E.eid", "op": "=", "value": 1}]}}])
    assert st["anchor"] == "E" and st["types"]["E"]["key"] == ["eid"]

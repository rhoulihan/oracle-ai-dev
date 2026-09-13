

def test_document_id_predicate_gets_an_index(repo_root):
    """A relational PK is already indexed, so PK predicates are skipped — but the DOCUMENT
    shape filters with JSON_VALUE(data,'$._id' RETURNING NUMBER), which has NO index by
    default. Skipping it makes the document full-scan its signature pattern (the id point
    read) and systematically biases every comparison toward relational."""
    import sys; sys.path.insert(0, str(repo_root))
    from tooling.generate.ddl import generate_indexes
    model = {"entities": {"Order": {"table": "orders", "pk": "order_id",
                                    "columns": {"total": "total"}}},
             "relationships": [],
             "projections": {"document": {"Order": {"collection": "order_docs",
                                                    "id_path": "$._id"}}}}
    q = {"root": "Order", "returns": ["Order.total"],
         "predicates": [{"ref": "Order.order_id", "op": "=", "value": 1}]}

    doc = generate_indexes(model, [q], shape="document")
    assert "order_docs" in doc, "the id point-read must be indexed on the collection"
    # must match the generated predicate EXACTLY or the optimizer won't use it
    assert "JSON_VALUE(data, '$._id' RETURNING NUMBER)" in doc

    # relational still skips it — the PK is already indexed there
    rel = generate_indexes(model, [q], shape="relational")
    assert "order_id" not in rel

# Copyright (c) 2026 Oracle and/or its affiliates.
"""Reverse-engineer a ModelSpec from what a developer already has.

Each importer returns (model, annotations). `model` validates against
tooling.generate.model.validate_model; `annotations` records inferred types and
embed/reference bets for the developer to confirm/edit. Hand-authoring stays
first-class — ingestion is optional.
"""
import re


def _infer_type(v):
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        if re.match(r"^\d{4}-\d{2}-\d{2}", v):
            return "date"
        return "string"
    return "string"


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def model_from_documents(docs, root_name="Root"):
    """Infer a ModelSpec from example JSON documents (heuristic; annotated)."""
    entities, relationships, annotations = {}, [], []

    def add_entity(name, sample):
        ent = entities.setdefault(name, {"table": _snake(name), "pk": None, "columns": {}})
        for k, v in sample.items():
            if k == "_id":
                ent["pk"] = "_id"
                continue
            if isinstance(v, dict):
                child = k[:1].upper() + k[1:]
                add_entity(child, v)
                relationships.append({"from": name, "to": child, "from_key": "_id",
                                      "to_key": name.lower() + "_id", "cardinality": "N:1"})
                annotations.append(f"{name}.{k}: nested object -> entity {child} (embed candidate; confirm)")
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                child = (k[:-1] if k.endswith("s") else k)
                child = child[:1].upper() + child[1:]
                add_entity(child, v[0])
                relationships.append({"from": name, "to": child, "from_key": "_id",
                                      "to_key": name.lower() + "_id", "cardinality": "1:N"})
                annotations.append(f"{name}.{k}: array of objects -> child {child} 1:N (embed candidate; confirm)")
            else:
                ent["columns"][k] = _snake(k)
                annotations.append(f"{name}.{k}: inferred type {_infer_type(v)}"
                                   + (" (reference candidate; confirm)"
                                      if re.search(r"(_id|Id)$", k) else ""))
        if ent["pk"] is None:
            ent["pk"] = "_id"

    # Union across docs: fields absent from some docs are optional.
    all_keys = {}
    for d in docs:
        for k in d:
            all_keys[k] = all_keys.get(k, 0) + 1
        add_entity(root_name, d)
    for k, cnt in all_keys.items():
        if cnt < len(docs):
            annotations.append(f"{root_name}.{k}: optional (present in {cnt}/{len(docs)} docs)")

    return {"entities": entities, "relationships": relationships, "projections": {}}, annotations


def _strip_quotes(s):
    for q in ('"', "`", "[", "]"):
        s = s.replace(q, "")
    return s


def _split_top_level(body):
    parts, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts]


_KW = {"constraint", "primary", "foreign", "unique", "check", "key"}


def model_from_ddl(sql):
    """Parse CREATE TABLE DDL (Oracle/PostgreSQL/MySQL/SQL Server) into a ModelSpec."""
    sql = _strip_quotes(sql)
    entities, relationships, annotations = {}, [], []
    for m in re.finditer(r"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(\w+)\s*\(", sql):
        tname = m.group(1).lower()
        start = m.end() - 1  # the '('
        depth, j = 0, start
        while j < len(sql):
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        ent = {"table": tname, "pk": None, "columns": {}}
        for d in _split_top_level(sql[start + 1:j]):
            dl = d.lower().strip()
            first = dl.split()[0] if dl.split() else ""

            mpk = re.search(r"primary\s+key\s*\(\s*(\w+)\s*\)", dl)
            if "primary key" in dl and mpk:
                ent["pk"] = mpk.group(1)
            elif "primary key" in dl and first not in _KW:
                ent["pk"] = first

            mfk = re.search(r"foreign\s+key\s*\(\s*(\w+)\s*\)\s*references\s+(\w+)\s*\(\s*(\w+)\s*\)", dl)
            if mfk:
                relationships.append({"from": tname, "to": mfk.group(2), "from_key": mfk.group(1),
                                      "to_key": mfk.group(3), "cardinality": "N:1"})
                continue
            if first in _KW:
                continue  # a constraint line, not a column

            col = first
            ent["columns"][col] = col
            mref = re.search(r"\breferences\s+(\w+)\s*\(\s*(\w+)\s*\)", dl)
            if mref:
                relationships.append({"from": tname, "to": mref.group(1), "from_key": col,
                                      "to_key": mref.group(2), "cardinality": "N:1"})
                annotations.append(f"{tname}.{col}: FK -> {mref.group(1)} (N:1; confirm cardinality)")
        if ent["pk"] is None:
            ent["pk"] = next(iter(ent["columns"]), "id")
        # the pk column need not appear in columns (it's the pk); drop it from columns to avoid dupe
        ent["columns"].pop(ent["pk"], None)
        entities[tname] = ent
    return {"entities": entities, "relationships": relationships, "projections": {}}, annotations


_BSON_TYPE = {"double": "number", "int": "number", "long": "number", "decimal": "number",
              "bool": "boolean", "date": "date", "string": "string", "objectId": "string"}


def model_from_jsonschema(schema, root_name="Root"):
    """Parse a MongoDB $jsonSchema (declared types) into a ModelSpec."""
    entities, relationships, annotations = {}, [], []

    def walk(name, node):
        ent = entities.setdefault(name, {"table": _snake(name), "pk": None, "columns": {}})
        props = (node or {}).get("properties", {})
        for k, spec in props.items():
            bt = spec.get("bsonType")
            if k == "_id":
                ent["pk"] = "_id"
            elif bt == "object":
                child = k[:1].upper() + k[1:]
                walk(child, spec)
                relationships.append({"from": name, "to": child, "from_key": "_id",
                                      "to_key": name.lower() + "_id", "cardinality": "N:1"})
            elif bt == "array":
                items = spec.get("items", {})
                child = (k[:-1] if k.endswith("s") else k)
                child = child[:1].upper() + child[1:]
                if items.get("bsonType") == "object":
                    walk(child, items)
                    relationships.append({"from": name, "to": child, "from_key": "_id",
                                          "to_key": name.lower() + "_id", "cardinality": "1:N"})
            else:
                ent["columns"][k] = _snake(k)
                annotations.append(f"{name}.{k}: declared {_BSON_TYPE.get(bt, 'string')}")
        if ent["pk"] is None:
            ent["pk"] = "_id"

    walk(root_name, schema)
    return {"entities": entities, "relationships": relationships, "projections": {}}, annotations


def model_from_mongoose(js, root_name="Root"):
    """Parse a Mongoose schema definition into a ModelSpec (fields, ref, subdocs)."""
    entities = {root_name: {"table": _snake(root_name), "pk": "_id", "columns": {}}}
    relationships, annotations = [], []
    m = re.search(r"Schema\s*\(\s*\{(.*)\}\s*\)", js, re.S)
    body = m.group(1) if m else js
    # ref -> reference: `field: { ... ref: 'Model' ... }`
    for fm in re.finditer(r"(\w+)\s*:\s*\{[^}]*ref\s*:\s*['\"](\w+)['\"]", body):
        relationships.append({"from": root_name, "to": fm.group(2),
                              "from_key": _snake(fm.group(1)), "to_key": "_id", "cardinality": "N:1"})
        entities.setdefault(fm.group(2), {"table": _snake(fm.group(2)), "pk": "_id", "columns": {}})
        annotations.append(f"{root_name}.{fm.group(1)}: ref -> {fm.group(2)} (reference)")
    # array subdoc: `field: [{ ... }]`
    for am in re.finditer(r"(\w+)\s*:\s*\[\s*\{", body):
        child = am.group(1)
        child = (child[:-1] if child.endswith("s") else child)
        child = child[:1].upper() + child[1:]
        entities.setdefault(child, {"table": _snake(child), "pk": "_id", "columns": {}})
        relationships.append({"from": root_name, "to": child, "from_key": "_id",
                              "to_key": root_name.lower() + "_id", "cardinality": "1:N"})
    # scalar fields: `field: Type` (Number/String/Boolean/Date)
    for sm in re.finditer(r"(\w+)\s*:\s*(Number|String|Boolean|Date)\b", body):
        entities[root_name]["columns"][_snake(sm.group(1))] = _snake(sm.group(1))
    return {"entities": entities, "relationships": relationships, "projections": {}}, annotations


# ---- DynamoDB single-table design (NoSQL Workbench export) ----------------
_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

# Oracle reserved words that occur as DynamoDB attribute names (start, end, number,
# …) — rename to a safe form so every generated shape deploys.
_RESERVED = {
    "access", "add", "all", "alter", "and", "any", "as", "asc", "audit", "between",
    "by", "char", "check", "cluster", "column", "comment", "compress", "connect",
    "create", "current", "date", "decimal", "default", "delete", "desc", "distinct",
    "drop", "else", "end", "exclusive", "exists", "file", "float", "for", "from", "grant",
    "group", "having", "identified", "immediate", "in", "increment", "index",
    "initial", "insert", "integer", "intersect", "into", "is", "level", "like",
    "lock", "long", "maxextents", "minus", "mode", "modify", "noaudit", "nocompress",
    "not", "nowait", "null", "number", "of", "offline", "on", "online", "option",
    "or", "order", "pctfree", "prior", "privileges", "public", "raw", "rename",
    "resource", "revoke", "row", "rowid", "rownum", "rows", "select", "session",
    "set", "share", "size", "smallint", "start", "successful", "synonym", "sysdate",
    "table", "then", "to", "trigger", "uid", "union", "unique", "update", "user",
    "validate", "values", "varchar", "varchar2", "view", "whenever", "where", "with",
}


def _safe_col(name):
    return name + "_" if str(name).lower() in _RESERVED else name


def _ddb_type(value):
    s = str(value)
    if _ISO_TS.match(s):
        return "TIMESTAMP"
    if re.fullmatch(r"-?\d+", s):
        return "NUMBER"
    return "VARCHAR2(4000)"


def _ddb_val(item, k):
    v = item.get(k)
    return list(v.values())[0] if isinstance(v, dict) else v


def _key_attr_names(dm):
    ka = dm["KeyAttributes"]
    names = {ka["PartitionKey"]["AttributeName"]}
    if ka.get("SortKey"):
        names.add(ka["SortKey"]["AttributeName"])
    for g in dm.get("GlobalSecondaryIndexes", []) or []:
        gk = g["KeyAttributes"]
        names.add(gk["PartitionKey"]["AttributeName"])
        if gk.get("SortKey"):
            names.add(gk["SortKey"]["AttributeName"])
    names.add("type")
    return names


def _decompose_key(value, attrs, key_names, delimiter, prefix):
    """Split a concatenated DynamoDB key into (column, segment) pairs by matching
    each segment to a named attribute value — never reproducing the concatenation."""
    if value is None:
        return []
    out, used = [], set()
    for i, seg in enumerate(str(value).split(delimiter)):
        name = None
        for an, av in attrs.items():
            if an in key_names or an in used:
                continue
            if str(av) == seg and seg != "":
                name = an
                break
        if name is None:
            name = f"{prefix}{i}"     # a literal prefix or an unnamed collection anchor
        else:
            used.add(name)
        out.append((name, seg))
    return out


def model_from_dynamodb(dynamo, table_name=None, delimiter="#"):
    """Reverse-engineer a ModelSpec from a DynamoDB single-table design.

    Each item `type` becomes a logical entity; the concatenated PK/SK keys are
    decomposed into typed composite-key columns (matched to the item's attributes),
    and every GSI becomes a multi-column index — the string-concat 'mapping
    functions' are dropped. A `single_table` projection captures the shared physical
    layout (one table, a `type` discriminator, a composite key per type, and the
    GSI-derived indexes) so the optimizer can weigh it against relational/document.
    """
    dm = dynamo["DataModel"][0]
    key_names = _key_attr_names(dm)
    pk_attr = dm["KeyAttributes"]["PartitionKey"]["AttributeName"]
    sk_attr = (dm["KeyAttributes"].get("SortKey") or {}).get("AttributeName")
    gsis = dm.get("GlobalSecondaryIndexes", []) or []
    tname = table_name or re.sub(r"\W+", "_", (dynamo.get("ModelName") or "data")).lower()

    by_type = {}
    for it in dm.get("TableData", []) or []:
        by_type.setdefault(_ddb_val(it, "type") or "item", []).append(it)

    entities, st_types, st_indexes, annotations = {}, {}, [], []
    for t, items in by_type.items():
        rep = items[0]
        attrs = {k: _ddb_val(rep, k) for k in rep}
        pk_cols = [(_safe_col(c), s) for c, s in
                   _decompose_key(_ddb_val(rep, pk_attr), attrs, key_names, delimiter, "pk")]
        sk_cols = [(_safe_col(c), s) for c, s in
                   _decompose_key(_ddb_val(rep, sk_attr), attrs, key_names, delimiter, "sk")] if sk_attr else []
        key = [c for c, _ in pk_cols + sk_cols]

        columns, ctypes = {}, {}
        for c, seg in pk_cols + sk_cols:
            columns[c] = c
            ctypes[c] = _ddb_type(seg)
        for an, av in attrs.items():
            if an in key_names:
                continue
            columns[_safe_col(an)] = _safe_col(an)
            ctypes[_safe_col(an)] = _ddb_type(av)

        entities[t] = {"table": _snake(t) + ("" if t.endswith("s") else "s"),
                       "pk": key if len(key) != 1 else key[0],
                       "columns": columns, "column_types": ctypes}
        st_types[t] = {"key": key}

        for g in gsis:
            gk = g["KeyAttributes"]
            gpk, gsk = gk["PartitionKey"]["AttributeName"], (gk.get("SortKey") or {}).get("AttributeName")
            if _ddb_val(rep, gpk) is None:
                continue  # this item type does not participate in this GSI
            gcols = _decompose_key(_ddb_val(rep, gpk), attrs, key_names, delimiter, "g")
            if gsk:
                gcols += _decompose_key(_ddb_val(rep, gsk), attrs, key_names, delimiter, "g")
            st_indexes.append({"name": f"{_snake(t)}_{g['IndexName']}".lower(),
                               "type": t, "columns": [_safe_col(c) for c, _ in gcols],
                               "source_gsi": g["IndexName"]})

    unmatched = {t: [c for c in st_types[t]["key"] if c.startswith(("pk", "sk"))]
                 for t in st_types}
    unmatched = {t: cols for t, cols in unmatched.items() if cols}
    if unmatched:
        annotations.append(f"confirm the meaning of unnamed key segments (collection "
                           f"anchors / literal prefixes): {unmatched}")
    annotations.append("types inferred from sample values (TIMESTAMP/NUMBER/VARCHAR2); confirm.")
    annotations.append("relationships between item types are implicit in shared keys; "
                       "confirm which types co-locate (item collections).")

    model = {"entities": entities, "relationships": [],
             "projections": {"single_table": {"table": tname, "discriminator": "type",
                                              "types": st_types, "indexes": st_indexes}}}
    return model, annotations

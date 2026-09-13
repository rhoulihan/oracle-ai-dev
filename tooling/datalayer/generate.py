# Copyright (c) 2026 Oracle and/or its affiliates.
"""Generate a parameterized (bound) query per shape — the SQL half of the data
layer. Each access pattern's predicate values become bind variables, so the
generated method is reusable with different inputs and never inlines a literal.

The relational family reuses the shape generators unchanged (a Bind sentinel makes
_render_value emit a placeholder). The JSON shapes (document/duality) build the
query here so non-id path predicates use the PASSING clause — a bind cannot sit
inside a JSON path string, it must be passed in and referenced as $VAR.
"""
from tooling.generate.ddl import (agg_expr, dot_pred_expr, duality_paths,
                                  json_value_expr, select_duality_view)
from tooling.generate.model import is_array_prop
from tooling.generate.sql import (_agg_projection, _check, _col, _group_by_clause,
                                   _is_nested_path, _limit_clause, _norm_op,
                                   _render_value, generate_relational,
                                   generate_sql_view, is_aggregate)


class Bind:
    """A predicate value replaced by a bind placeholder named `bind_name`."""
    __slots__ = ("bind_name",)

    def __init__(self, name):
        self.bind_name = name


def _walk_binds(query):
    """Return (bound_query, binds): every predicate value replaced by Bind
    sentinel(s), and the ordered bind descriptors [{name, ref, op}]."""
    binds, preds, i = [], [], 0
    for p in query.get("predicates", []) or []:
        op = _norm_op(p.get("op", "="))
        np = dict(p)
        if op in ("IS NULL", "IS NOT NULL"):
            preds.append(np)
            continue
        if op == "IN":
            names = []
            for _ in p["value"]:
                nm = f"b{i}"; i += 1
                names.append(Bind(nm))
                binds.append({"name": nm, "ref": p["ref"], "op": op})
            np["value"] = names
        elif op == "BETWEEN":
            lo, hi = f"b{i}", f"b{i + 1}"; i += 2
            np["value"] = [Bind(lo), Bind(hi)]
            binds += [{"name": lo, "ref": p["ref"], "op": op},
                      {"name": hi, "ref": p["ref"], "op": op}]
        else:
            nm = f"b{i}"; i += 1
            np["value"] = Bind(nm)
            binds.append({"name": nm, "ref": p["ref"], "op": op})
        preds.append(np)
    bq = dict(query)
    bq["predicates"] = preds
    return bq, binds


def _pathvar(bind):
    return bind.bind_name.upper()  # PASSING alias / $VAR name


def _bound_json_cond(prop, op, val, id_path, is_pk, path=None, pk_expr=None,
                     dot=False):
    p = path or f"$.{prop}"
    if op == "IS NULL":
        return f"NOT JSON_EXISTS(d.data, '{p}')"
    if op == "IS NOT NULL":
        return f"JSON_EXISTS(d.data, '{p}')"
    # DOT NOTATION FIRST for a flat document scalar: `d.data.f = :b0` is served
    # by the same multivalue index the Mongo lane uses — and takes a PLAIN bind
    # on the RHS. The old JSON_EXISTS(...PASSING) form for a flat scalar could
    # use none of our indexes: the bound app query full-scanned exactly where
    # the optimizer's literal query was indexed.
    if dot and not is_pk and not _is_nested_path(p):
        expr = dot_pred_expr(prop)
        if op == "IN":
            return f"{expr} IN (" + ", ".join(f":{b.bind_name}" for b in val) + ")"
        if op == "BETWEEN":
            return f"{expr} BETWEEN :{val[0].bind_name} AND :{val[1].bind_name}"
        return f"{expr} {op} :{val.bind_name}"
    if is_pk:
        # A plain SQL comparison over JSON_VALUE — the bind works inline. The expression
        # is typed from the DECLARED pk by the caller (hardcoded RETURNING NUMBER made a
        # VARCHAR2 pk read NULL and match nothing), and IN/BETWEEN keep their list
        # rendering — handing the Bind list to the scalar renderer inlined a Python repr.
        if op == "IN":
            return f"{pk_expr} IN (" + ", ".join(_render_value(b) for b in val) + ")"
        if op == "BETWEEN":
            return f"{pk_expr} BETWEEN {_render_value(val[0])} AND {_render_value(val[1])}"
        return f"{pk_expr} {op} {_render_value(val)}"
    # A duality view relocates a nested parent's FK (ORA-40609) — filter the PARENT
    # step, exactly as _render_predicate_json does; the flat path does not exist in
    # the document and silently matches zero rows.
    if _is_nested_path(p):
        parent, _, leaf = p.rpartition(".")
        at = f"@.{leaf}"
    else:
        parent, at = p, "@"
    if op == "IN":
        clauses = []
        for b in val:
            v = _pathvar(b)
            clauses.append(f"JSON_EXISTS(d.data, '{parent}?({at} == ${v})' "
                           f'PASSING :{b.bind_name} AS "{v}")')
        return "(" + " OR ".join(clauses) + ")"
    if op == "BETWEEN":
        lo, hi = val
        vl, vh = _pathvar(lo), _pathvar(hi)
        return (f"JSON_EXISTS(d.data, '{parent}?({at} >= ${vl} && {at} <= ${vh})' "
                f'PASSING :{lo.bind_name} AS "{vl}", :{hi.bind_name} AS "{vh}")')
    jop = "==" if op == "=" else ("!=" if op in ("!=", "<>") else op)
    v = _pathvar(val)
    return (f"JSON_EXISTS(d.data, '{parent}?({at} {jop} ${v})' "
            f'PASSING :{val.bind_name} AS "{v}")')


def _bound_json(model, query, target, id_path, paths=None, dot=False):
    root = query["root"]
    pk = model["entities"][root]["pk"]
    conds = []
    for p in query.get("predicates", []) or []:
        ent, prop = p["ref"].split(".", 1)
        is_pk = (ent == root and _col(model, p["ref"]) == pk)
        path = None if is_pk else (paths or {}).get(p["ref"])
        pk_expr = json_value_expr(model, ent, prop, path=id_path) if is_pk else None
        # an ARRAY property is a CONTAINS question — it stays JSON_EXISTS, which
        # the multivalue index serves; dot-first applies to flat SCALARS only
        d = dot and not is_array_prop(model, ent, prop, query)
        conds.append(_bound_json_cond(prop, _norm_op(p.get("op", "=")),
                                      p.get("value"), id_path, is_pk, path=path,
                                      pk_expr=pk_expr, dot=d))
    where = ("\nWHERE " + " AND ".join(conds)) if conds else ""

    # Aggregation and ORDER BY/LIMIT mirror _json_query (sql.py) — dropping them
    # made a KPI method return every raw document. agg_expr is the same helper the
    # index generator uses, so the two cannot drift apart.
    if is_aggregate(query):
        def col_of(ref, numeric=False):
            return agg_expr(model, ref, "document", numeric=numeric)
        return (f"SELECT {', '.join(_agg_projection(query, col_of))}\n"
                f"FROM {target} d{where}" + _group_by_clause(query, col_of))

    ob = ""
    if query.get("order_by"):
        parts = []
        for o in query["order_by"]:
            ent, prop = o["ref"].split(".", 1)
            expr = json_value_expr(model, ent, prop, path=(paths or {}).get(o["ref"]))
            parts.append(f"{expr} {str(o.get('dir', 'ASC')).upper()}")
        ob = "\nORDER BY " + ", ".join(parts)
    return f"SELECT d.data\nFROM {target} d{where}{ob}" + _limit_clause(query)


def bound_sql(model, query, shape):
    """Return (sql, binds) for one access pattern against a physical `shape`."""
    _check(model, query)
    bq, binds = _walk_binds(query)
    if shape == "relational":
        return generate_relational(model, bq), binds
    if shape == "hybrid":
        # the hybrid generator renders bind sentinels through the same value
        # renderer as every other lane — flex dot predicates bind as :bN
        from tooling.generate.sql import generate_hybrid
        return generate_hybrid(model, bq), binds
    if shape == "summary":
        from tooling.generate.sql import generate_summary
        return generate_summary(model, bq), binds
    if shape == "sql_view":
        return generate_sql_view(model, bq), binds
    if shape == "duality":
        # `projections.duality[root]` is a LIST of views (or a string) — resolve the
        # leanest view exactly as generate_duality does; interpolating the raw entry
        # put a Python repr straight into the FROM clause (see _dual_or_doc in sql.py).
        view = select_duality_view(model, bq)
        if not view:
            raise ValueError(f"no duality view can answer a query rooted at {query['root']!r}")
        return _bound_json(model, bq, view["view"], "$._id",
                           paths=duality_paths(model, bq["root"], view)), binds
    if shape == "document":
        doc = ((model.get("projections") or {}).get("document") or {}).get(query["root"])
        if not doc:
            raise ValueError(f"no document projection for {query['root']!r}")
        return _bound_json(model, bq, doc["collection"], doc.get("id_path", "$._id"),
                           dot=True), binds
    raise ValueError(f"unknown shape: {shape!r}")

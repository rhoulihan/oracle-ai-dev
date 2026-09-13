# Copyright (c) 2026 Oracle and/or its affiliates.
"""Generate the SQL for one query-result set against each physical shape.

Pure functions of a validated ModelSpec + QuerySpec. Identifiers come only from
the validated model; predicate values are rendered safely (numbers inline,
strings single-quote-escaped). Raises ValueError on an invalid spec or an
unreachable entity — never emits broken SQL silently.
"""
import re
from collections import deque

from tooling.generate.ddl import (json_value_expr, dot_pred_expr, dot_typed_expr,
                                  duality_paths, select_duality_view, agg_expr)
from tooling.generate.model import (duality_supports, hybrid_flex_props,
                                    is_array_prop, summary_mv_for,
                                    validate_model, validate_query)


def _check(model, query):
    errs = validate_model(model) + validate_query(query, model)
    if errs:
        raise ValueError("invalid spec: " + "; ".join(errs))


def _entities_referenced(query):
    # Every clause that names an entity.property must pull its entity into the JOINs —
    # returns and predicates alone left a non-root GROUP BY / aggregate / ORDER BY ref
    # naming an alias that was never introduced (ORA-00904 at execution).
    refs = list(query.get("returns", [])) + [p["ref"] for p in query.get("predicates", [])]
    refs += list(query.get("group_by") or [])
    refs += [a["ref"] for a in query.get("aggregates") or [] if a.get("ref", "*") != "*"]
    refs += [o["ref"] for o in query.get("order_by") or []]
    return {r.split(".", 1)[0] for r in refs} | {query["root"]}


def _join_paths(model, root, targets):
    """BFS the relationship graph from root; return {entity: (parent, rel)} or raise
    if a target is unreachable."""
    adj = {}
    for r in model.get("relationships", []):
        adj.setdefault(r["from"], []).append((r["to"], r))
        adj.setdefault(r["to"], []).append((r["from"], {
            "from": r["to"], "to": r["from"], "from_key": r["to_key"],
            "to_key": r["from_key"], "cardinality": r.get("cardinality")}))
    parent = {root: None}
    q = deque([root])
    while q:
        cur = q.popleft()
        for nxt, rel in adj.get(cur, []):
            if nxt not in parent:
                parent[nxt] = (cur, rel)
                q.append(nxt)
    for t in targets:
        if t not in parent:
            raise ValueError(f"entity {t!r} is not reachable from root {root!r} via relationships")
    return parent


def _col(model, ref):
    ent, prop = ref.split(".", 1)
    e = model["entities"][ent]
    return prop if prop == e["pk"] else e["columns"][prop]


def _render_value(v):
    # A bind sentinel (anything with a .bind_name) renders as a placeholder rather
    # than an inlined literal — this is how the data-layer generator parameterizes.
    bn = getattr(v, "bind_name", None)
    if bn is not None:
        return ":" + bn
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


_ALLOWED_OPS = {"=", "!=", "<>", "<", "<=", ">", ">=", "LIKE",
                "IN", "BETWEEN", "IS NULL", "IS NOT NULL"}


def _norm_op(op):
    o = str(op).strip().upper()
    if o not in _ALLOWED_OPS:
        raise ValueError(f"unsupported predicate operator: {op!r}")
    return o


def _render_predicate_sql(col, op, value):
    """A relational/sql_view WHERE condition for one predicate."""
    o = _norm_op(op)
    if o in ("IS NULL", "IS NOT NULL"):
        return f"{col} {o}"
    if o == "IN":
        return f"{col} IN ({', '.join(_render_value(v) for v in value)})"
    if o == "BETWEEN":
        return f"{col} BETWEEN {_render_value(value[0])} AND {_render_value(value[1])}"
    return f"{col} {o} {_render_value(value)}"


def _render_json_path_value(v):
    """A value literal inside a JSON path filter: strings are DOUBLE-quoted (JSON path
    syntax, and safe inside the single-quoted SQL string), numbers/bools rendered bare.
    (SQL single-quoted literals would both break the outer string and be invalid JSON
    path.)"""
    bn = getattr(v, "bind_name", None)
    if bn is not None:
        return ":" + bn
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _is_nested_path(path):
    """`$.passenger.passenger_id` and `$.legs[*].flight_number` are nested; `$.status` is not.
    Only the nested ones need the JSON_EXISTS treatment."""
    body = path[2:] if path.startswith("$.") else path
    return "." in body or "[" in body


def _render_predicate_json(model, ent, prop, op, value, id_path, is_pk, path=None,
                           is_array=False, dot=False):
    """A JSON (document/duality) WHERE condition for one predicate.

    DOT NOTATION FIRST (`dot=True`, the document lane): a flat scalar renders as
    plain `d.data.prop` — it compiles to a JSON_VALUE(... TYPE(STRICT)) recheck
    over the multivalue index access, the same semantics the Mongo API uses, so
    the SQL predicate and a Mongo find() share ONE multivalue index (the one the
    index generator now derives). JSON_VALUE RETURNING is the last resort, kept
    where its evidence lives: the `_id` point read (typed scalar ids against a
    functional index, measured 321us) and the duality lane (`dot=False`), whose
    base-column rewrite was measured on these forms. JSON_EXISTS stays what it
    always was here: the CONTAINS operator for arrays and the nested-path form
    a duality view rewrites onto base-table B-trees (measured 43x).
    """
    o = _norm_op(op)
    if is_pk and o not in ("IS NULL", "IS NOT NULL"):
        # Typed from the DECLARED pk (json_value_expr -> json_returning), not hardcoded
        # NUMBER: RETURNING NUMBER on a VARCHAR2 code like 'LAX' is NULL under the default
        # NULL ON ERROR, so every id read silently returned zero rows. And the fast path
        # must still route IN/BETWEEN through the list renderers — handing the whole list
        # to the scalar renderer emitted `IN '[1, 2]'` (invalid SQL).
        expr = json_value_expr(model, ent, prop, path=id_path)
        if o == "IN":
            return f"{expr} IN (" + ", ".join(_render_value(v) for v in value) + ")"
        if o == "BETWEEN":
            return f"{expr} BETWEEN {_render_value(value[0])} AND {_render_value(value[1])}"
        return f"{expr} {o} {_render_value(value)}"
    p = path or f"$.{prop}"

    # An ARRAY property is a CONTAINS question, not an equality question. JSON_VALUE returns
    # NULL for an array, so the indexable-scalar form would match nothing at all — and a
    # multivalue index over `$.tags[*]` is what serves this anyway.
    if is_array and o not in ("IS NULL", "IS NOT NULL"):
        jop = {"=": "==", "!=": "!=", "<>": "!="}.get(o, o)
        if o == "IN":
            inner = " || ".join(f"@ == {_render_json_path_value(v)}" for v in value)
        elif o == "BETWEEN":
            inner = (f"@ >= {_render_json_path_value(value[0])} "
                     f"&& @ <= {_render_json_path_value(value[1])}")
        else:
            inner = f"@ {jop} {_render_json_path_value(value)}"
        return f"JSON_EXISTS(d.data, '{p}?({inner})')"

    # A NESTED path in a duality view must be JSON_EXISTS, not JSON_VALUE.
    #
    # A duality view is a projection OVER TABLES, and Oracle rewrites a JSON_EXISTS path
    # predicate back onto the base columns — where the B-tree is. JSON_VALUE on a nested path
    # it does NOT rewrite, and the view full-scans. Measured on the airline capstone at 100k
    # reservations, filtering a nested parent's key: JSON_VALUE 14,292us FULL SCAN against
    # JSON_EXISTS 332us INDEXED. Forty-three times.
    #
    # Note this is the OPPOSITE of a document collection, where JSON_VALUE matches the
    # functional index and JSON_EXISTS cannot use it (see _render_predicate_json's caller and
    # tests/test_document_indexable.py). Same syntax, same engine, opposite answers. A flat
    # root path stays JSON_VALUE either way — it already reaches the index.
    if _is_nested_path(p) and o not in ("IS NULL", "IS NOT NULL"):
        parent, _, leaf = p.rpartition(".")
        jop = {"=": "==", "!=": "!=", "<>": "!="}.get(o, o)
        if o == "IN":
            inner = " || ".join(f"@.{leaf} == {_render_json_path_value(v)}" for v in value)
        elif o == "BETWEEN":
            inner = (f"@.{leaf} >= {_render_json_path_value(value[0])} "
                     f"&& @.{leaf} <= {_render_json_path_value(value[1])}")
        else:
            inner = f"@.{leaf} {jop} {_render_json_path_value(value)}"
        return f"JSON_EXISTS(d.data, '{parent}?({inner})')"
    # NULL-ness is a question about the KEY, not the value — JSON_EXISTS is the right tool,
    # and there is no index to miss.
    if o == "IS NULL":
        return f"NOT JSON_EXISTS(d.data, '{p}')"
    if o == "IS NOT NULL":
        return f"JSON_EXISTS(d.data, '{p}')"
    if dot:
        expr = dot_pred_expr(prop)
        if o == "IN":
            return f"{expr} IN (" + ", ".join(_render_value(v) for v in value) + ")"
        if o == "BETWEEN":
            return f"{expr} BETWEEN {_render_value(value[0])} AND {_render_value(value[1])}"
        return f"{expr} {o} {_render_value(value)}"
    expr = json_value_expr(model, ent, prop, path=p)
    if o == "IN":
        return f"{expr} IN (" + ", ".join(_render_value(v) for v in value) + ")"
    if o == "BETWEEN":
        return f"{expr} BETWEEN {_render_value(value[0])} AND {_render_value(value[1])}"
    return f"{expr} {o} {_render_value(value)}"


# Reserved words that could plausibly be entity names — aliasing to these breaks SQL.
_RESERVED = {
    "order", "user", "group", "date", "table", "level", "row", "rows", "size",
    "mode", "start", "end", "comment", "access", "session", "number", "char",
    "view", "index", "column", "value", "values", "type", "option", "default",
    "cluster", "current", "resource", "audit", "check", "case",
}


def _alias(entity):
    a = entity.lower()
    return a + "_t" if a in _RESERVED else a


def _computed_entities(model, query):
    """Entities a computed expression references by ALIAS (`restaurant.name`,
    `order_t.total`) — they must be JOINed like any other reference. Appended to the
    SELECT without this, the alias is never introduced and the query dies with
    ORA-00904 at execution."""
    exprs = [str(c.get("expr", "")) for c in query.get("computed") or []]
    if not exprs:
        return set()
    by_alias = {_alias(e): e for e in model.get("entities") or {}}
    ents = set()
    for expr in exprs:
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_$#]*)\s*\.", expr):
            ent = by_alias.get(m.group(1).lower())
            if ent:
                ents.add(ent)
    return ents


def _from_join_where(model, query, table_of=None, cond_of=None):
    """Shared FROM/JOIN/WHERE clause for the relational family (relational,
    sql_view, hybrid). `table_of(ent_spec)` overrides the physical table name
    (the hybrid lane's `_h` tables); `cond_of(pred)` overrides predicate
    rendering (the hybrid lane's flex dot conditions)."""
    root = query["root"]
    tbl = table_of or (lambda e: e["table"])
    targets = _entities_referenced(query) | _computed_entities(model, query)
    parent = _join_paths(model, root, targets)
    # Every entity on the path from root to a referenced entity must be joined,
    # including intermediates not themselves in the results — else a JOIN would
    # reference an alias that was never introduced.
    needed = set()
    for t in targets:
        cur = t
        while cur != root:
            needed.add(cur)
            cur = parent[cur][0]
    ents = model["entities"]
    lines = [f"FROM {tbl(ents[root])} {_alias(root)}"]
    for ent in [e for e in _bfs_order(model, root) if e in needed and e != root]:
        _p, rel = parent[ent]
        if rel["to"] == ent:
            left, lkey, rkey = rel["from"], rel["from_key"], rel["to_key"]
        else:
            left, lkey, rkey = rel["to"], rel["to_key"], rel["from_key"]
        lines.append(f"JOIN {tbl(ents[ent])} {_alias(ent)} "
                     f"ON {_alias(left)}.{lkey} = {_alias(ent)}.{rkey}")
    preds = query.get("predicates", [])
    if preds:
        conds = [(cond_of(p) if cond_of else _render_predicate_sql(
            f"{_alias(p['ref'].split('.', 1)[0])}.{_col(model, p['ref'])}",
            p.get("op", "="), p.get("value"))) for p in preds]
        lines.append("WHERE " + " AND ".join(conds))
    return "\n".join(lines)


def _validated_computed(query):
    """Developer-provided derived expressions (COALESCE, CASE, arithmetic). Light
    guard against statement-terminator/comment injection."""
    out = []
    for c in query.get("computed", []) or []:
        expr = str(c.get("expr", ""))
        if ";" in expr or "--" in expr:
            raise ValueError(f"unsafe computed expression: {expr!r}")
        out.append({"name": c["name"], "expr": expr})
    return out


def _order_by_clause(model, query):
    ob = query.get("order_by")
    if not ob:
        return ""
    parts = []
    for o in ob:
        d = str(o.get("dir", "ASC")).upper()
        if d not in ("ASC", "DESC"):
            raise ValueError(f"invalid sort direction: {o.get('dir')!r}")
        parts.append(f"{_alias(o['ref'].split('.', 1)[0])}.{_col(model, o['ref'])} {d}")
    return "\nORDER BY " + ", ".join(parts)


def _limit_clause(query):
    n = query.get("limit")
    return f"\nFETCH FIRST {int(n)} ROWS ONLY" if n else ""


# --- aggregation (the KPI / reporting pattern class) ---------------------------
# A document CAN aggregate on Oracle (SQL/JSON over the collection) but must full-scan
# to do it; a duality view cannot express an aggregation at all and must stay updatable.
# That asymmetry is exactly what anchors the converged model, so the generator has to be
# able to express it.
_ALLOWED_AGG = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


def _agg_fn(a):
    fn = str(a.get("fn", "")).strip().upper()
    if fn not in _ALLOWED_AGG:
        raise ValueError(f"unsupported aggregate function: {a.get('fn')!r}")
    return fn


def is_aggregate(query):
    return bool(query.get("group_by") or query.get("aggregates"))


# SUM/AVG are numeric-only: in a document shape their argument must be typed, because
# JSON_VALUE returns VARCHAR2 by default and summing that coerces (or raises).
_NUMERIC_AGG = {"SUM", "AVG"}


def _agg_projection(query, col_of):
    """SELECT list for an aggregation: the GROUP BY keys, then the aggregate functions.
    `col_of(ref, numeric)` renders a reference in the target shape's dialect."""
    parts = [f"{col_of(ref, False)} AS {ref.split('.', 1)[1]}"
             for ref in query.get("group_by", [])]
    for a in query.get("aggregates", []) or []:
        fn = _agg_fn(a)
        arg = "*" if a.get("ref", "*") == "*" else col_of(a["ref"], fn in _NUMERIC_AGG)
        parts.append(f"{fn}({arg}) AS {a['name']}")
    return parts


def _group_by_clause(query, col_of):
    keys = [col_of(ref, False) for ref in query.get("group_by", [])]
    return ("\nGROUP BY " + ", ".join(keys)) if keys else ""


def _child_branches(model, query):
    """The root's child COLLECTIONS referenced by this query's returns, each with the path
    that reaches it -> {first_hop_entity: [(entity, rel), ...]}.

    A "branch" is one 1:N line out of the root — the legs, the payments. Two branches in one
    query is a FAN TRAP: joined naively they cross-product (3 legs x 2 payments = 6 rows, the
    reservation repeated six times, every payment repeated once per leg). That is not the
    aggregate the query asked for, and it costs MORE to produce than the right answer does.
    """
    root = query.get("root")
    rels = model.get("relationships", [])
    want = {r.split(".", 1)[0] for r in (query.get("returns") or []) if "." in r} - {root}
    if not root or not want:
        return {}

    branches = {}
    for r in rels:                                        # first hop: a 1:N child of the root
        if r["from"] != root or (r.get("cardinality") or "1:N").upper() not in ("1:N", "1:1"):
            continue
        hop = r["to"]
        members = [(hop, r)]
        for r2 in rels:                                   # second hop: the far side of an M:N
            card2 = (r2.get("cardinality") or "1:N").upper()
            far = None
            if r2["to"] == hop and card2 in ("1:N", "1:1") and r2["from"] != root:
                far = r2["from"]
            elif r2["from"] == hop and card2 == "N:1" and r2["to"] != root:
                far = r2["to"]
            if far:
                members.append((far, r2))
        if want & {m for m, _ in members}:
            branches[hop] = members
    return branches


def _branch_subquery(model, query, hop, members, table_of=None, col_of=None,
                     cond_of=None):
    """One correlated JSON_ARRAYAGG per child collection — gathered independently, so the
    branches never multiply each other. `table_of`/`col_of`/`cond_of` override
    the physical table name, the value expression, and predicate rendering
    (the hybrid lane); defaults are the plain relational forms."""
    root = query["root"]
    re_ = model["entities"][root]
    root_pk = re_["pk"][0] if isinstance(re_["pk"], list) else re_["pk"]
    ra = _alias(root)
    tbl = table_of or (lambda e: e["table"])

    want = {r.split(".", 1)[0] for r in query["returns"] if "." in r}
    pairs, froms, conds, prev_alias, prev_ent = [], [], [], None, None
    for ent, rel in members:
        e = model["entities"][ent]
        a = _alias(ent)
        if prev_alias is None:
            froms.append(f"{tbl(e)} {a}")
            link = rel.get("to_key") or root_pk
            conds.append(f"{a}.{link} = {ra}.{root_pk}")
        else:
            # Join the far side on ITS OWN key. rel links `ent` (the far table) to the
            # junction `prev_ent`, spelled either far-1:N-junction or junction-N:1-far.
            # One key name applied to both tables only worked while every fixture happened
            # to use identical names on both sides (flights has no leg_id — ORA-00904).
            if rel["to"] == prev_ent:
                far_k, junc_k = rel["from_key"], rel["to_key"]
            else:
                far_k, junc_k = rel["to_key"], rel["from_key"]
            froms.append(f"JOIN {tbl(e)} {a} ON {a}.{far_k} = {prev_alias}.{junc_k}")
        # A predicate on a branch member filters this branch's rows — dropping it
        # aggregated EVERY child, filtered or not.
        for p in query.get("predicates", []) or []:
            if p["ref"].split(".", 1)[0] == ent:
                conds.append(cond_of(p) if cond_of else _render_predicate_sql(
                    f"{a}.{_col(model, p['ref'])}", p.get("op", "="), p.get("value")))
        if ent in want:
            for ref in query["returns"]:
                if ref.split(".", 1)[0] == ent:
                    prop = ref.split(".", 1)[1]
                    val = col_of(a, ref) if col_of else f"{a}.{_col(model, ref)}"
                    pairs.append(f"'{prop}' VALUE {val}")
        prev_alias, prev_ent = a, ent

    obj = f"JSON_OBJECT({', '.join(pairs)} RETURNING JSON)"
    return (f"  (SELECT JSON_ARRAYAGG({obj} RETURNING JSON)\n"
            f"   FROM {' '.join(froms)}\n"
            f"   WHERE {' AND '.join(conds)}) AS {hop.lower()}s")


def generate_relational(model, query, table_of=None) -> str:
    _check(model, query)
    if is_aggregate(query):
        def col_of(ref, numeric=False):
            return f"{_alias(ref.split('.', 1)[0])}.{_col(model, ref)}"
        return (f"SELECT {', '.join(_agg_projection(query, col_of))}\n"
                + _from_join_where(model, query, table_of=table_of)
                + _group_by_clause(query, col_of)
                + _order_by_clause(model, query) + _limit_clause(query))
    computed = _validated_computed(query)

    # THE FAN TRAP. Two independent child collections in one query cross-product: 3 legs x 2
    # payments = 6 rows, the reservation repeated six times. Gather each branch in its own
    # correlated subquery instead — one row, the right answer, and measurably cheaper (live:
    # 528us cartesian -> 377us aggregated). Leave it in and the relational design is charged
    # for a query no competent developer would write, which flatters every design that
    # assembles the aggregate for you.
    branches = _child_branches(model, query)
    if len(branches) >= 2 and not computed:
        branch_members = {m for mem in branches.values() for m, _ in mem}
        # The OUTER query keeps everything that is not gathered inside a branch: the root's
        # columns, any N:1 parent's columns (joined — a parent cannot fan), and the
        # predicates on those entities. A predicate on a branch entity filters INSIDE its
        # branch. Dropping either kind silently answered a different question than asked —
        # in the very path added to make relational answers correct.
        outer = {**query,
                 "returns": [r for r in query["returns"]
                             if r.split(".", 1)[0] not in branch_members],
                 "predicates": [p for p in query.get("predicates", []) or []
                                if p["ref"].split(".", 1)[0] not in branch_members],
                 "order_by": [o for o in query.get("order_by") or []
                              if o["ref"].split(".", 1)[0] not in branch_members]}
        cols = [f"{_alias(r.split('.', 1)[0])}.{_col(model, r)}" for r in outer["returns"]]
        subs = [_branch_subquery(model, query, hop, mem, table_of=table_of)
                for hop, mem in branches.items()]
        # No root columns is legal (every return inside a branch): the projection is just
        # the subqueries — never emit the 'SELECT ,' that ORA-00936s.
        sel = ",\n".join(([", ".join(cols)] if cols else []) + subs)
        return (f"SELECT {sel}\n" + _from_join_where(model, outer, table_of=table_of)
                + _order_by_clause(model, outer) + _limit_clause(query))

    cols = [f"{_alias(ref.split('.', 1)[0])}.{_col(model, ref)}" for ref in query["returns"]]
    cols += [f"{c['expr']} AS {c['name']}" for c in computed]
    return (f"SELECT {', '.join(cols)}\n" + _from_join_where(model, query, table_of=table_of)
            + _order_by_clause(model, query) + _limit_clause(query))


def _summary_tbl(e):
    """The summary lane's own table — an MV on the shared base tables would
    charge maintenance to the plain relational design's write cells (the same
    measurement-honesty problem the hybrid lane's D2 solved)."""
    return f"{e['table']}_s"


def generate_summary(model, query) -> str:
    """The summary design: a matched aggregation reads its materialized view
    DIRECTLY (deterministic — QUERY REWRITE is prose, not mechanism); every
    other pattern rides the relational generators against the `_s` lane, so
    the design answers everything. Matching is `summary_mv_for` — the same
    helper the index deriver uses, so "the MV serves it" and "skip its agg
    index" cannot disagree."""
    _check(model, query)
    if not ((model.get("projections") or {}).get("summary") or {}).get("mvs"):
        raise ValueError("no summary projection in the model")
    mv = summary_mv_for(model, query) if is_aggregate(query) else None
    if mv is None:
        return generate_relational(model, query, table_of=_summary_tbl)

    def _col_of(ref):
        ent, prop = ref.split(".", 1)
        e = model["entities"][ent]
        return prop if prop == e["pk"] else (e.get("columns") or {}).get(prop, prop)

    sel = [f"{_col_of(r)} AS {r.split('.', 1)[1]}" for r in query.get("group_by") or []]
    sel += [a["name"] for a in query.get("aggregates") or []]
    conds = [_render_predicate_sql(_col_of(p["ref"]), p.get("op", "="), p.get("value"))
             for p in query.get("predicates") or []]
    where = ("\nWHERE " + " AND ".join(conds)) if conds else ""
    ob = ""
    if query.get("order_by"):
        parts = []
        for o in query["order_by"]:
            d = str(o.get("dir", "ASC")).upper()
            if d not in ("ASC", "DESC"):
                raise ValueError(f"invalid sort direction: {o.get('dir')!r}")
            parts.append(f"{_col_of(o['ref'])} {d}")
        ob = "\nORDER BY " + ", ".join(parts)
    return (f"SELECT {', '.join(sel)}\nFROM {mv['name']}{where}{ob}"
            + _limit_clause(query))


def _hybrid_tbl(e):
    """The hybrid lane's own table — see hybrid_table in ddl.py (decision D2:
    separate storage, so the flex column cannot perturb relational's rows)."""
    return f"{e['table']}_h"


def _hybrid_flex_cond(model, ent, prop, op, value, alias):
    """A flex predicate: plain dot for scalars (compiles to the same
    JSON_VALUE(... TYPE(STRICT)) recheck the multivalue index serves),
    JSON_EXISTS containment for arrays, JSON_EXISTS for key-presence — the
    document doctrine applied to the flex column."""
    o = _norm_op(op)
    src = f"{alias}.flex"
    if is_array_prop(model, ent, prop) and o not in ("IS NULL", "IS NOT NULL"):
        jop = {"=": "==", "!=": "!=", "<>": "!="}.get(o, o)
        if o == "IN":
            inner = " || ".join(f"@ == {_render_json_path_value(v)}" for v in value)
        elif o == "BETWEEN":
            inner = (f"@ >= {_render_json_path_value(value[0])} "
                     f"&& @ <= {_render_json_path_value(value[1])}")
        else:
            inner = f"@ {jop} {_render_json_path_value(value)}"
        return f"JSON_EXISTS({src}, '$.{prop}?({inner})')"
    if o == "IS NULL":
        return f"NOT JSON_EXISTS({src}, '$.{prop}')"
    if o == "IS NOT NULL":
        return f"JSON_EXISTS({src}, '$.{prop}')"
    return _render_predicate_sql(dot_pred_expr(prop, alias=alias, col="flex"), o, value)


def generate_hybrid(model, query) -> str:
    """The hybrid shape: a relational core + a JSON flex column per entity, on
    the lane's own `_h` tables. Core references are plain columns; flex
    references follow the document doctrine — plain-dot predicates, typed item
    methods where a SQL type is needed (projection, aggregation, ORDER BY),
    JSON_EXISTS containment for arrays. Every pattern kind is expressible:
    joins, branches, and aggregations work exactly as relational does."""
    _check(model, query)
    if not ((model.get("projections") or {}).get("hybrid") or {}).get("entities"):
        raise ValueError("no hybrid projection in the model")

    def is_flex(ref):
        ent, prop = ref.split(".", 1)
        return prop in hybrid_flex_props(model, ent)

    def cond_of(p):
        ent, prop = p["ref"].split(".", 1)
        if is_flex(p["ref"]):
            return _hybrid_flex_cond(model, ent, prop, p.get("op", "="),
                                     p.get("value"), _alias(ent))
        return _render_predicate_sql(f"{_alias(ent)}.{_col(model, p['ref'])}",
                                     p.get("op", "="), p.get("value"))

    def val_of(alias, ref):
        ent, prop = ref.split(".", 1)
        if is_flex(ref):
            return dot_typed_expr(model, ent, prop, alias=alias, col="flex")
        return f"{alias}.{_col(model, ref)}"

    def ob_clause():
        parts = []
        for o in query.get("order_by") or []:
            d = str(o.get("dir", "ASC")).upper()
            if d not in ("ASC", "DESC"):
                raise ValueError(f"invalid sort direction: {o.get('dir')!r}")
            parts.append(f"{val_of(_alias(o['ref'].split('.', 1)[0]), o['ref'])} {d}")
        return ("\nORDER BY " + ", ".join(parts)) if parts else ""

    if is_aggregate(query):
        def col_of(ref, numeric=False):
            return agg_expr(model, ref, "hybrid", numeric=numeric,
                            alias=_alias(ref.split(".", 1)[0]))
        return (f"SELECT {', '.join(_agg_projection(query, col_of))}\n"
                + _from_join_where(model, query, table_of=_hybrid_tbl, cond_of=cond_of)
                + _group_by_clause(query, col_of) + ob_clause() + _limit_clause(query))

    computed = _validated_computed(query)
    branches = _child_branches(model, query)
    if len(branches) >= 2 and not computed:
        # Same fan-trap discipline as relational: independent child collections
        # gather in correlated subqueries, never a cross-product.
        branch_members = {m for mem in branches.values() for m, _ in mem}
        outer = {**query,
                 "returns": [r for r in query["returns"]
                             if r.split(".", 1)[0] not in branch_members],
                 "predicates": [p for p in query.get("predicates", []) or []
                                if p["ref"].split(".", 1)[0] not in branch_members],
                 "order_by": [o for o in query.get("order_by") or []
                              if o["ref"].split(".", 1)[0] not in branch_members]}
        cols = []
        for r in outer["returns"]:
            expr = val_of(_alias(r.split(".", 1)[0]), r)
            cols.append(f"{expr} AS {r.split('.', 1)[1]}" if is_flex(r) else expr)
        subs = [_branch_subquery(model, query, hop, mem, table_of=_hybrid_tbl,
                                 col_of=val_of, cond_of=cond_of)
                for hop, mem in branches.items()]
        sel = ",\n".join(([", ".join(cols)] if cols else []) + subs)
        return (f"SELECT {sel}\n"
                + _from_join_where(model, outer, table_of=_hybrid_tbl, cond_of=cond_of)
                + ob_clause() + _limit_clause(query))

    cols = []
    for r in query["returns"]:
        expr = val_of(_alias(r.split(".", 1)[0]), r)
        # a flex scalar is aliased to its PROPERTY NAME so the result column —
        # and therefore the canonical answer — matches every other shape's
        cols.append(f"{expr} AS {r.split('.', 1)[1]}" if is_flex(r) else expr)
    cols += [f"{c['expr']} AS {c['name']}" for c in computed]
    return (f"SELECT {', '.join(cols)}\n"
            + _from_join_where(model, query, table_of=_hybrid_tbl, cond_of=cond_of)
            + ob_clause() + _limit_clause(query))


def generate_sql_view(model, query) -> str:
    """Read-only SQL view/query returning a document via JSON_OBJECT — the duality
    fallback for projections duality can't express (COALESCE, derived columns,
    aggregation…)."""
    _check(model, query)

    def col_of(ref, numeric=False):
        return f"{_alias(ref.split('.', 1)[0])}.{_col(model, ref)}"

    if is_aggregate(query):
        pairs = [f"'{ref.split('.', 1)[1]}' VALUE {col_of(ref)}" for ref in query.get("group_by", [])]
        for a in query.get("aggregates", []) or []:
            fn = _agg_fn(a)
            arg = "*" if a.get("ref", "*") == "*" else col_of(a["ref"])
            pairs.append(f"'{a['name']}' VALUE {fn}({arg})")
        return (f"SELECT JSON_OBJECT({', '.join(pairs)}) AS doc\n"
                + _from_join_where(model, query) + _group_by_clause(query, col_of)
                + _order_by_clause(model, query) + _limit_clause(query))

    computed = _validated_computed(query)
    pairs = [f"'{ref.split('.', 1)[1]}' VALUE {col_of(ref)}" for ref in query["returns"]]
    pairs += [f"'{c['name']}' VALUE {c['expr']}" for c in computed]
    return (f"SELECT JSON_OBJECT({', '.join(pairs)}) AS doc\n"
            + _from_join_where(model, query) + _order_by_clause(model, query)
            + _limit_clause(query))


def _id_predicate_value(model, query):
    """The predicate value on the root entity's PK (the id-filter for JSON shapes)."""
    root = query["root"]
    pk = model["entities"][root]["pk"]
    for p in query.get("predicates", []):
        ent = p["ref"].split(".", 1)[0]
        if ent == root and _col(model, p["ref"]) == pk:
            return _render_value(p["value"])
    return None


def _json_query(model, query, target, id_path, paths=None, dot=False):
    """paths: where each `Entity.prop` lives inside THIS document. A duality view is not
    flat — a nested parent's FK moves from `$.passenger_id` to `$.passenger.passenger_id`
    (ORA-40609 forbids it being both). Filter the flat path and the query silently matches
    nothing, then times beautifully. `dot` selects dot-notation-first (the document lane);
    duality keeps its measured JSON_VALUE/JSON_EXISTS forms."""
    _check(model, query)
    root = query["root"]
    pk = model["entities"][root]["pk"]
    conds = []
    for p in query.get("predicates", []):
        ent, prop = p["ref"].split(".", 1)
        is_pk = (ent == root and _col(model, p["ref"]) == pk)
        path = None if is_pk else (paths or {}).get(p["ref"])
        arr = is_array_prop(model, ent, prop, query)
        conds.append(_render_predicate_json(model, ent, prop, p.get("op", "="),
                                            p.get("value"), id_path, is_pk, path=path,
                                            is_array=arr, dot=dot))
    where = ("\nWHERE " + " AND ".join(conds)) if conds else ""

    if is_aggregate(query):
        # A document CAN aggregate on an access path — this used to say it could not, and
        # full-scanned to prove it. It full-scanned because we never derived an index from the
        # GROUP BY key. The expression here comes from the same helper the INDEX is built from
        # (`agg_expr`), because an index whose expression differs by one character is built,
        # valid, and silently ignored. RETURNING NUMBER pins a numeric argument — JSON_VALUE
        # defaults to VARCHAR2 and SUM of that coerces or raises.
        def col_of(ref, numeric=False):
            return agg_expr(model, ref, "document", numeric=numeric)
        return (f"SELECT {', '.join(_agg_projection(query, col_of))}\n"
                f"FROM {target} d{where}" + _group_by_clause(query, col_of))

    # ORDER BY and LIMIT are NOT optional. A duality view sorts perfectly well — you order on
    # a JSON_VALUE expression, and it can even use a functional index. We simply were not
    # emitting them, so the relational query sorted and the JSON queries did not: the JSON
    # shapes "won" a row by doing less work. The equivalence gate compares SETS of values and
    # cannot see an ordering difference, so nothing caught it.
    ob = ""
    if query.get("order_by"):
        parts = []
        for o in query["order_by"]:
            ent, prop = o["ref"].split(".", 1)
            path = (paths or {}).get(o["ref"])
            # Document lane: typed item-method dot preserves the sort type
            # (.numberOnly() sorts numerically) without JSON_VALUE RETURNING.
            # Duality keeps JSON_VALUE — its functional-index evidence.
            expr = (dot_typed_expr(model, ent, prop) if dot and not path
                    else json_value_expr(model, ent, prop, path=path))
            parts.append(f"{expr} {str(o.get('dir', 'ASC')).upper()}")
        ob = "\nORDER BY " + ", ".join(parts)
    return f"SELECT d.data\nFROM {target} d{where}{ob}" + _limit_clause(query)


def generate_duality(model, query) -> str:
    """Read through the LEANEST view that can answer this query. A duality view costs exactly
    what it nests, so a point read must not be served by the view that assembles the whole
    itinerary — that is the difference between 451us and 3,257us for the same two scalars."""
    _check(model, query)
    view = select_duality_view(model, query)
    if not view:
        raise ValueError(f"no duality view can answer a query rooted at {query['root']!r}")
    return _json_query(model, query, view["view"], "$._id",
                       paths=duality_paths(model, query["root"], view))


def generate_document(model, query) -> str:
    _check(model, query)
    doc = ((model.get("projections") or {}).get("document") or {}).get(query["root"])
    if not doc:
        raise ValueError(f"no document projection for root entity {query['root']!r}")
    return _json_query(model, query, doc["collection"], doc.get("id_path", "$._id"),
                       dot=True)


def _single_table_write_scope(model, query):
    """(table, discriminator, type, pk-predicate) for a write against the single
    collection — scoped to the item type, so it never touches another type's rows."""
    st = (model.get("projections") or {}).get("single_table")
    if not st:
        raise ValueError("model has no single_table projection")
    root = query["root"]
    e = model["entities"][root]
    pk = e["pk"]
    pk_col = pk[0] if isinstance(pk, list) else pk
    return (st["table"], st.get("discriminator", "type"), root, pk_col)


def generate_update(model, query, shape, set_ref, delta=1) -> str:
    """Generate a field UPDATE for one shape — the write-amplification case.

    relational: updates one row. document: JSON_TRANSFORM rewrites the whole embedded
    document. duality: writes through the view (fans to base tables). single_table:
    updates the item in place, scoped to its type.
    """
    _check(model, query)
    if shape == "single_table":
        table, disc, typ, pk_col = _single_table_write_scope(model, query)
        set_col = _col(model, set_ref)
        id_val = _id_predicate_value(model, query)
        return (f"UPDATE {table} SET {set_col} = {set_col} + {int(delta)} "
                f"WHERE {disc} = {_render_value(typ)} AND {pk_col} = {id_val}")
    if shape == "hybrid":
        # core prop -> a plain single-row column update; flex prop -> a
        # JSON_TRANSFORM rewrite of the flex column only (not the whole row's
        # document — the hybrid's write-amplification story in one branch).
        set_ent, set_prop = set_ref.split(".", 1)
        e = model["entities"][set_ent]
        tbl = f"{e['table']}_h"
        id_val = _id_predicate_value(model, query)
        root = query["root"]
        rk = (model["entities"][root]["pk"] if set_ent == root
              else _child_fk_to_root(model, set_ent, root))
        if set_prop in hybrid_flex_props(model, set_ent):
            return (f"UPDATE {tbl} SET flex = JSON_TRANSFORM(flex, "
                    f"SET '$.{set_prop}' = "
                    f"JSON_VALUE(flex, '$.{set_prop}' RETURNING NUMBER) + {int(delta)}) "
                    f"WHERE {rk} = {id_val}")
        set_col = _col(model, set_ref)
        return (f"UPDATE {tbl} SET {set_col} = {set_col} + {int(delta)} "
                f"WHERE {rk} = {id_val}")
    if shape not in ("relational", "document", "duality", "summary"):
        raise ValueError(f"unknown shape: {shape!r}")
    set_ent, _set_prop = set_ref.split(".", 1)
    set_col = _col(model, set_ref)
    id_val = _id_predicate_value(model, query)

    if shape in ("relational", "summary"):
        tbl = model["entities"][set_ent]["table"] + ("_s" if shape == "summary" else "")
        root = query["root"]
        if set_ent == root:
            # The column lives on the root itself (a status flip, a counter increment) —
            # scope by the root's own PK, not by a child FK.
            rk = model["entities"][root]["pk"]
        else:
            # scope to the root via the relationship join key on the child table
            rk = _child_fk_to_root(model, set_ent, root)
        return (f"UPDATE {tbl} SET {set_col} = {set_col} + {int(delta)} "
                f"WHERE {rk} = {id_val}")

    if shape == "document":
        doc = ((model.get("projections") or {}).get("document") or {}).get(query["root"])
        if not doc:
            raise ValueError(f"no document projection for {query['root']!r}")
        # Where set_ref lives inside the document — derived the same way duality_paths
        # derives it (root scalar -> $.prop, child -> $.<child>s[*].prop), `[0]` selecting
        # the one element this write rewrites. Hardcoding the path updates a field the
        # caller never asked for — silently, since JSON_TRANSFORM SET creates it.
        derived = duality_paths(model, query["root"]).get(set_ref)
        if not derived:
            raise ValueError(f"cannot locate {set_ref!r} in the document for {query['root']!r}")
        path = derived.replace("[*]", "[0]")
        # Whole-document rewrite of a nested array element (amplification).
        return (f"UPDATE {doc['collection']} SET data = JSON_TRANSFORM(data, "
                f"SET '{path}' = JSON_VALUE(data, '{path}' RETURNING NUMBER) + {int(delta)}) "
                f"WHERE JSON_VALUE(data, '{doc.get('id_path', '$._id')}' RETURNING NUMBER) = {id_val}")

    # The view that models the aggregate being written — NOT the raw projection entry, which
    # is a list of views and would render as a Python repr straight into the SQL.
    dv = _dual_or_doc(model, query, "duality")
    prop = set_ref.split(".", 1)[1] if "." in set_ref else set_ref
    paths = duality_paths(model, query["root"], select_duality_view(model, query))
    path = paths.get(set_ref, f"$.{prop}")
    return (f"UPDATE {dv} SET data = JSON_TRANSFORM(data, "
            f"SET '{path}' = JSON_VALUE(data, '{path}' RETURNING NUMBER) + {int(delta)}) "
            f"WHERE JSON_VALUE(data, '$._id' RETURNING NUMBER) = {id_val}")


def _json_literal(element) -> str:
    """Render a dict/list as a JSON literal for JSON_TRANSFORM."""
    import json as _json
    return "JSON('" + _json.dumps(element).replace("'", "''") + "')"


def generate_array_append(model, query, shape, array_path, element) -> str:
    """Append an element to an array (Bucket/Pre-allocation). Relational inserts a
    child row; the embedded document JSON_TRANSFORM-APPENDs (rewrites) the whole
    document; duality appends through the view. sql_view is read-only -> ValueError."""
    _check(model, query)
    if shape not in ("relational", "document", "duality", "hybrid", "summary"):
        raise ValueError(f"append not supported for shape {shape!r}")
    id_val = _id_predicate_value(model, query)
    if shape in ("relational", "hybrid", "summary"):
        # Insert a child row of the array-owning child entity of the root —
        # the hybrid/summary lanes append into their own suffixed child table.
        child = _array_child_entity(model, query["root"])
        tbl = model["entities"][child]["table"] + {"hybrid": "_h", "summary": "_s"}.get(shape, "")
        cols = list(element.keys())
        fk = _child_fk_to_root(model, child, query["root"])
        col_list = ", ".join([fk] + cols)
        val_list = ", ".join([str(id_val)] + [_render_value(v) for v in element.values()])
        return f"INSERT INTO {tbl} ({col_list}) VALUES ({val_list})"
    target = (_dual_or_doc(model, query, shape))
    return (f"UPDATE {target} SET data = JSON_TRANSFORM(data, "
            f"APPEND '{array_path}' = {_json_literal(element)}) "
            f"WHERE JSON_VALUE(data, '$._id' RETURNING NUMBER) = {id_val}")


def generate_multi_field_update(model, query, shape, sets) -> str:
    """Update several fields in one statement. `sets` is a list of {ref, expr} for
    relational, or {path, expr} for document/duality."""
    _check(model, query)
    id_val = _id_predicate_value(model, query)
    if shape in ("relational", "hybrid", "summary"):
        root = query["root"]
        pk = model["entities"][root]["pk"]
        tbl = model["entities"][root]["table"] + {"hybrid": "_h", "summary": "_s"}.get(shape, "")
        assigns = []
        flex_steps = []
        for s in sets:
            prop = s["ref"].split(".", 1)[1]
            if (shape == "hybrid"
                    and prop in hybrid_flex_props(model, s["ref"].split(".", 1)[0])):
                flex_steps.append(f"SET '$.{prop}' = {s['expr']}")
            else:
                assigns.append(f"{_col(model, s['ref'])} = {s['expr']}")
        if flex_steps:
            assigns.append(f"flex = JSON_TRANSFORM(flex, {', '.join(flex_steps)})")
        return f"UPDATE {tbl} SET {', '.join(assigns)} WHERE {pk} = {id_val}"
    if shape in ("document", "duality"):
        steps = ", ".join(f"SET '{s['path']}' = {s['expr']}" for s in sets)
        target = _dual_or_doc(model, query, shape)
        return (f"UPDATE {target} SET data = JSON_TRANSFORM(data, {steps}) "
                f"WHERE JSON_VALUE(data, '$._id' RETURNING NUMBER) = {id_val}")
    raise ValueError(f"update not supported for shape {shape!r}")


def _dual_or_doc(model, query, shape):
    """The object a write goes through.

    For duality that is a VIEW, chosen the same way a read chooses one: the leanest view that
    models the aggregate being written. A status change touches one root scalar, so it writes
    through the lean view — the cheapest write. Creating a booking writes the reservation AND
    its legs AND its payment, so it writes through the view that holds them; aim that document
    at the lean view instead and Oracle rejects it outright (ORA-40944, JZN-00651 "field
    'itinerarylegs' is unknown or undefined"), because the field genuinely is not there.

    `projections.duality[root]` is a LIST of views. Returning it raw put a Python repr
    straight into the SQL — `UPDATE [{'view': ...}] SET ...` — which is the same defect that
    once took the duality DDL out with ORA-24558.
    """
    proj = (model.get("projections") or {})
    if shape == "duality":
        view = select_duality_view(model, query)
        if not view:
            raise ValueError(f"no duality view can hold a write rooted at {query['root']!r}")
        return view["view"]
    doc = (proj.get("document") or {}).get(query["root"])
    if not doc:
        raise ValueError(f"no document projection for {query['root']!r}")
    return doc["collection"]


def _array_child_entity(model, root):
    """The 1:N child entity of root (the array owner) — first one found."""
    for r in model.get("relationships", []):
        if r["from"] == root and r.get("cardinality", "").endswith("N"):
            return r["to"]
    raise ValueError(f"no 1:N array child for root {root!r}")


def _child_fk_to_root(model, child, root):
    """The child table's FK column that references the root (for scoping the update)."""
    for r in model.get("relationships", []):
        if r["from"] == root and r["to"] == child:
            return r["to_key"]
        if r["to"] == root and r["from"] == child:
            return r["from_key"]
    raise ValueError(f"no relationship from root {root!r} to {child!r}")


def generate_insert(model, query, shape) -> str:
    _check(model, query)
    if shape == "single_table":
        table, disc, typ, pk_col = _single_table_write_scope(model, query)
        return (f"INSERT INTO {table} ({disc}, {pk_col}) "
                f"VALUES ({_render_value(typ)}, 9999)")
    if shape == "hybrid":
        e = model["entities"][query["root"]]
        return f"INSERT INTO {e['table']}_h ({e['pk']}) VALUES (9999)"
    if shape == "summary":
        e = model["entities"][query["root"]]
        return f"INSERT INTO {e['table']}_s ({e['pk']}) VALUES (9999)"
    if shape not in ("relational", "document", "duality"):
        raise ValueError(f"unknown shape: {shape!r}")
    if shape == "relational":
        e = model["entities"][query["root"]]
        return f"INSERT INTO {e['table']} ({e['pk']}) VALUES (9999)"
    if shape == "duality":
        # There was NO duality branch here: the insert fell through to the document
        # collection, and the document's write cost was then reported as duality's. A duality
        # write goes through a duality VIEW — the one modelling the aggregate being written.
        return (f"INSERT INTO {_dual_or_doc(model, query, shape)} (data) "
                f"VALUES (JSON('{{\"_id\": 9999}}'))")
    doc = ((model.get("projections") or {}).get("document") or {}).get(query["root"])
    coll = doc["collection"] if doc else "order_docs"
    return f"INSERT INTO {coll} (data) VALUES (JSON('{{\"_id\": 9999}}'))"


def _hierarchy_rel(model, entity):
    for r in model.get("relationships", []):
        if r.get("kind") == "hierarchy" and r["from"] == entity and r["to"] == entity:
            return r
    raise ValueError(f"no self-referencing hierarchy relationship on {entity!r}")


def _traversal_start(model, query):
    st = query["traversal"]["start"]
    col = _col(model, st["ref"])
    return _render_predicate_sql(col, st.get("op", "="), st.get("value"))


def generate_connect_by(model, query) -> str:
    """Hierarchy traversal via CONNECT BY. down: descendants of the start node."""
    _check_traversal(model, query)
    root = query["root"]
    rel = _hierarchy_rel(model, root)
    tbl = model["entities"][root]["table"]
    cols = ", ".join(_col(model, ref) for ref in query["returns"])
    pk, parent = rel["from_key"], rel["to_key"]
    down = query["traversal"].get("direction", "down") == "down"
    connect = (f"PRIOR {pk} = {parent}" if down else f"{pk} = PRIOR {parent}")
    return (f"SELECT {cols}, LEVEL AS lvl\nFROM {tbl}\n"
            f"START WITH {_traversal_start(model, query)}\nCONNECT BY {connect}")


def generate_recursive_cte(model, query) -> str:
    """Hierarchy traversal via a recursive WITH clause."""
    _check_traversal(model, query)
    root = query["root"]
    rel = _hierarchy_rel(model, root)
    tbl = model["entities"][root]["table"]
    pk, parent = rel["from_key"], rel["to_key"]
    ret_cols = [_col(model, ref) for ref in query["returns"]]
    # The CTE must carry the join keys (pk, parent) even if they aren't returned.
    cte_cols = list(dict.fromkeys([pk, parent] + ret_cols))
    sel = ", ".join(cte_cols)
    down = query["traversal"].get("direction", "down") == "down"
    join = (f"e.{parent} = r.{pk}" if down else f"e.{pk} = r.{parent}")
    return (f"WITH r ({sel}, lvl) AS (\n"
            f"  SELECT {sel}, 1 FROM {tbl} WHERE {_traversal_start(model, query)}\n"
            f"  UNION ALL\n"
            f"  SELECT {', '.join('e.' + c for c in cte_cols)}, r.lvl + 1 "
            f"FROM {tbl} e JOIN r ON {join}\n)\n"
            f"SELECT {', '.join(ret_cols)}, lvl FROM r")


def _check_traversal(model, query):
    errs = validate_model(model)
    if "traversal" not in query or "start" not in query["traversal"]:
        errs.append("traversal query needs a traversal.start")
    if query.get("root") not in model.get("entities", {}):
        errs.append(f"unknown root {query.get('root')!r}")
    if errs:
        raise ValueError("invalid traversal spec: " + "; ".join(errs))


def _graph_names(model, entity):
    e = model["entities"][entity]
    return e["table"], f"{e['table']}_graph", f"{e['table']}_edge"


def generate_property_graph_ddl(model, entity, name=None) -> str:
    """CREATE PROPERTY GRAPH over a self-referencing `hierarchy` relationship — the
    SQL/PGQ realization of a Tree. Each row is a vertex; the parent ref is the edge
    (source = the row's pk, destination = the referenced parent pk)."""
    rel = _hierarchy_rel(model, entity)
    e = model["entities"][entity]
    tbl, gname, edge = _graph_names(model, entity)
    gname = name or gname
    pk, parent = rel["from_key"], rel["to_key"]
    props = list(dict.fromkeys([pk] + list((e.get("columns") or {}).values())))
    return (f"CREATE PROPERTY GRAPH {gname}\n"
            f"  VERTEX TABLES ({tbl} KEY ({pk}) PROPERTIES ({', '.join(props)}))\n"
            f"  EDGE TABLES ({tbl} AS {edge}\n"
            f"    KEY ({pk})\n"
            f"    SOURCE KEY ({pk}) REFERENCES {tbl} ({pk})\n"
            f"    DESTINATION KEY ({parent}) REFERENCES {tbl} ({pk})\n"
            f"    PROPERTIES ({pk}))")


def generate_graph_table(model, query) -> str:
    """Hierarchy traversal via SQL/PGQ GRAPH_TABLE. Returns the subtree rooted at the
    start node (start + descendants for `down`; start + ancestors for `up`) — the
    same set CONNECT BY / recursive CTE return, so the three Tree realizations agree.
    """
    _check_traversal(model, query)
    root = query["root"]
    _hierarchy_rel(model, root)                       # require a self-referencing edge
    _tbl, gname, edge = _graph_names(model, root)
    st = query["traversal"]["start"]
    start_col = _col(model, st["ref"])
    where = _render_predicate_sql(f"a.{start_col}", st.get("op", "="), st.get("value"))
    cols = ", ".join(f"n.{_col(model, ref)} AS {_col(model, ref)}" for ref in query["returns"])
    # Oracle GRAPH_TABLE requires a *bounded* quantifier (`*`/`+`/`{0,}` are rejected);
    # `{0,d}` includes the anchor itself (path length 0) → start + reachable nodes, so
    # the set matches CONNECT BY / recursive CTE up to depth d. Cost grows ~2x per +4
    # of the bound (measured), so d is a modest default (16 covers real hierarchies) and
    # overridable via traversal.max_depth — a characteristic of this realization: great
    # for bounded/graph traversal, while CONNECT BY / CTE suit deep/unbounded trees.
    depth = int(query["traversal"].get("max_depth", 16))
    if query["traversal"].get("direction", "down") == "down":
        match = f"(n) -[e IS {edge}]->{{0,{depth}}} (a)"   # n reports up to the anchor a
    else:
        match = f"(a) -[e IS {edge}]->{{0,{depth}}} (n)"   # n is an ancestor of the anchor a
    return (f"SELECT {', '.join(_col(model, ref) for ref in query['returns'])}\n"
            f"FROM GRAPH_TABLE ({gname}\n  MATCH {match}\n  WHERE {where}\n"
            f"  COLUMNS ({cols}))")


def generate_single_table(model, query) -> str:
    """Query the converged single-table design: one shared table with a `type`
    discriminator and native composite-key/GSI-derived indexes. A per-type read
    filters on the discriminator; an item-collection read (several types under a
    shared anchor) filters on the anchor column and returns them in one indexed
    scan — no joins, because the related items are co-located.

    query: {returns:[refs], type|types: discriminator value(s)?, predicates, order_by, limit}.
    Column refs resolve to the shared table's columns (property name).
    """
    st = (model.get("projections") or {}).get("single_table")
    if not st:
        raise ValueError("model has no single_table projection")
    table = st["table"]
    disc = st.get("discriminator", "type")

    def _stcol(ref):
        ent, prop = ref.split(".", 1)
        e = model["entities"].get(ent, {})
        return (e.get("columns") or {}).get(prop, prop)

    # Still SQL: a single collection can GROUP BY. Without this it would be EXCLUDED from
    # any workload with a KPI/reporting pattern — which is most of them.
    if is_aggregate(query):
        conds_a = []
        types_a = query.get("types") or ([query["type"]] if query.get("type") else None)
        if types_a is None and query.get("root") in (st.get("types") or {}):
            types_a = [query["root"]]
        if types_a:
            conds_a.append(f"{disc} IN (" + ", ".join(_render_value(t) for t in types_a) + ")")
        for p in query.get("predicates", []) or []:
            conds_a.append(_render_predicate_sql(_stcol(p["ref"]), p.get("op", "="), p.get("value")))
        where_a = ("\nWHERE " + " AND ".join(conds_a)) if conds_a else ""

        def col_of(ref, numeric=False):
            return _stcol(ref)
        return (f"SELECT {', '.join(_agg_projection(query, col_of))}\n"
                f"FROM {table}{where_a}" + _group_by_clause(query, col_of))

    # The converged edge over DynamoDB: shape the co-located result into the required
    # document on the way out (JSON_ARRAYAGG of JSON_OBJECTs) — no stored document to
    # rewrite. Set as_document to get one assembled JSON array back.
    if query.get("as_document"):
        pairs = [f"'{r.split('.', 1)[1]}' VALUE {_stcol(r)}" for r in query.get("returns", [])]
        select = f"JSON_ARRAYAGG(JSON_OBJECT({', '.join(pairs)})) AS doc"
    else:
        select = ", ".join([_stcol(r) for r in query.get("returns", [])] or ["*"])
    cols = None
    conds = []
    declared = (st.get("types") or {})
    types = query.get("types") or ([query["type"]] if query.get("type") else None)
    if types is None:
        # THE ITEM-COLLECTION READ. The result set names the types: if a query returns
        # Order + OrderItem + Payment, all three come back — filtering on the root's
        # discriminator alone would return the order with NULL items and NULL payments
        # (a wrong answer, quickly). Any co-located type in the result set is included, and
        # the read keys on the ANCHOR, which is the one column they all share.
        refs = list(query.get("returns") or [])
        want = [r.split(".", 1)[0] for r in refs]
        if query.get("root"):
            want.insert(0, query["root"])
        types = [t for t in dict.fromkeys(want) if t in declared] or None
    if types:
        conds.append(f"{disc} IN (" + ", ".join(_render_value(t) for t in types) + ")")
    # For a single-type read, filter on the sparse-index expression (CASE WHEN
    # type='t' THEN col END) so the sparse type-filtered index is used; the plain
    # `type = 't'` above still prunes the partition. Correct with non-sparse indexes
    # too (the CASE evaluates to the column for matching rows). Across an item collection
    # the anchor column is shared by every type, so no CASE — one plain indexed scan.
    single_t = types[0] if types and len(types) == 1 else None
    for p in query.get("predicates", []) or []:
        col = _stcol(p["ref"])
        if single_t:
            col = f"CASE WHEN {disc} = {_render_value(single_t)} THEN {col} END"
        conds.append(_render_predicate_sql(col, p.get("op", "="), p.get("value")))
    where = ("\nWHERE " + " AND ".join(conds)) if conds else ""
    ob = ""
    if query.get("order_by") and not query.get("as_document"):
        parts = [f"{_stcol(o['ref'])} {str(o.get('dir', 'ASC')).upper()}" for o in query["order_by"]]
        ob = "\nORDER BY " + ", ".join(parts)
    return f"SELECT {select}\nFROM {table}{where}{ob}" + _limit_clause(query)


def generate_candidates(model, query) -> dict:
    """Generate the query against every candidate shape for a ModelSpec + QuerySpec.

    The relational-storage document option is a duality view when duality can
    express the query, or a JSON_OBJECT-wrapped SQL view (read-only) otherwise
    (COALESCE / derived columns / aggregation) — Rick's rule.
    """
    # A traversal query has its own realizations: CONNECT BY, recursive CTE, and —
    # when the model carries a self-referencing hierarchy edge — SQL/PGQ GRAPH_TABLE.
    if query.get("traversal"):
        tree = {"connect_by": generate_connect_by(model, query),
                "recursive_cte": generate_recursive_cte(model, query)}
        try:
            tree["graph_table"] = generate_graph_table(model, query)
        except ValueError:
            pass                                    # no hierarchy edge → no graph realization
        return tree

    proj = model.get("projections") or {}
    cands = {"relational": generate_relational(model, query)}
    if proj.get("document"):
        cands["document"] = generate_document(model, query)
    if (proj.get("hybrid") or {}).get("entities"):
        cands["hybrid"] = generate_hybrid(model, query)
    if (proj.get("summary") or {}).get("mvs"):
        cands["summary"] = generate_summary(model, query)
    if proj.get("document") or proj.get("duality"):
        # A duality view must stay updatable, so it cannot express a computed/derived
        # projection OR an aggregation — those route to a read-only JSON_OBJECT SQL view.
        if (proj.get("duality") and duality_supports(query)
                and not query.get("computed") and not is_aggregate(query)):
            cands["duality"] = generate_duality(model, query)
        else:
            cands["sql_view"] = generate_sql_view(model, query)
    # A converged single-table design is a candidate too, when the model offers one
    # (e.g. imported from a DynamoDB single-table design).
    if proj.get("single_table"):
        cands["single_table"] = generate_single_table(model, query)
    return cands


def _bfs_order(model, root):
    adj = {}
    for r in model.get("relationships", []):
        adj.setdefault(r["from"], []).append(r["to"])
        adj.setdefault(r["to"], []).append(r["from"])
    order, seen, q = [], {root}, deque([root])
    while q:
        cur = q.popleft()
        order.append(cur)
        for nxt in adj.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return order

# Copyright (c) 2026 Oracle and/or its affiliates.
"""Validate a ModelSpec and a QuerySpec for the query generator.

Pure, stdlib-only. Returns violation messages (empty == valid). Generation
never runs on an invalid spec, so broken SQL is never emitted silently.
"""


def is_array_prop(model, ent, prop, query=None) -> bool:
    """Is this property a JSON ARRAY? `tags = 'red'` against `["red","small"]` means
    CONTAINS: the query side must be JSON_EXISTS (JSON_VALUE of an array is NULL) and the
    index side must be MULTIVALUE (a scalar functional index over an array is all-NULL dead
    weight). Declared on the entity (`arrays: ["tags"]`), or flagged on the query by the
    Attribute realization (`attribute_kv`). ONE helper for both generators, so the query
    and its serving index cannot disagree about array-ness."""
    if (query or {}).get("attribute_kv"):
        return True
    e = (model.get("entities") or {}).get(ent) or {}
    return prop in set(e.get("arrays") or ())


def _ref_ok(ref: str, entities: dict) -> bool:
    if "." not in ref:
        return False
    ent, prop = ref.split(".", 1)
    e = entities.get(ent)
    if not e:
        return False
    return prop == e.get("pk") or prop in (e.get("columns") or {})


def hybrid_flex_props(model, ent):
    """The properties the hybrid projection moves into `ent`'s JSON flex column.
    Empty set when the entity (or the projection) declares none. ONE helper for
    the DDL, query, index, and seed generators — the four lanes cannot disagree
    about which side of the core/flex split a property lives on."""
    hy = ((model.get("projections") or {}).get("hybrid") or {}).get("entities") or {}
    return set(((hy.get(ent) or {}).get("flex")) or ())


def validate_model(model) -> list:
    v = []
    if not isinstance(model, dict):
        return ["model must be an object"]
    entities = model.get("entities")
    if not isinstance(entities, dict) or not entities:
        v.append("model.entities must be a non-empty object")
        entities = entities if isinstance(entities, dict) else {}
    for name, e in entities.items():
        if not isinstance(e, dict) or "table" not in e or "pk" not in e:
            v.append(f"entity {name} must have 'table' and 'pk'")
    rel_keys = set()
    for r in model.get("relationships", []) or []:
        for side in ("from", "to"):
            if r.get(side) not in entities:
                v.append(f"relationship references unknown entity: {r.get(side)}")
        if "from_key" not in r or "to_key" not in r:
            v.append(f"relationship {r.get('from')}->{r.get('to')} needs from_key and to_key")
        rel_keys |= {r.get("from_key"), r.get("to_key")}
    # The partition dimension: a per-entity block naming one of the three
    # lifecycle-justified families. `column` may be a property or a column
    # name and must resolve on the entity.
    for name, e in entities.items():
        part = (e or {}).get("partition") if isinstance(e, dict) else None
        if not part:
            continue
        if part.get("by") not in ("interval", "auto_list", "hash"):
            v.append(f"entity {name} partition strategy must be one of "
                     f"interval|auto_list|hash, got {part.get('by')!r}")
        col = part.get("column")
        cols = e.get("columns") or {}
        pk = e.get("pk")
        pk_cols = set(pk) if isinstance(pk, list) else {pk}
        if not col or (col not in cols and col not in set(cols.values())
                       and col not in pk_cols):
            v.append(f"entity {name} partition column does not resolve: {col!r}")
    # The organization (IOT) and compress dimensions. The engine decided
    # these rules and the live probes recorded them: of the v1 partition
    # families only hash composes with an index-organized table (anything
    # else is ORA-25198), row compression on an IOT is ORA-00922, and a
    # multivalue index on an IOT is ORA-61714 — so an IOT may not carry
    # hybrid flex properties, whose predicates would otherwise lose their
    # MVIs and silently full-scan.
    for name, e in entities.items():
        if not isinstance(e, dict):
            continue
        org = e.get("organization")
        if org is not None and org not in ("heap", "index"):
            v.append(f"entity {name} organization must be one of heap|index, "
                     f"got {org!r}")
        iot = org == "index"
        cols = e.get("columns") or {}
        pk = e.get("pk")
        pk_cols = set(pk) if isinstance(pk, list) else {pk}
        pct = e.get("pctthreshold")
        if pct is not None:
            if not iot:
                v.append(f"entity {name} pctthreshold needs organization "
                         f"index — only an IOT has an overflow segment")
            if isinstance(pct, bool) or not isinstance(pct, int) \
                    or not 1 <= pct <= 50:
                v.append(f"entity {name} pctthreshold must be 1-50, got {pct!r}")
        inc = e.get("including")
        if inc is not None:
            if not iot:
                v.append(f"entity {name} including needs organization "
                         f"index — only an IOT has an overflow segment")
            if (inc not in cols and inc not in set(cols.values())
                    and inc not in pk_cols):
                v.append(f"entity {name} including column does not resolve: "
                         f"{inc!r}")
        comp = e.get("compress")
        if comp is not None and comp != "advanced":
            v.append(f"entity {name} compress must be 'advanced', got {comp!r} "
                     f"— BASIC compresses on bulk load only and conventional "
                     f"updates decompress the block, so it is not an honest "
                     f"tier under DML")
        if iot and comp is not None:
            v.append(f"entity {name} is organization index and cannot also be "
                     f"row compressed — the pair raises ORA-00922 on deploy")
        part = e.get("partition") or {}
        if iot and part and part.get("by") != "hash":
            v.append(f"entity {name} is organization index, so only a hash "
                     f"partition composes — {part.get('by')!r} raises ORA-25198")
        if iot and part and part.get("by") == "hash":
            # an IOT's partitioning key must sit WITHIN the primary key —
            # a non-PK hash column deploys into ORA-25199
            pcol = part.get("column")
            pk_props = {p for p, c in cols.items() if c in pk_cols}
            if pcol not in pk_cols and pcol not in pk_props:
                v.append(f"entity {name} is organization index, so its hash "
                         f"partition key must be a primary-key column — "
                         f"{pcol!r} raises ORA-25199")
        if iot and hybrid_flex_props(model, name):
            v.append(f"entity {name} is organization index and cannot carry "
                     f"hybrid flex properties — a multivalue index on an IOT "
                     f"is ORA-61714, so its flex predicates would full-scan")
    # The summary projection: named single-root aggregation MVs. The MV's
    # query must BE an aggregation (a summary of nothing summarizes nothing)
    # and stay on one root — cross-entity join MVs are a fast-refresh
    # eligibility minefield deferred to v2.
    mvs = ((model.get("projections") or {}).get("summary") or {}).get("mvs")
    if mvs is not None:
        names = []
        for mv in mvs or []:
            nm = (mv or {}).get("name")
            if not nm:
                v.append("summary mv needs a name")
            elif nm in names:
                v.append(f"summary mv name is not unique: {nm}")
            names.append(nm)
            mq = (mv or {}).get("query") or {}
            if not (mq.get("group_by") or mq.get("aggregates")):
                v.append(f"summary mv {nm or '?'} query must be an aggregation")
                continue
            root = mq.get("root")
            refs = list(mq.get("group_by") or ())
            refs += [a.get("ref") for a in mq.get("aggregates") or ()
                     if a.get("ref", "*") != "*"]
            offroot = {r.split(".", 1)[0] for r in refs if "." in r} - {root}
            if offroot:
                v.append(f"summary mv {nm or '?'} must be single-root "
                         f"(references {', '.join(sorted(offroot))})")
    # The hybrid projection: per-entity `flex` lists select which of the
    # entity's declared properties live in the JSON flex column. The PK and
    # every relationship key must stay typed columns — they serve the point
    # reads, FKs and JOINs the relational core exists to keep cheap.
    hy = ((model.get("projections") or {}).get("hybrid") or {}).get("entities") or {}
    for ent, spec in hy.items():
        e = entities.get(ent)
        if not isinstance(e, dict):
            v.append(f"hybrid projection references unknown entity: {ent}")
            continue
        flex = (spec or {}).get("flex")
        if not flex:
            v.append(f"hybrid entity {ent} has an empty flex list — declare nothing instead")
            continue
        known = set((e.get("columns") or {}))
        pk = e.get("pk")
        pk_cols = set(pk) if isinstance(pk, list) else {pk}
        cols_of = e.get("columns") or {}
        for prop in flex:
            if prop not in known:
                v.append(f"hybrid flex property {ent}.{prop} is not a declared property "
                         f"(add it to columns): {prop}")
            elif prop in pk_cols or cols_of.get(prop) in pk_cols:
                v.append(f"hybrid flex may not take the primary key: {ent}.{prop}")
            elif cols_of.get(prop, prop) in rel_keys:
                v.append(f"hybrid flex may not take a relationship key: {ent}.{prop}")
    return v


# Operations a duality view cannot express (must stay updatable) — force a SQL view.
DUALITY_UNSUPPORTED = {
    "coalesce", "decode", "case", "derived", "computed",
    "group_by", "aggregate", "window", "distinct", "union",
}


def duality_supports(query) -> bool:
    """False when the query needs an operation a duality view can't express
    (COALESCE, derived columns, aggregation, …) — route it to a SQL view instead."""
    ops = {str(o).lower() for o in query.get("requires_ops", [])}
    return not (ops & DUALITY_UNSUPPORTED)


def summary_mv_for(model, query):
    """The declared summary MV that can answer this aggregation query, or None.

    A match requires: same root; identical group_by SET; every query aggregate
    present in the MV (same name, fn, ref — the read selects MV columns by
    those names); and every predicate on a group-by ref (anything else needs
    base rows the MV no longer has). ONE matcher for the query generator and
    the index deriver, so "the MV serves it" and "skip its agg index" cannot
    disagree."""
    if not (query.get("group_by") or query.get("aggregates")):
        return None
    mvs = ((model.get("projections") or {}).get("summary") or {}).get("mvs") or []
    q_groups = set(query.get("group_by") or ())
    q_aggs = {(a.get("name"), str(a.get("fn", "")).upper(), a.get("ref", "*"))
              for a in query.get("aggregates") or ()}
    pred_refs = {p.get("ref") for p in query.get("predicates") or ()}
    for mv in mvs:
        mq = mv.get("query") or {}
        if mq.get("root") != query.get("root"):
            continue
        if set(mq.get("group_by") or ()) != q_groups:
            continue
        mv_aggs = {(a.get("name"), str(a.get("fn", "")).upper(), a.get("ref", "*"))
                   for a in mq.get("aggregates") or ()}
        if not q_aggs <= mv_aggs:
            continue
        if not pred_refs <= q_groups:
            continue
        return mv
    return None


def validate_query(query, model) -> list:
    v = []
    entities = (model or {}).get("entities", {})
    if query.get("root") not in entities:
        v.append(f"query root {query.get('root')!r} is not a known entity")
    for ref in query.get("returns", []) or []:
        if not _ref_ok(ref, entities):
            v.append(f"return references unknown entity.property: {ref}")
    # An aggregation projects its GROUP BY keys + aggregate functions, so it legitimately
    # has no plain `returns`.
    if not query.get("returns") and not query.get("group_by"):
        v.append("query.returns must be a non-empty list")
    for ref in query.get("group_by", []) or []:
        if not _ref_ok(ref, entities):
            v.append(f"group_by references unknown entity.property: {ref}")
    for a in query.get("aggregates", []) or []:
        ref = a.get("ref", "*")
        if ref != "*" and not _ref_ok(ref, entities):
            v.append(f"aggregate references unknown entity.property: {ref}")
        if not a.get("name"):
            v.append(f"aggregate needs a name: {a}")
    for p in query.get("predicates", []) or []:
        if not _ref_ok(p.get("ref", ""), entities):
            v.append(f"predicate references unknown entity.property: {p.get('ref')}")
    return v

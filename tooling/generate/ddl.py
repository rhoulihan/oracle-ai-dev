# Copyright (c) 2026 Oracle and/or its affiliates.
"""Generate the CREATE DDL for a physical shape from a ModelSpec.

The measured optimizer picks a shape; this emits the schema that realizes it, so
the generated data layer can deploy it. Relational and duality share base tables;
document is a JSON collection; duality adds a single-level duality view.

Column types are taken from an optional per-entity `column_types` map when the
model provides one, else inferred (numeric-looking names -> NUMBER, date/time-ish
-> TIMESTAMP, otherwise VARCHAR2(4000)). Primary keys are identity NUMBERs.
"""

import re

from tooling.generate.model import (hybrid_flex_props, is_array_prop,
                                    summary_mv_for)

# Whole-token matches only — substring matching produced false positives like
# "country" -> "count" and "flight_number"/"tail_number" -> "num". The ambiguous
# tokens "num"/"number"/"no"/"id"/"code"/"ref" are deliberately NOT numeric: they
# usually name string identifiers. Keys are handled structurally (PK/FK -> NUMBER).
# "fare" is intentionally absent — "fare_class"/"fare_type" are category strings;
# a fare amount is "fare_amount" (matches "amount"). Keep only unambiguous tokens.
_NUMERIC_TOKENS = {"total", "price", "amount", "qty", "quantity", "count", "rating",
                   "balance", "cost", "capacity", "tax", "discount",
                   "subtotal", "age", "year", "weight", "height", "length", "width",
                   "distance", "duration", "percent", "ratio"}
_TIME_TOKENS = {"date", "time", "timestamp", "at", "datetime"}


def _tokens(prop, col):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", f"{prop}_{col}")
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def _coltype(prop, col, entity):
    ct = (entity.get("column_types") or {}).get(prop)
    if ct:
        return ct
    toks = _tokens(prop, col)
    if toks & _NUMERIC_TOKENS:
        return "NUMBER"
    if toks & _TIME_TOKENS:
        return "TIMESTAMP"
    return "VARCHAR2(4000)"


def _pk_list(e):
    """Primary-key columns as a list (single-column PK -> one-element list)."""
    pk = e["pk"]
    return list(pk) if isinstance(pk, list) else [pk]


def _pk_declared_type(e):
    """The DECLARED type of a single-column PK, or None. `pk_type` wins; else
    `column_types` looked up through the prop that maps to the pk column.
    Ignoring column_types here rendered every natural code key (country_code
    VARCHAR2(3)...) as NUMBER IDENTITY, and every FK to it died ORA-02267 —
    classic reference/lookup tables are not an edge case."""
    if isinstance(e["pk"], list):
        return None
    if e.get("pk_type"):
        return e["pk_type"].split(" GENERATED")[0].strip()  # drop any identity clause
    ct = e.get("column_types") or {}
    pk = e["pk"]
    prop = next((p for p, c in (e.get("columns") or {}).items() if c == pk), pk)
    return ct.get(prop) or ct.get(pk)


def _pk_sqltype(e):
    """SQL type of a single-column PK, for typing the FK columns that reference it.
    The declared type (pk_type or column_types) wins; the default identity PK is NUMBER."""
    if isinstance(e["pk"], list):
        return "NUMBER"  # composite keys aren't referenced by single-column FKs here
    return _pk_declared_type(e) or "NUMBER"


def _fks_on(model, ent):
    """FK columns this entity holds. 1:N -> FK on the 'to' side; N:1 -> on 'from'.
    Each carries the referenced PK's SQL type so the FK column matches it."""
    out = []
    for r in model.get("relationships", []):
        card = (r.get("cardinality") or "1:N").upper()
        if card == "N:1":
            holder, col, ref_ent, ref_key = r["from"], r["from_key"], r["to"], r["to_key"]
        else:  # 1:N, 1:1, default
            holder, col, ref_ent, ref_key = r["to"], r["to_key"], r["from"], r["from_key"]
        if holder == ent:
            ref = model["entities"][ref_ent]
            out.append({"col": col, "ref_table": ref["table"], "ref_col": ref_key,
                        "ref_type": _pk_sqltype(ref)})
    return out


def _col_sqltype(e, prop, col, fk_type):
    """Explicit column_types > FK-matched type > name inference."""
    return (e.get("column_types") or {}).get(prop) or fk_type.get(col) or _coltype(prop, col, e)


def _partition_clause(model, ent, e):
    """The PARTITION BY clause for one entity's `partition` block, or ''.

    v1 supports the three lifecycle-justified families (Phase-1 spec):
    interval (time-series TTL — metadata-only DROP PARTITION), auto_list
    (enumerable categories, the proven single_table mechanism), and hash
    (spread). An interval partition needs an initial boundary; time-typed
    columns get a documented far-past default, anything else must declare
    `initial` explicitly — a silently wrong boundary is a wrong design.
    """
    part = e.get("partition")
    if not part:
        return ""
    raw = part.get("column")
    col = (e.get("columns") or {}).get(raw, raw)
    by = part.get("by")
    if by == "auto_list":
        seed = part.get("seed_value", "__seed__")
        seed = seed if isinstance(seed, (int, float)) else f"'{seed}'"
        return f"\nPARTITION BY LIST ({col}) AUTOMATIC (PARTITION p_seed VALUES ({seed}))"
    if by == "hash":
        return f"\nPARTITION BY HASH ({col}) PARTITIONS {int(part.get('partitions', 8))}"
    if by == "interval":
        init = part.get("initial")
        if not init:
            fk = {f["col"]: f["ref_type"] for f in _fks_on(model, ent)}
            prop = next((p for p, c in (e.get("columns") or {}).items()
                         if c == col), col)
            t = str(_col_sqltype(e, prop, col, fk)).upper()
            if t.startswith(("TIMESTAMP", "DATE")):
                init = "TIMESTAMP '2000-01-01 00:00:00'"
            else:
                raise ValueError(
                    f"interval partition on non-time column {ent}.{col} needs an "
                    f"explicit 'initial' boundary")
        return (f"\nPARTITION BY RANGE ({col}) INTERVAL ({part['interval']}) "
                f"(PARTITION p0 VALUES LESS THAN ({init}))")
    raise ValueError(f"unsupported partition strategy: {by!r}")


def _organization_clause(model, ent, e):
    """The ORGANIZATION INDEX clause for one entity's storage, or ''.

    Clause order is probe-pinned, not guessed: `ORGANIZATION INDEX
    [PCTTHRESHOLD n] [INCLUDING col] OVERFLOW` was created live on 26ai Free
    (23.26.2) in exactly this order, and OVERFLOW is emitted whenever either
    overflow option is declared — the split row has to have somewhere to go.
    The compositions an IOT cannot enter are refused by validate_model rather
    than here: row compression is ORA-00922, every partition family but hash
    is ORA-25198, and a multivalue index on an IOT is ORA-61714 (so an IOT
    carries no hybrid flex properties).
    """
    if (e.get("organization") or "heap") != "index":
        return ""
    out = "\nORGANIZATION INDEX"
    pct, inc = e.get("pctthreshold"), e.get("including")
    if pct is not None:
        out += f" PCTTHRESHOLD {int(pct)}"
    if inc:
        out += f" INCLUDING {(e.get('columns') or {}).get(inc, inc)}"
    # OVERFLOW is UNCONDITIONAL: name-inferred VARCHAR2(4000) columns make a
    # >50%-of-block max row the common case, and an IOT without an overflow
    # segment then cannot even be created (live-isolated: ORA-01429 on the
    # hash-partitioned form). An empty overflow segment on a narrow table is
    # cheap; a failed CREATE on a real one is not.
    return out + " OVERFLOW"


def _compress_clause(e):
    """`ROW STORE COMPRESS ADVANCED` for one entity's `compress` block, or ''.
    ADVANCED is the only tier v1 emits: BASIC compresses on bulk load only and
    conventional updates decompress the block, and HCC is storage-gated off
    Free (ORA-64307)."""
    return "\nROW STORE COMPRESS ADVANCED" if e.get("compress") == "advanced" else ""


def _index_local(model, ent, partition):
    """' LOCAL' when this entity's table is partitioned and its policy asks
    for local index maintenance (the default) — '' otherwise. The knob that
    disables partitioning disables locality with it: an index must be built
    exactly as the table it serves is."""
    e = (model.get("entities") or {}).get(ent) or {}
    part = e.get("partition")
    return " LOCAL" if partition and part and part.get("local_indexes", True) else ""


def hybrid_table(e):
    """The hybrid lane's OWN table for an entity. Sharing the entity tables
    would let the flex column perturb relational's row width mid-measurement —
    the election measures designs, so each design owns its storage."""
    return f"{e['table']}_h"


def _relational_ddl(model, hybrid=False, flex_limit=8192, partition=True,
                    suffix="", iot=True, compress=True):
    """The base-table DDL. `hybrid=True` emits the hybrid lane instead: the
    same relational core on `<table>_h` tables, minus the properties the
    hybrid projection moves into a per-entity `flex JSON (OBJECT)` column,
    emitted with a `LIMIT n` inline guarantee (23.7+) so a flex document can
    never cross the OSON inline threshold into LOB storage — the measured
    decay hazard becomes impossible by construction. `flex_limit=None` drops
    the clause.

    Every base-table lane shares this emitter, so the storage dimensions
    compose identically on all three: after the column list, in probe-pinned
    order, the organization clause, then the compression clause, then the
    partition clause. `iot=False` / `compress=False` suppress their blocks."""
    tables, alters = [], []
    sfx = "_h" if hybrid else suffix
    for ent, e in model["entities"].items():
        tbl = e["table"] + sfx
        flex = hybrid_flex_props(model, ent) if hybrid else set()
        flex_cols = {(e.get("columns") or {}).get(p, p) for p in flex}
        composite = isinstance(e["pk"], list)
        pk_cols = _pk_list(e)
        fks = _fks_on(model, ent)
        if sfx:
            fks = [{**f, "ref_table": f"{f['ref_table']}{sfx}"} for f in fks]
        fk_type = {f["col"]: f["ref_type"] for f in fks}
        seen, cols = set(), []

        if not composite:
            pk = e["pk"]
            seen.add(pk)
            declared = _pk_declared_type(e)
            if e.get("pk_type"):
                cols.append(f"  {pk} {e['pk_type']} PRIMARY KEY")   # typed, non-identity
            elif declared and not declared.upper().startswith("NUMBER"):
                # a natural (code/date) key: keep its type, no identity
                cols.append(f"  {pk} {declared} PRIMARY KEY")
            elif declared:
                cols.append(f"  {pk} {declared} GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
            else:
                cols.append(f"  {pk} NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
        else:
            for pkc in pk_cols:                                     # composite: type each key col
                seen.add(pkc)
                cols.append(f"  {pkc} {_col_sqltype(e, pkc, pkc, fk_type)}")

        for prop, col in (e.get("columns") or {}).items():
            if col in seen or prop in flex or col in flex_cols:
                continue
            seen.add(col)
            cols.append(f"  {col} {_col_sqltype(e, prop, col, fk_type)}")

        if flex:
            # LIMIT lives INSIDE the type-constraint parens — live-verified on
            # 26ai Free (23.26.2): `JSON (OBJECT) LIMIT n` raises ORA-03099;
            # `JSON (OBJECT LIMIT n)` builds, and an oversize insert is
            # rejected with ORA-42712 (the inline guarantee, enforced).
            lim = f" LIMIT {int(flex_limit)}" if flex_limit else ""
            cols.append(f"  flex JSON (OBJECT{lim})")

        for fk in fks:
            if fk["col"] not in seen:
                seen.add(fk["col"])
                cols.append(f"  {fk['col']} {fk['ref_type']}")
            alters.append(
                f"ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_{fk['col']}_fk "
                f"FOREIGN KEY ({fk['col']}) REFERENCES {fk['ref_table']} ({fk['ref_col']});")

        if composite:
            cols.append(f"  CONSTRAINT {tbl}_pk PRIMARY KEY ({', '.join(pk_cols)})")

        stmt = f"CREATE TABLE IF NOT EXISTS {tbl} (\n" + ",\n".join(cols) + "\n)"
        if iot:
            stmt += _organization_clause(model, ent, e)
        if compress:
            stmt += _compress_clause(e)
        if partition:
            stmt += _partition_clause(model, ent, e)
        tables.append(stmt + ";")
    out = "\n\n".join(tables)
    if alters:
        out += "\n\n" + "\n".join(alters)
    return out


def _pks(e):
    """PK columns, always as a list — a composite key is a LIST, and rendering it with
    str() leaks a Python repr straight into the DDL (ORA-24558)."""
    pk = e["pk"]
    return list(pk) if isinstance(pk, (list, tuple)) else [pk]


def _dv_fields(e, indent, props=None):
    """The key columns then the payload columns, one field per line. A composite key
    contributes one line per column — duality has no syntax for a tuple field.

    `props` scopes the payload to the properties the patterns actually reference. Trim the
    columns, never the KEYS: duality needs them to identify the row (a child array without its
    full PK raises ORA-40477), and the root's key is `_id`."""
    pks = _pks(e)
    lines = [f"{indent}{c} : {c}" for c in pks]
    lines += [f"{indent}{p} : {c}" for p, c in (e.get("columns") or {}).items()
              if c not in pks and (props is None or p in props)]
    return lines


def is_junction(model, name):
    """An associative entity: a composite key whose every column is another entity's key.
    `reservation_payments(reservation_id, payment_id)` is one; `legs(leg_id)` is not."""
    e = (model.get("entities") or {}).get(name) or {}
    pk = _pk_list(e) if e else []
    if len(pk) < 2:
        return False
    others = {c for n, o in model["entities"].items() if n != name for c in _pk_list(o)}
    return all(c in others for c in pk)


def _junction_far_side(model, junction, came_from):
    """The entity on the OTHER side of an M:N — the one holding the payload. Reached from a
    genuine junction table only; an M:N is written either as two 1:N edges INTO the junction
    or as an N:1 out of it, and both mean the same thing."""
    if not is_junction(model, junction):
        return []
    out = []
    for r in model.get("relationships", []):
        card = (r.get("cardinality") or "1:N").upper()
        far = None
        if r["to"] == junction and card in ("1:N", "1:1") and r["from"] != came_from:
            far = r["from"]
        elif r["from"] == junction and card == "N:1" and r["to"] != came_from:
            far = r["to"]
        if far and far in model["entities"] and far not in [f for f, _ in out]:
            out.append((far, r))
    return out


def duality_views(model, root):
    """The duality views declared for a root -> [{"view": name, "includes": {entities}}].

    A view COSTS EXACTLY WHAT IT NESTS. One view per root, covering the union of every
    pattern, makes the point read pay to assemble the itinerary read's joins — measured on
    the airline capstone at 3,257us against 451us for a lean view answering the same
    two-scalar query. So a root offers a view PER AGGREGATE, and each query reads through the
    leanest one that can answer it.

    A bare string (`duality: {Res: "reservations_dv"}`) still means one all-in view: that is
    a model saying explicitly what it wants, and it is kept.
    """
    decl = ((model.get("projections") or {}).get("duality") or {}).get(root)
    if not decl:
        return []
    if isinstance(decl, str):
        # a declared string means one all-in view, every entity, every column
        return [{"view": decl, "includes": None, "columns": None}]
    if isinstance(decl, dict):
        decl = [decl]
    return [{"view": v["view"], "includes": set(v.get("includes") or ()),
             "columns": v.get("columns")} for v in decl]


def select_duality_view(model, query):
    """The LEANEST view that can answer this query — the one nesting the fewest entities
    while still reaching every entity the query touches."""
    root = query["root"]
    refs = list(query.get("returns") or []) + [p["ref"] for p in query.get("predicates") or []]
    for a in query.get("aggregates") or []:
        if a.get("ref", "*") != "*":
            refs.append(a["ref"])
    refs += list(query.get("group_by") or [])
    need = {r.split(".", 1)[0] for r in refs if "." in r} - {root}

    best = None
    for v in duality_views(model, root):
        inc = v["includes"]
        if inc is None:                                  # the declared all-in view serves all
            cand, size = v, 10_000
        elif need <= set(inc):
            cand, size = v, len(inc)
        else:
            continue
        if best is None or size < best[1]:
            best = (cand, size)
    return best[0] if best else None


def _needed_for(model, root, includes):
    """Which parents / child branches this view must nest to reach `includes`."""
    if includes is None:                                  # declared all-in
        parents = [(p, fk) for p, fk in _parents_of(model, root)]
        children = [r for r in model.get("relationships", [])
                    if r["from"] == root
                    and (r.get("cardinality") or "1:N").upper() in ("1:N", "1:1")
                    and r["to"] not in {p for p, _ in parents}]
        return parents, children, None
    parents = [(p, fk) for p, fk in _parents_of(model, root) if p in includes]
    children = []
    for r in model.get("relationships", []):
        card = (r.get("cardinality") or "1:N").upper()
        if r["from"] != root or card not in ("1:N", "1:1"):
            continue
        child = r["to"]
        if child in {p for p, _ in parents}:
            continue
        far = {f for f, _ in _junction_far_side(model, child, root)}
        if child in includes or (far & set(includes)):
            children.append(r)
    return parents, children, set(includes)


def _parents_of(model, root):
    """(parent, fk-column-on-root) for every N:1 parent, written either way round."""
    out = []
    for r in model.get("relationships", []):
        card = (r.get("cardinality") or "1:N").upper()
        if r["from"] == root and card == "N:1":
            out.append((r["to"], r.get("from_key")))
        elif r["to"] == root and card in ("1:N", "1:1") and not is_junction(model, r["from"]):
            out.append((r["from"], r.get("to_key")))
    return out


def duality_paths(model, root, view=None):
    """Where each `Entity.prop` LIVES inside ONE duality view -> {"Ent.prop": "$.path"}.

    The shape is not flat, and it is not a free choice: a nested parent's FK column may not
    ALSO be a root scalar (ORA-40609), so `passenger_id` moves from `$.passenger_id` to
    `$.passenger.passenger_id` the moment the passenger is nested. Filter the old path and
    the query matches nothing — it does not error, it just quietly returns zero rows and
    times beautifully.

    Which means the path depends on the VIEW, not just the model: the lean view keeps the FK
    flat because it nests no parent, and the scoped view nests it. Pass the view.
    """
    e = model["entities"][root]
    paths, pks = {}, _pks(e)
    includes = view["includes"] if view else None
    parents, children, _inc = _needed_for(model, root, includes)
    parent_fks = {fk for _, fk in parents if fk}

    for prop, col in (e.get("columns") or {}).items():
        if col in pks:
            continue
        if col in parent_fks:
            owner = next(p for p, fk in parents if fk == col)
            paths[f"{root}.{prop}"] = f"$.{owner.lower()}.{col}"      # moved into the parent
        else:
            paths[f"{root}.{prop}"] = f"$.{prop}"

    for parent, _fk in parents:
        pe = model["entities"][parent]
        for prop, _col in (pe.get("columns") or {}).items():
            paths[f"{parent}.{prop}"] = f"$.{parent.lower()}.{prop}"
        for c in _pks(pe):
            paths[f"{parent}.{c}"] = f"$.{parent.lower()}.{c}"

    for r in children:
        child = r["to"]
        arr = f"$.{child.lower()}s"
        for prop, _col in (model["entities"][child].get("columns") or {}).items():
            paths[f"{child}.{prop}"] = f"{arr}[*].{prop}"
        for far, _rel in _junction_far_side(model, child, root):
            if includes is not None and far not in includes:
                continue
            fe = model["entities"][far]
            for prop, _col in (fe.get("columns") or {}).items():
                paths[f"{far}.{prop}"] = f"{arr}[*].{far.lower()}.{prop}"
    return paths


def _duality_view_ddl(model, root, view=None):
    """ONE duality view, nesting exactly the aggregate it is scoped to — root scalars, the
    parents it needs (objects), the child collections it needs (arrays), and the far side of
    any junction it must reach. A view costs exactly what it nests, so it nests no more."""
    e = model["entities"][root]
    specs = duality_views(model, root)
    if view is None:
        if not specs:
            raise ValueError(f"no duality projection for {root!r}")
        view = specs[0]
    name, includes = view["view"], view["includes"]
    cols = view.get("columns")            # {entity: [props]} — None means every column
    pks = _pks(e)
    parents, children, _inc = _needed_for(model, root, includes)
    parent_fks = {fk for _, fk in parents if fk}

    def props_of(ent):
        return None if cols is None else cols.get(ent, [])

    lines = [f"CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW {name} AS",
             f"{e['table']} @insert @update @delete", "{"]
    if len(pks) == 1:
        lines.append(f"  _id : {pks[0]}")
    else:
        lines += [f"  {c} : {c}" for c in pks]        # composite key: no single _id
    root_props = props_of(root)
    for prop, col in (e.get("columns") or {}).items():
        # A nested parent's FK may NOT also be a root scalar — ORA-40609. When the parent is
        # NOT nested (the lean view), the FK stays flat and the filter keeps its cheap path.
        if col in pks or col in parent_fks:
            continue
        if root_props is not None and prop not in root_props:
            continue                     # nobody queries it — do not carry it
        lines.append(f"  {prop} : {col}")

    for parent, _fk in parents:
        pe = model["entities"][parent]
        lines.append(f"  {parent.lower()} : {pe['table']} @noinsert @update @nodelete")
        lines.append("  {")
        lines += _dv_fields(pe, "    ", props_of(parent))
        lines.append("  }")

    for r in children:
        child = model["entities"][r["to"]]
        lines.append(f"  {r['to'].lower()}s : {child['table']} @insert @update @delete")
        lines.append("  [ {")
        lines += _dv_fields(child, "      ", props_of(r["to"]))   # full child PK (ORA-40477)
        # THE JOIN. A junction's far side carries the payload — the flight number, the
        # payment amount. Nest the junction and stop and the view returns `[{res_id, leg_id}]`:
        # the keys and nothing else, doing none of the work the query asked for.
        #
        # A NAMED nested object, deliberately not @unnest: on 26ai an @unnest block omitting
        # the far-side PK raises ORA-00600 [qjsnbzoUpdateRow:zero_pk_cols] and KILLS THE
        # SESSION on update; putting the PK inside it collides with the junction's own copy
        # (ORA-40473). The named object carries the key in its own scope and does both.
        for far, _rel in _junction_far_side(model, r["to"], root):
            if includes is not None and far not in includes:
                continue                     # not in this aggregate — do not pay for it
            fe = model["entities"][far]
            lines.append(f"      {far.lower()} : {fe['table']} @noinsert @noupdate @nodelete")
            lines.append("      {")
            lines += _dv_fields(fe, "        ", props_of(far))
            lines.append("      }")
        lines.append("  } ]")
    lines.append("};")
    return "\n".join(lines)


def json_returning(model, ent, prop):
    """The RETURNING type for a JSON functional index / JSON_VALUE predicate on one property.

    Oracle uses a functional index on a JSON collection only when the query's expression
    matches the index's expression EXACTLY — function, path AND returning type. So the query
    generator and the index generator must derive the type from this one place; if they ever
    disagree, the index is built, ignored, and the collection full-scans in silence.

    The type is resolved the SAME way the relational DDL resolves it — explicit
    `column_types`, then the referenced PK's type for an FK column, then name inference.
    `passenger_id` is a NUMBER because it references `passengers.passenger_id`, and no amount
    of staring at the name will tell you that; guessing from the name alone types it VARCHAR2
    and the index dies.

    TIMESTAMP is deliberately not emitted: JSON has no timestamp type, so the value is a
    string in the document and NUMBER/VARCHAR2 are the honest choices.
    """
    e = (model.get("entities") or {}).get(ent) or {}
    if not e:
        return None
    col = (e.get("columns") or {}).get(prop, prop)
    if col in _pk_list(e):
        t = _pk_sqltype(e)
    else:
        fk = {f["col"]: f["ref_type"] for f in _fks_on(model, ent)}
        t = _col_sqltype(e, prop, col, fk)
    return "NUMBER" if t == "NUMBER" else None


def json_value_expr(model, ent, prop, alias="d", path=None):
    """The canonical JSON_VALUE expression — now the documented LAST RESORT.

    Dot notation first (see dot_pred_expr / dot_typed_expr): simple dot compiles
    to a JSON_VALUE(... TYPE(STRICT)) recheck over a multivalue index — the same
    semantics the Mongo API uses — so both lanes share ONE index, and the JSON
    type is preserved instead of coerced through RETURNING. JSON_VALUE RETURNING
    remains only where an explicit SQL type genuinely must be forced: the `_id`
    point read (scalar ids, live-measured against its functional index) and the
    duality lane (whose base-column rewrite evidence is for these forms).

    `path` overrides WHERE the value lives (a duality view nests, so
    `passenger_id` sits at `$.passenger.passenger_id`) while `ent`/`prop` still
    decide its TYPE — keep those coupled or a nested path silently loses its
    RETURNING NUMBER."""
    ret = json_returning(model, ent, prop)
    src = f"{alias}.data" if alias else "data"
    p = path or f"$.{prop}"
    return f"JSON_VALUE({src}, '{p}' RETURNING {ret})" if ret else f"JSON_VALUE({src}, '{p}')"


def dot_pred_expr(prop, alias="d", col="data"):
    """The PREDICATE side of dot-notation-first: PLAIN dot, no item method.

    Field-verified (26ai + ORDS, 2026-07): `d.data.f = 'x'` compiles to a
    JSON_VALUE(... TYPE(STRICT)) recheck over the multivalue index access and is
    served by the SAME multivalue index a Mongo `createIndex`/`find` uses. An
    item method on the predicate (`.string() =`) coerces with different
    semantics and LOSES the index match — plain dot is the sweet spot.

    `col` names the JSON column the dot path starts from — `data` for a
    collection, `flex` for the hybrid lane's extension column."""
    src = f"{alias}.{col}" if alias else col
    return f"{src}.{prop}"


def dot_typed_expr(model, ent, prop, alias="d", col="data"):
    """The typed item-method dot expression for the sides that NEED a SQL type —
    the multivalue index definition, aggregation arguments/keys, ORDER BY —
    preserving the JSON type instead of flattening through JSON_VALUE RETURNING.
    Typed from the model exactly like json_value_expr, so the pair cannot drift:
    NUMBER props -> .numberOnly(), everything else -> .string(). (Our generated
    documents carry date-ish values as strings by design — json_returning emits
    no TIMESTAMP; native-date collections use .dateTimeOnly(), see the skills.)"""
    method = "numberOnly" if json_returning(model, ent, prop) == "NUMBER" else "string"
    src = f"{alias}.{col}" if alias else col
    return f"{src}.{prop}.{method}()"


def agg_expr(model, ref, shape, numeric=False, alias="d"):
    """The ONE expression an aggregation uses for a GROUP BY key or an aggregate argument.

    The query generator and the index generator both call this, because an index whose
    expression differs from the query's by a single character is built, valid, and silently
    ignored — a defect that has now bitten the document's JSON index (VARCHAR2 vs NUMBER) and
    the single table's TO_NUMBER wrap.

    A numeric argument is pinned with RETURNING NUMBER: JSON_VALUE defaults to VARCHAR2, and
    SUM of that coerces or raises.
    """
    ent, prop = ref.split(".", 1)
    e = (model.get("entities") or {}).get(ent) or {}
    # NOT duality: a duality view cannot express a GROUP BY (it must stay updatable), so an
    # aggregation reads through the read-only sql_view projection — which is a JSON wrapper
    # over the BASE TABLES. Its index is therefore a plain relational index on those columns;
    # index a JSON path on `itinerary_reservations` and you get ORA-00904: "DATA" invalid.
    if shape == "document":
        # Typed item-method dot, not JSON_VALUE RETURNING: SUM/AVG still get a
        # SQL NUMBER (.numberOnly()), GROUP BY keys a VARCHAR2 (.string()), and
        # the derived index carries the identical expression.
        if numeric:
            src = f"{alias}.data" if alias else "data"
            return f"{src}.{prop}.numberOnly()"
        return dot_typed_expr(model, ent, prop, alias=alias)
    if shape == "hybrid" and prop in hybrid_flex_props(model, ent):
        # The flex side of the hybrid split follows the document doctrine —
        # typed item-method dot on the flex column, identical on the query
        # and index sides.
        if numeric:
            src = f"{alias}.flex" if alias else "flex"
            return f"{src}.{prop}.numberOnly()"
        return dot_typed_expr(model, ent, prop, alias=alias, col="flex")
    col = prop if prop in _pk_list(e) else (e.get("columns") or {}).get(prop, prop)
    if shape == "hybrid" and alias:
        return f"{alias}.{col}"
    if shape == "single_table":
        return col
    return col


def agg_index_columns(model, query, shape):
    """The covering index an aggregation implies: every GROUP BY key, then every aggregate
    ARGUMENT, then a trailing constant.

    Index derivation only ever looked at FILTER predicates, so a GROUP BY key never got an
    index and every aggregation scanned the whole table or collection. On a JSON collection
    that means dragging every embedded leg and payment past the CPU to read one status field:
    15,479us and 3,359 logical reads, against 1,789us and 102 with the index.

    THE TRAILING CONSTANT is the trick. A B-tree omits an entry whose key is entirely NULL, so
    Oracle will not use it for COUNT(*) — any row might be missing the key. `(expr, 0)` makes
    the entry never wholly NULL, so the index holds EVERY row and can be fast-full-scanned.
    No query change and no semantic change: the NULL group is still counted.
    """
    if not (query.get("group_by") or query.get("aggregates")):
        return []

    def _on_root(ref):
        # A relational/duality/hybrid agg index is built ON the root's table; a non-root
        # ref's column lives on another table and the CREATE would raise ORA-00904. (The
        # converged single table holds every entity's columns, so no filter there.)
        return (shape not in ("relational", "duality", "hybrid", "summary")
                or ref.split(".", 1)[0] == query.get("root"))
    cols = [agg_expr(model, r, shape, alias=None)
            for r in (query.get("group_by") or []) if _on_root(r)]
    for a in (query.get("aggregates") or []):
        ref = a.get("ref", "*")
        if ref == "*" or not _on_root(ref):
            continue
        numeric = str(a.get("fn", "")).upper() in ("SUM", "AVG")
        e = agg_expr(model, ref, shape, numeric=numeric, alias=None)
        if e not in cols:
            cols.append(e)
    return (cols + ["0"]) if cols else []


def _resolve_col(model, ref):
    ent, prop = ref.split(".", 1)
    e = model["entities"][ent]
    pk = e["pk"]
    if prop == pk or (isinstance(pk, list) and prop in pk):
        return ent, prop, True   # a PK column — already indexed
    return ent, (e.get("columns") or {}).get(prop, prop), False


def generate_indexes(model, queries, shape="relational", partition=True) -> str:
    """Candidate indexes DERIVED from the access patterns — their FILTERS *and* their
    AGGREGATIONS.

    Access-pattern-first: each query's predicate columns on an entity imply an
    index on those filter columns — composite when one query filters an entity on
    several columns (a single-column index won't serve a combined predicate). PK
    columns are already indexed and skipped; equality/range predicates are indexed,
    IS [NOT] NULL is not. Whether an index actually wins depends on selectivity and
    data volume — measure on a representative sample.

    shape 'relational'/'duality' -> B-tree on the base columns; 'document' -> a
    function index on the JSON filter path.
    """
    seen, stmts = set(), []
    for q in queries:
        # AN AGGREGATION IMPLIES AN INDEX TOO. Deriving from filters alone left every GROUP BY
        # scanning the whole object — which is how "documents cannot aggregate" got into the
        # capstone as a finding, when it was a missing index (15,479us -> 1,789us, and fewer
        # logical reads than the relational table).
        agg_cols = agg_index_columns(model, q, shape)
        if shape == "summary" and summary_mv_for(model, q):
            # the MV IS the covering structure for a matched aggregation —
            # deriving a B-tree beside it would index a read nobody runs
            agg_cols = []
        if agg_cols:
            root = q.get("root")
            e = model["entities"].get(root) or {}
            if shape == "document":
                doc = ((model.get("projections") or {}).get("document") or {}).get(root)
                obj = doc["collection"] if doc else f"{e.get('table')}_docs"
            elif shape == "single_table":
                st = (model.get("projections") or {}).get("single_table") or {}
                obj = st.get("table", "converged_items")
            elif shape == "hybrid":
                obj = f"{e.get('table')}_h" if e.get("table") else None
            elif shape == "summary":
                obj = f"{e.get('table')}_s" if e.get("table") else None
            else:
                obj = e.get("table")
            if obj:
                key = (obj, tuple(agg_cols), shape)
                if key not in seen:
                    seen.add(key)
                    # NAME IT FOR ITS COLUMNS, not for the root: three aggregations over the
                    # same entity would otherwise generate three indexes with the SAME name,
                    # and the second and third raise ORA-00955 — which the runner tolerates as
                    # "already exists" and swallows. That is the defect that left relational
                    # with no indexes at all; do not reintroduce it two functions later.
                    props = [r.split(".", 1)[1] for r in (q.get("group_by") or [])]
                    props += [a["ref"].split(".", 1)[1]
                              for a in (q.get("aggregates") or []) if a.get("ref", "*") != "*"]
                    tag = re.sub(r"[^a-z0-9]+", "_", "_".join(props).lower()) or "agg"
                    nm = f"{obj}_agg_{tag}_ix"[:128]
                    loc = (_index_local(model, root, partition)
                           if shape in ("relational", "duality", "hybrid") else "")
                    stmts.append(f"CREATE INDEX {nm} ON {obj} ({', '.join(agg_cols)}){loc};")

        by_ent = {}
        for p in q.get("predicates", []) or []:
            op = str(p.get("op", "=")).upper()
            if op in ("IS NULL", "IS NOT NULL"):
                continue
            ent, col, is_pk = _resolve_col(model, p["ref"])
            if is_pk:
                # A relational PK is already indexed — but a DOCUMENT filters on
                # JSON_VALUE(data,'$._id' RETURNING NUMBER), which has no index by
                # default. Skipping it makes the document full-scan the id point read
                # (its signature pattern) and biases every comparison toward relational.
                # The expression must match the generated predicate EXACTLY to be used.
                if shape == "document" and ent == q.get("root"):
                    doc = ((model.get("projections") or {}).get("document") or {}).get(ent)
                    if doc:
                        coll = doc["collection"]
                        path = doc.get("id_path", "$._id")
                        key = (coll, ("__id__",), shape)
                        if key not in seen:
                            seen.add(key)
                            # Typed from the declared pk via the SAME helper the predicate
                            # uses — hardcoded RETURNING NUMBER gave a VARCHAR2 pk an index
                            # expression its own point read never matches.
                            prop = p["ref"].split(".", 1)[1]
                            expr = json_value_expr(model, ent, prop, alias=None, path=path)
                            stmts.append(
                                f"CREATE INDEX {coll}_id_ix ON {coll} ({expr});")
                continue
            prop = p["ref"].split(".", 1)[1]
            # AN ARRAY PREDICATE NEEDS A MULTIVALUE INDEX. The query side filters an array
            # with JSON_EXISTS('$.tags?(@ == "red")') — same helper-coupled reason as
            # everywhere else in this module: JSON_VALUE of an array is NULL for every row,
            # so the scalar functional index this loop would derive is all-NULL dead weight
            # and the contains query full-scans the collection forever. The runtime-verified
            # serving form (tests/test_pattern_catalog_live.py; field-measured 4,110 vs
            # 572 q/s) is MULTIVALUE over the array elements, typed like the values.
            if shape == "document" and is_array_prop(model, ent, prop, q):
                doc = ((model.get("projections") or {}).get("document") or {}).get(ent)
                coll = doc["collection"] if doc else f"{model['entities'][ent]['table']}_docs"
                key = (coll, (f"{prop}[*]",), shape)
                if key not in seen:
                    seen.add(key)
                    typ = "number" if json_returning(model, ent, prop) == "NUMBER" else "string"
                    stmts.append(f"CREATE MULTIVALUE INDEX {coll}_{prop}_mv_ix "
                                 f"ON {coll} t (t.data.{prop}[*].{typ}());")
                continue
            # A flex ARRAY in the hybrid lane is the same containment question,
            # over the flex column instead of the whole document.
            if (shape == "hybrid" and is_array_prop(model, ent, prop, q)
                    and prop in hybrid_flex_props(model, ent)):
                tbl = f"{model['entities'][ent]['table']}_h"
                key = (tbl, (f"{prop}[*]",), shape)
                if key not in seen:
                    seen.add(key)
                    typ = "number" if json_returning(model, ent, prop) == "NUMBER" else "string"
                    stmts.append(f"CREATE MULTIVALUE INDEX {tbl}_{prop}_mv_ix "
                                 f"ON {tbl} t (t.flex.{prop}[*].{typ}());")
                continue
            by_ent.setdefault(ent, [])
            entry = (col, prop)
            if entry not in by_ent[ent]:
                by_ent[ent].append(entry)
        for ent, entries in by_ent.items():
            if not entries:
                continue
            e = model["entities"][ent]
            # NAME IT FOR THE OBJECT IT IS BUILT ON. Named for the entity's TABLE regardless
            # of shape, the document's index on `res_docs` claimed the name the relational
            # index on `reservations` needed — and the second CREATE raised ORA-00955, which
            # the runner tolerates as "already exists" and swallows. Relational then had NO
            # access-pattern indexes and full-scanned every filtered read, in every run.
            if shape == "document":
                # MULTIVALUE with the typed item method, ONE INDEX PER FIELD: a
                # composite multivalue over scalars is invalid SQL (ORA-44981 —
                # composite multivalue columns must come from JSON_TABLE;
                # field-verified, it blocked an entire run). Per-field is legal,
                # is exactly what a Mongo createIndex produces (one shared index
                # per field, both lanes), and DEDUPES on (collection, field) —
                # a duplicate CREATE raises ORA-01408, the runner tolerates it
                # as "already exists", and verify_indexes then aborts the run.
                doc = ((model.get("projections") or {}).get("document") or {}).get(ent)
                coll = doc["collection"] if doc else f"{e['table']}_docs"
                for col, prop in entries:
                    key = (coll, (prop,), shape)
                    if key in seen:
                        continue
                    seen.add(key)
                    name = (f"{coll}_{col}_ix")[:128]
                    stmts.append(f"CREATE MULTIVALUE INDEX {name} ON {coll} t "
                                 f"({dot_typed_expr(model, ent, prop, alias='t')});")
            elif shape == "hybrid":
                # The core/flex split carries into index derivation: flex
                # properties follow the document doctrine (per-field MULTIVALUE
                # with the typed item method — composite multivalue is
                # ORA-44981), core properties stay a composite B-tree exactly
                # like relational — both on the hybrid lane's own table.
                tbl = f"{e['table']}_h"
                flex = hybrid_flex_props(model, ent)
                for col, prop in entries:
                    if prop not in flex:
                        continue
                    key = (tbl, (prop,), shape)
                    if key in seen:
                        continue
                    seen.add(key)
                    name = (f"{tbl}_{col}_ix")[:128]
                    stmts.append(f"CREATE MULTIVALUE INDEX {name} ON {tbl} t "
                                 f"({dot_typed_expr(model, ent, prop, alias='t', col='flex')});")
                core = [c for c, p in entries if p not in flex]
                if core:
                    key = (tbl, tuple(core), shape)
                    if key not in seen:
                        seen.add(key)
                        name = (f"{tbl}_{'_'.join(core)}_ix")[:128]
                        loc = _index_local(model, ent, partition)
                        stmts.append(f"CREATE INDEX {name} ON {tbl} "
                                     f"({', '.join(core)}){loc};")
            else:
                cols = [c for c, _ in entries]
                tbl = e["table"] + ("_s" if shape == "summary" else "")
                key = (tbl, tuple(cols), shape)
                if key in seen:
                    continue
                seen.add(key)
                name = (f"{tbl}_{'_'.join(cols)}_ix")[:128]
                loc = (_index_local(model, ent, partition)
                       if shape in ("relational", "duality", "summary") else "")
                stmts.append(f"CREATE INDEX {name} ON {tbl} "
                             f"({', '.join(cols)}){loc};")

        # JOIN KEYS ARE ACCESS PATHS TOO. A read that reaches a child joins on
        # the child's FK, and a child write scopes by it — but the FK never
        # appears as a predicate, so it derived NO index: get_booking
        # full-scanned two designs, and the write-path version of the same gap
        # cost 367ms at 775k rows (16ms at small scale, where it read as
        # "write amplification"). Base-table lanes only — the document embeds
        # its children, and the single table co-locates by anchor.
        if shape in ("relational", "duality", "hybrid", "summary"):
            suffix = {"hybrid": "_h", "summary": "_s"}.get(shape, "")
            root = q.get("root")
            refs = list(q.get("returns") or []) + \
                [p["ref"] for p in q.get("predicates") or []] + \
                list(q.get("group_by") or []) + \
                [a["ref"] for a in q.get("aggregates") or [] if a.get("ref", "*") != "*"]
            touched = {r.split(".", 1)[0] for r in refs if "." in r} - {root}
            for rel in model.get("relationships", []):
                card = (rel.get("cardinality") or "1:N").upper()
                if card in ("1:N", "1:1") and rel["from"] == root and rel["to"] in touched:
                    child = model["entities"][rel["to"]]
                    fk = rel["to_key"]
                    tbl = child["table"] + suffix
                    key = (tbl, (fk,), shape)
                    if fk in _pk_list(child) or key in seen:
                        continue
                    seen.add(key)
                    loc = _index_local(model, rel["to"], partition)
                    stmts.append(f"CREATE INDEX {tbl}_{fk}_ix "
                                 f"ON {tbl} ({fk}){loc};")
    return "\n".join(stmts)


def _single_table_ddl(model, sparse=True, partition_by_type=True):
    """One shared table for heterogeneous item types — the converged realization of
    a DynamoDB single-table design. A `type` discriminator, the union of the types'
    columns (sparse/nullable, natively typed — no concatenated string keys), and
    multi-column indexes: a composite-key index per type (the item-collection /
    base-table access) plus every GSI-derived index. Co-locates related types so an
    anchor query returns them in one indexed read — and it is still SQL, so joins
    and aggregations work on the same table."""
    st = (model.get("projections") or {}).get("single_table")
    if not st:
        raise ValueError("model has no single_table projection")
    table = st["table"]
    disc = st.get("discriminator", "type")

    # Somebody's PRIMARY KEY is authoritative for that column name, everywhere. `passenger_id`
    # is a NUMBER because it is Passenger's key — a fact that lives in the model, not in the
    # name. Type it by inference and it lands VARCHAR2 in the converged table; every numeric
    # filter then silently wraps in TO_NUMBER, which precludes the index. Oracle says so in
    # the plan: "predicates which preclude their use as keys in index range scan." The index
    # is built, valid, and unusable. (Exactly the defect that crippled the document's JSON
    # index — inference without key/FK context.)
    pk_types = {}
    for _ent, _e in model["entities"].items():
        if not isinstance(_e["pk"], list):
            pk_types.setdefault(_e["pk"], _pk_sqltype(_e))

    cols, types, from_pk = {}, {}, set()
    for ent, e in model["entities"].items():
        # explicit column_types > FK-matched type > the referenced PK's type > name inference
        fk_type = {f["col"]: f["ref_type"] for f in _fks_on(model, ent)}
        for prop, col in (e.get("columns") or {}).items():
            cols.setdefault(col, True)
            ct = ((e.get("column_types") or {}).get(prop) or fk_type.get(col)
                  or pk_types.get(col) or _coltype(prop, col, e))
            if col not in types or col in from_pk:
                types[col] = ct
                from_pk.discard(col)
        # Each entity's KEY must be a real column here — the per-type key index refers to
        # it. A DynamoDB-ingested model already carries its keys in `columns`; a
        # relational model keeps the PK separate, so fold it in explicitly.
        for pk in _pk_list(e):
            cols.setdefault(pk, True)
            if pk not in types:
                types[pk] = _pk_sqltype(e)
                from_pk.add(pk)

    lines = ["  item_id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
             f"  {disc} VARCHAR2(60) NOT NULL"]
    for col in cols:
        if col == disc:
            continue
        lines.append(f"  {col} {types.get(col, 'VARCHAR2(4000)')}")
    create = f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(lines) + "\n)"
    if partition_by_type:
        # Automatic list partitioning by the discriminator: each item type lands in
        # its own partition (auto-created on first insert of a new type), so reads
        # filtered by type prune to one partition and each type is physically isolated.
        create += f"\nPARTITION BY LIST ({disc}) AUTOMATIC (PARTITION p_seed VALUES ('__seed__'))"
    out = [create + ";"]

    local = " LOCAL" if partition_by_type else ""

    def _cols(index_cols, t, sparse_ok=True):
        # Sparse: type-filter each column so the index holds ONLY this type's rows
        # (Oracle omits all-NULL keys) — the native analog of a DynamoDB sparse GSI,
        # so an insert of another type never touches this index.
        #
        # But a SPARSE index cannot serve a read that spans SEVERAL types: that read filters
        # on the plain column and matches no CASE expression, so it scans. Such an index must
        # be non-sparse, and carry the discriminator so the type predicate still prunes.
        if sparse and sparse_ok:
            return ", ".join(f"CASE WHEN {disc} = '{t}' THEN {c} END" for c in index_cols)
        if sparse and not sparse_ok:
            # deliberately non-sparse: carry the discriminator so a type predicate still prunes
            return ", ".join(list(index_cols) + [disc])
        return ", ".join(index_cols)          # sparse disabled model-wide

    out2 = []
    # THE ANCHOR INDEX — the single table's defining access path, and the direct analog of
    # a DynamoDB PK+SK. The per-type indexes below are SPARSE (type-filtered), so not one
    # of them can serve an item-collection read, which spans several types at once: that
    # read would full-scan, and the design would lose the very query it exists to win. This
    # index is deliberately NOT sparse and NOT local — one range scan on (anchor, type)
    # returns the reservation and its legs and its payments, co-located and in key order.
    anchor = st.get("anchor")
    akey = ((st.get("types") or {}).get(anchor) or {}).get("key") if anchor else None
    if akey:
        cols = ", ".join(list(akey) + [disc])
        out2.append(f"CREATE INDEX {table}_anchor_ix ON {table} ({cols});")

    seen = set()
    # composite-key index per type — the full key, anchor-first, so a single-type read
    # (WHERE type = 't' AND key = ?) probes exactly this type's rows and nothing else.
    for t, spec in (st.get("types") or {}).items():
        key = spec.get("key", [])
        if key and (t, tuple(key)) not in seen:
            seen.add((t, tuple(key)))
            tn = re.sub(r"\W+", "_", t).lower()
            out.append(f"CREATE INDEX {table}_{tn}_k_ix ON {table} ({_cols(key, t)}){local};")
    # GSI-derived multi-column indexes
    for i in st.get("indexes", []) or []:
        # SPARSITY IS PART OF THE IDENTITY. The same columns may need BOTH a sparse index (for
        # the single-type read, which filters through the CASE expression) and a non-sparse one
        # (for the multi-type read, which filters on the plain column). Dedupe on the columns
        # alone and the second variant is dropped — and its read full-scans.
        key_i = (i.get("type"), tuple(i.get("columns") or ()), bool(i.get("sparse", True)))
        if not i.get("columns") or key_i in seen:
            continue
        seen.add(key_i)
        name = f"{table}_{i['name']}"[:128]
        sparse_ok = i.get("sparse", True)
        loc = local if sparse_ok else ""      # a cross-type index must not be LOCAL to a type
        out.append(f"CREATE INDEX {name} ON {table} "
                   f"({_cols(i['columns'], i['type'], sparse_ok)}){loc};")
    return "\n\n".join(out[:1] + out2 + out[1:])


def _summary_ddl(model, partition=True, iot=True, compress=True):
    """The summary lane: `_s` copies of the relational core, one MV log per
    base table (column sets MERGED across the MVs it feeds — a second CREATE
    LOG on the same table is an error, not a merge), and one REFRESH FAST ON
    COMMIT aggregate MV per declared summary. Probe-verified on 26ai Free
    23.26.2: aggregate ON STATEMENT MVs are rejected (ORA-32428, join-shape
    only); ON COMMIT + log builds and maintains; IF NOT EXISTS deploys
    idempotently (duplicate = ORA-12006, tolerated). COUNT companions are
    appended per the documented fast-refresh eligibility rules: COUNT(*)
    when not declared, COUNT(<arg>) for every SUM/AVG argument."""
    proj = ((model.get("projections") or {}).get("summary") or {})
    mvs = proj.get("mvs") or []
    if not mvs:
        raise ValueError("no summary projection in the model")
    parts = [_relational_ddl(model, suffix="_s", partition=partition,
                             iot=iot, compress=compress)]

    def _col_of(ref):
        ent, prop = ref.split(".", 1)
        e = model["entities"][ent]
        return prop if prop in _pk_list(e) else (e.get("columns") or {}).get(prop, prop)

    log_cols = {}                        # table -> ordered column list
    mv_stmts = []
    for mv in mvs:
        q = mv["query"]
        root = q["root"]
        tbl = model["entities"][root]["table"] + "_s"
        groups = [_col_of(r) for r in q.get("group_by") or []]
        sel = list(groups)
        have_count_star = False
        arg_cols, agg_sel = [], []
        for a in q.get("aggregates") or []:
            fn = str(a.get("fn", "")).upper()
            ref = a.get("ref", "*")
            arg = "*" if ref == "*" else _col_of(ref)
            if fn == "COUNT" and arg == "*":
                have_count_star = True
            if arg != "*":
                arg_cols.append(arg)
            agg_sel.append(f"{fn}({arg}) AS {a['name']}")
        sel += agg_sel
        if not have_count_star:
            sel.append("COUNT(*) AS osq_cnt")
        for c in dict.fromkeys(arg_cols):
            sel.append(f"COUNT({c}) AS osq_cnt_{c}")
        cols = log_cols.setdefault(tbl, [])
        for c in groups + arg_cols:
            if c not in cols:
                cols.append(c)
        mv_stmts.append(
            f"CREATE MATERIALIZED VIEW IF NOT EXISTS {mv['name']} "
            f"REFRESH FAST ON COMMIT AS\n"
            f"SELECT {', '.join(sel)}\nFROM {tbl}\n"
            f"GROUP BY {', '.join(groups)};")
    for tbl, cols in log_cols.items():
        parts.append(f"CREATE MATERIALIZED VIEW LOG ON {tbl} WITH ROWID, "
                     f"SEQUENCE ({', '.join(cols)}) INCLUDING NEW VALUES;")
    parts += mv_stmts
    return "\n\n".join(parts)


def generate_ddl(model, shape, root=None, sparse=True, partition_by_type=True,
                 flex_limit=8192, partition=True, iot=True,
                 compress=True) -> str:
    """Return the CREATE DDL that realizes `shape` for the model.

    root selects the duality/document projection root (defaults to the sole one).
    flex_limit sets the hybrid flex column's `JSON ... LIMIT n` inline
    guarantee (None drops the clause). partition=False suppresses every
    per-entity `partition` block (the `--no-partition` knob); iot=False and
    compress=False do the same for the per-entity `organization` and
    `compress` blocks (`--no-iot` / `--no-compress`).
    """
    if shape == "relational":
        return _relational_ddl(model, partition=partition, iot=iot,
                               compress=compress)
    if shape == "hybrid":
        if not ((model.get("projections") or {}).get("hybrid") or {}).get("entities"):
            raise ValueError("no hybrid projection in the model")
        return _relational_ddl(model, hybrid=True, flex_limit=flex_limit,
                               partition=partition, iot=iot, compress=compress)
    if shape == "summary":
        return _summary_ddl(model, partition=partition, iot=iot,
                            compress=compress)
    if shape == "single_table":
        return _single_table_ddl(model, sparse=sparse, partition_by_type=partition_by_type)
    if shape == "document":
        docs = (model.get("projections") or {}).get("document") or {}
        if not docs:
            raise ValueError("no document projection in the model")
        stmts = [f"CREATE JSON COLLECTION TABLE IF NOT EXISTS {d['collection']};"
                 for d in docs.values()]
        return "\n".join(stmts)
    if shape == "duality":
        roots = list(((model.get("projections") or {}).get("duality") or {}))
        if not roots:
            raise ValueError("no duality projection in the model")
        # THE DESIGN GATES run at this single emit choke point, with the
        # optimizer's own severity split: a blocker REFUSES to emit (the view
        # cannot exist, or exists and answers wrongly); a warning emits and
        # annotates. Imported here, not at module top: validate imports this
        # module's helpers.
        from tooling.duality.validate import DualityGateError, validate_duality
        found = validate_duality(model, root=root)
        blockers = [v for v in found if v.severity == "blocker"]
        if blockers:
            raise DualityGateError(blockers)
        warns = {}
        for v in found:
            # No ';' inside a comment: deployers split the DDL on ';' and an
            # orphaned comment tail reaches the server as ORA-00900.
            warns.setdefault(v.where, []).append(
                f"-- WARN [gate-{v.gate}]: {v.message.replace(';', ',')}")
        # A duality view over a PARTITIONED base is doc-unstated territory
        # (system-partitioned/partitioned-extended bases are read-only
        # participants; plain partitioned heaps are unlisted) — deploy
        # plan-verifies and the docs disclose it as plan-proven, not promised.
        # A duality view over an INDEX-ORGANIZED base is the same posture and
        # is live-proven: it creates and answers a point read.
        base = _relational_ddl(model, partition=partition, iot=iot,
                               compress=compress)
        # EVERY view the root offers — one per aggregate, each nesting only what it needs.
        views = "\n\n".join(
            "\n".join(warns.get(v["view"], []) + [_duality_view_ddl(model, r, v)])
            for r in ([root] if root else roots)
            for v in duality_views(model, r))
        return base + "\n\n" + views
    raise ValueError(f"unknown shape: {shape!r}")

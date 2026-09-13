# Copyright (c) 2026 Oracle and/or its affiliates.
"""The measured-optimization runner — the six steps, codified.

Before this existed, choosing a schema meant hand-assembling the loop every time:
derive the indexes, deploy each candidate shape, seed it, benchmark every access
pattern against every shape, assemble the cost matrix, then decide. That is a
procedure, not a judgement call — so it belongs in code, not in a prompt.

    1. candidate_shapes  — what the model actually offers (the agent proposes the
                           candidate models; this measures whatever it declares)
    2. deploy            — DDL per shape + the indexes the ACCESS PATTERNS imply
                           (indexes FIRST: benchmarking un-indexed tables measures
                           full scans production would never run)
    3. seed              — load representative volume
    4. measure           — every pattern x every shape, on the live DB
    5. build_result      — the full cost matrix (reads AND writes as first-class
                           rows, each with its rate) -> decide
    6. winning_ddl       — emit the schema that won

**Unit discipline.** Logical reads (queries) and redo bytes (writes) are *different
units* and cannot be summed — a mistake that quietly inverts the answer. The matrix is
therefore built in one consistent unit, **median elapsed microseconds**, with logical
reads / redo captured alongside as diagnostics.
"""
import re
import statistics
import time

from tooling.generate.ddl import generate_indexes, generate_ddl
from tooling.generate.sql import (generate_candidates, generate_relational, is_aggregate,
                                  generate_update, generate_insert)
from tooling.optimize.benchparse import CV_GATE
from tooling.optimize.decide import decide_model
# The EXPLAIN mechanics live in tooling.plancheck — the SAME path query-craft's
# delivery gate reads plans through, so the measurement and the gate cannot drift.
from tooling.plancheck.check import _scanned_tables, explain, plan_access

# Tolerated on deploy: object already exists / duplicate index / etc.
_EXISTS = (955, 1430, 2260, 2264, 2275, 1408, 942, 2261, 12000, 12006, 12007)


def storage_shape(shape):
    """`sql_view` is a read-only JSON projection OVER relational storage — it is not a
    storage shape of its own. It deploys as relational, and its writes ARE relational
    writes; only its read projection differs."""
    return "relational" if shape == "sql_view" else shape


# --- 1. candidates -------------------------------------------------------------
# The consolidation walk. These four are not an arbitrary list — they are the stations
# the design moves through as write pressure climbs:
#
#     document  ->  single collection  ->  duality  ->  relational
#     (max read consolidation,          (co-located,   (relational   (normalized,
#      max write amplification)          one anchor)    storage +      cheapest
#                                                       doc API)       writes)
#
# Tuning the knob traverses that walk, so all four compete by default.
#
# `sql_view` is deliberately NOT a station: it is a read-only JSON projection over
# relational storage, so listing it beside `relational` is redundant. It survives as
# duality's fallback for what a duality view cannot express (aggregations).
#
# `hybrid` (Phase-1 spec, D3) sits between the converged single collection and
# duality: a relational core carrying its variable attributes in a JSON flex
# column — less consolidated than a single collection, more than duality's pure
# relational storage.
# `summary` (Phase-2 spec) sits between duality and relational: relational
# storage plus declared REFRESH FAST ON COMMIT aggregates — the read side of
# the precompute inequality, with its maintenance charged to the write cells.
DEFAULT_DESIGNS = ("document", "single_table", "hybrid", "duality", "summary",
                   "relational")

# TWO NOISE THRESHOLDS, TWO JOBS — and they must stay coherent:
#
#   NOISE_FLOOR (5%)  — the a-priori FLOOR on the margin BETWEEN designs. Repeated
#                       timings on a live database vary by a few percent — buffer cache,
#                       background work, the host — so a smaller margin is never a result.
#   CV_GATE (10%)     — benchparse's per-cell trust gate: how much the trials WITHIN one
#                       cell may disagree before the cell itself cannot be trusted.
#
# Coherence rule: the floor is only the floor. The measured cv of the cells a verdict
# actually rests on RAISES it — build_result reports noise_floor = max(NOISE_FLOOR,
# worst cv among the top two designs' weighted cells), and any cell above CV_GATE is
# flagged NOISY in the report. Without this, a 5.5% margin over 8-10%-cv cells prints
# "SEPARATES" while the winner flips run to run (docs/DEMO-SCRIPT.md recorded exactly
# that during rehearsal).
NOISE_FLOOR = 0.05


def propose_projections(model, patterns):
    """Offer the standard candidate models when the agent hasn't proposed its own, so the
    whole walk competes: an embedded document per query root, a duality view over the same
    relational storage, and a converged single-collection layout."""
    import copy
    m = copy.deepcopy(model)
    proj = m.setdefault("projections", {})
    roots = sorted({p["query"]["root"] for p in patterns
                    if isinstance(p.get("query"), dict) and p["query"].get("root")})
    doc = proj.setdefault("document", {})
    dv = proj.setdefault("duality", {})
    for r in roots:
        e = m["entities"].get(r)
        if not e:
            continue
        doc.setdefault(r, {"collection": f"{e['table']}_docs", "id_path": "$._id"})
        dv.setdefault(r, propose_duality_views(m, patterns, r))
    proj.setdefault("single_table", propose_single_table(m, patterns))
    if "hybrid" not in proj:
        hyb = propose_hybrid(m, patterns)
        if hyb:
            proj["hybrid"] = hyb
    if "summary" not in proj:
        summ = propose_summary(m, patterns)
        if summ:
            proj["summary"] = summ
    return m


def propose_summary(model, patterns):
    """Nominate the summary candidate by heuristic (Phase-2 spec, P2-D1): one
    MV per DISTINCT single-root aggregation signature among the read patterns
    — the precompute inequality gets priced by default, and a write-flooded
    workload simply elects against it. No aggregation patterns means no
    summary candidate."""
    from tooling.generate.sql import is_aggregate
    seen, mvs = set(), []
    for p in patterns or []:
        q = p.get("query") or {}
        if p.get("kind") == "write" or not is_aggregate(q):
            continue
        root = q.get("root")
        refs = list(q.get("group_by") or ())
        refs += [a.get("ref") for a in q.get("aggregates") or ()
                 if a.get("ref", "*") != "*"]
        if {r.split(".", 1)[0] for r in refs if "." in r} - {root}:
            continue                       # v1: single-root summaries only
        sig = (root, frozenset(q.get("group_by") or ()),
               tuple(sorted((a.get("name"), str(a.get("fn", "")).upper(),
                             a.get("ref", "*"))
                            for a in q.get("aggregates") or ())))
        if sig in seen:
            continue
        seen.add(sig)
        mvs.append({"name": f"mv_{p.get('name', 'agg')}"[:120],
                    "query": {"root": root,
                              "group_by": list(q.get("group_by") or ()),
                              "aggregates": [dict(a) for a in
                                             q.get("aggregates") or ()]}})
    return {"mvs": mvs} if mvs else None


def propose_hybrid(model, patterns):
    """Nominate the hybrid candidate by heuristic when the agent hasn't
    declared one (Phase-1 spec, D1): attributes no pattern filters, groups,
    aggregates, orders on or writes move to the flex column; the PK, every
    relationship key, and every access-path-anchored property stay typed
    columns — patterns filter/aggregate on the stable keys, point-read the
    variable attributes. Entities with nothing to move contribute nothing;
    no qualifying entity means no hybrid candidate."""
    anchored = set()
    for p in patterns or []:
        q = p.get("query") or {}
        refs = [pr.get("ref", "") for pr in q.get("predicates") or []]
        refs += list(q.get("group_by") or [])
        refs += [a["ref"] for a in q.get("aggregates") or [] if a.get("ref", "*") != "*"]
        refs += [o["ref"] for o in q.get("order_by") or [] if o.get("ref")]
        w = p.get("write") or {}
        if w.get("set_ref"):
            refs.append(w["set_ref"])
        anchored |= {r for r in refs if "." in r}
    rel_keys = set()
    for r in model.get("relationships", []) or []:
        rel_keys |= {r.get("from_key"), r.get("to_key")}
    ents = {}
    for ent, e in (model.get("entities") or {}).items():
        pk = e.get("pk")
        pk_cols = set(pk) if isinstance(pk, list) else {pk}
        flex = [p for p, c in (e.get("columns") or {}).items()
                if f"{ent}.{p}" not in anchored
                and p not in pk_cols and c not in pk_cols and c not in rel_keys]
        if flex:
            ents[ent] = {"flex": sorted(flex)}
    return {"entities": ents} if ents else None


def propose_duality_views(model, patterns, root):
    """A duality view PER AGGREGATE, not one per root.

    A view costs exactly what it nests. Cover every pattern with a single view and the point
    read pays to assemble the itinerary read's joins — measured on the airline capstone at
    3,257µs against 451µs for a lean view answering the same two-scalar query. So: group the
    patterns rooted here by the set of OTHER entities they touch, and give each distinct
    aggregate its own view. Each query then reads through the leanest view that can answer it.

    (An aggregation is not considered: duality must stay updatable, so it cannot express a
    GROUP BY and reads that pattern through the read-only sql_view projection instead.)
    """
    from tooling.generate.sql import is_aggregate
    e = model["entities"][root]
    scopes = set()
    for p in patterns or []:
        q = p.get("query") or {}
        if q.get("root") != root or is_aggregate(q):
            continue
        refs = list(q.get("returns") or []) + [pr["ref"] for pr in q.get("predicates") or []]
        scopes.add(frozenset({r.split(".", 1)[0] for r in refs if "." in r} - {root}))

    # ...and the COLUMNS each entity contributes. Scoping by aggregate but not by column
    # leaves a kitchen sink one level down: nesting all eleven passenger columns to answer a
    # query that wants `last_name`. A view costs exactly what it nests, and that includes the
    # columns it carries.
    #
    # The ROOT takes the union across every pattern rooted here — reads, writes, aggregations
    # alike — because a duality view is updatable and a write may set any of them. A nested
    # entity takes only what is actually referenced on it. Keys are never trimmed: duality
    # needs them to identify the row, and the root's key IS `_id`.
    cols = {}
    for p in patterns or []:
        q = p.get("query") or {}
        if q.get("root") != root:
            continue
        refs = list(q.get("returns") or []) + [pr["ref"] for pr in q.get("predicates") or []]
        refs += list(q.get("group_by") or [])
        refs += [a["ref"] for a in (q.get("aggregates") or []) if a.get("ref", "*") != "*"]
        refs += [o["ref"] for o in (q.get("order_by") or []) if o.get("ref")]
        w = p.get("write") or {}
        if w.get("set_ref"):
            refs.append(w["set_ref"])
        for ref in refs:
            if "." not in ref:
                continue
            ent, prop = ref.split(".", 1)
            cols.setdefault(ent, set()).add(prop)

    views = []
    for scope in sorted(scopes, key=lambda s: (len(s), sorted(s))):
        suffix = "_".join(sorted(x.lower() for x in scope))
        name = f"{e['table']}_dv" + (f"_{suffix}" if suffix else "")
        views.append({"view": name[:128], "includes": sorted(scope),
                      "columns": {k: sorted(v) for k, v in cols.items()}})
    return views or [{"view": f"{e['table']}_dv", "includes": [],
                      "columns": {k: sorted(v) for k, v in cols.items()}}]


def _pklist(e):
    pk = e["pk"]
    return list(pk) if isinstance(pk, list) else [pk]


def _anchor_entity(model, patterns):
    """The anchor is what the ACCESS PATTERNS actually key on — the query root carrying
    the most traffic. That is the thing a single collection must co-locate around."""
    rates = {}
    for p in patterns or []:
        q = p.get("query") or {}
        root = q.get("root")
        if root in model.get("entities", {}):
            rates[root] = rates.get(root, 0) + float(p.get("rate", 0) or 0)
    return max(rates, key=rates.get) if rates else None


def _path_cols(model, anchor, steps):
    """The join path from the anchor down to a co-located entity, as table/key hops. The
    populate step walks it in reverse to carry the anchor key onto the co-located item."""
    ents = model["entities"]
    return [{"from_table": ents[s["from"]]["table"], "to_table": ents[s["to"]]["table"],
             "from_key": s.get("from_key"), "to_key": s.get("to_key")} for s in steps]


def _co_retrieved(model, patterns, anchor):
    """The entities that appear in a RESULT SET alongside the anchor. If a query returns
    Order + OrderItem + Payment together, those three must come back in one read — so they
    are the candidates for co-location. The result set is the requirement; the
    relationships below decide whether it can actually be satisfied."""
    out = set()
    for p in patterns or []:
        q = p.get("query") or {}
        refs = list(q.get("returns") or []) + [pr["ref"] for pr in q.get("predicates") or []]
        ents = {r.split(".", 1)[0] for r in refs} | ({q["root"]} if q.get("root") else set())
        if anchor in ents:
            out |= ents
    return out & set(model.get("entities", {}))


def _is_join_table(model, name):
    """An associative entity: a composite key whose every column is somebody else's key.
    `reservation_payments(reservation_id, payment_id)` is one; `legs(leg_id)` is not.

    This guard is what stops the descent from wandering: without it, hopping "up" out of
    Leg would drag FlightSchedule — shared reference data — into every item collection."""
    e = model["entities"].get(name) or {}
    pk = _pklist(e)
    if len(pk) < 2:
        return False
    others = {c for n, o in model["entities"].items() if n != name for c in _pklist(o)}
    return all(c in others for c in pk)


def _descendants(model, anchor, max_hops=3):
    """Entities reachable from the anchor by following relationships DOWN -> {entity: path}.

    Two ways down:
      * a 1:N child of the current entity;
      * the FAR SIDE of an M:N — reached only from a genuine join table, by following its
        other parent edge. An M:N is modelled as two 1:N edges INTO the join table, so the
        far side (Payment, Leg) sits "up" one of them; without this hop the item collection
        would hold the join rows and none of their payload.

    Down only. An N:1 parent (customer, airport, calendar) is shared reference data — pull
    it into every item collection and you duplicate it once per anchor. A DynamoDB item
    collection is the aggregate root and its dependents, and that is what this returns."""
    rels = model.get("relationships", [])
    paths, frontier = {}, [(anchor, [])]
    for _ in range(max_hops):
        nxt = []
        for cur, path in frontier:
            cands = [(r["to"], r) for r in rels
                     if r["from"] == cur
                     and (r.get("cardinality") or "1:N").upper() in ("1:N", "1:1")]
            if cur != anchor and _is_join_table(model, cur):
                # An M:N is written either way round — two 1:N edges INTO the join table,
                # or an N:1 edge OUT of it. Both mean the same thing; follow both.
                cands += [(r["from"], r) for r in rels
                          if r["to"] == cur
                          and (r.get("cardinality") or "1:N").upper() in ("1:N", "1:1")]
                cands += [(r["to"], r) for r in rels
                          if r["from"] == cur
                          and (r.get("cardinality") or "1:N").upper() == "N:1"]
            for nb, step in cands:
                if nb == anchor or nb in paths or nb == cur:
                    continue
                paths[nb] = path + [step]
                nxt.append((nb, paths[nb]))
        frontier = nxt
        if not frontier:
            break
    return paths


def propose_single_table(model, patterns=None):
    """Derive the converged single-collection layout FROM THE RESULT SETS, THE FILTERS AND
    THE RELATIONSHIPS. Nothing here is guessed:

      * the ANCHOR is the entity the filters key on most (by rate) — the query root
        carrying the most traffic;
      * an entity that is RETURNED ALONGSIDE the anchor and is one of its dependents keys
        **anchor-first** — (anchor_col, own_pk). That is exactly the DynamoDB PK+SK shape,
        so "everything for reservation X" is one indexed read of the item collection. It
        holds through a join table too: the far side of an M:N co-locates;
      * shared parents (customer, airport, calendar) stay on their own key — co-locating
        them would duplicate the row into every item collection;
      * the filters that are not the anchor become indexes — the GSI equivalent.
    """
    ents = model["entities"]
    anchor = _anchor_entity(model, patterns)
    anchor_cols = _pklist(ents[anchor]) if anchor in ents else []

    co = _co_retrieved(model, patterns, anchor) if anchor else set()
    desc = _descendants(model, anchor) if anchor else {}

    types, indexes = {}, []
    for name, e in ents.items():
        own = _pklist(e)
        cols = set((e.get("columns") or {}).values()) | set(own)
        if not anchor or name == anchor:
            key = own
        elif name in co and name in desc:
            # returned with the anchor AND a dependent of it -> it belongs in the item
            # collection, keyed anchor-first. `path` is how the populate step carries the
            # anchor key across the join.
            key = anchor_cols + [k for k in own if k not in anchor_cols]
            types[name] = {"key": key, "path": _path_cols(model, anchor, desc[name])}
            continue
        else:
            carried = [c for c in anchor_cols if c in cols]
            key = carried + [k for k in own if k not in carried] if carried else own
        types[name] = {"key": key}

    # Secondary access paths (the GSIs): the patterns' non-anchor filters, per type.
    #
    # SPARSE or NOT? Every per-type index is sparse (CASE WHEN type='X' THEN col END), and a
    # sparse index cannot serve a read that spans SEVERAL types — such a read filters on the
    # plain column, matches no CASE expression, and scans the whole collection (measured at
    # 100k reservations: FULL SCAN, 2,481 logical reads, 4,505us, against relational's 499us).
    # A filter used by ANY multi-type read must therefore be non-sparse, so the flag is the OR
    # across every pattern that uses that column set — not whichever pattern happened to be
    # seen first.
    gsi = {}
    for p in patterns or []:
        q = p.get("query") or {}
        root = q.get("root")
        if root not in ents:
            continue
        # A predicate need not be on the ROOT. `passenger_history` filters
        # `Passenger.passenger_id` — the parent's own key — and in the single collection that
        # is the same physical column as the reservation's FK, shared by both item types. Skip
        # the non-root predicates and no index is derived for that filter at all, and the
        # 1.2M-row collection is scanned.
        cols, cross = [], False
        for pr in q.get("predicates", []) or []:
            ent, prop = pr["ref"].split(".", 1)
            if ent not in ents:
                continue
            e = ents[ent]
            col = prop if prop in _pklist(e) else (e.get("columns") or {}).get(prop, prop)
            if ent != root:
                cross = True                  # filters a column shared across item types
            if col not in anchor_cols and col not in cols:
                cols.append(col)
        if not cols:
            continue
        touched = {rf.split(".", 1)[0] for rf in (q.get("returns") or []) if "." in rf}
        # A read that spans types — or filters a column belonging to another type — cannot use
        # a sparse, type-filtered index. It needs the plain column.
        multi = cross or len(touched & set(ents)) > 1
        key = (root, tuple(cols))
        shapes = gsi.setdefault(key, {"single": False, "multi": False})
        shapes["multi" if multi else "single"] = True

    # The index must match the QUERY. A single-type read filters through the sparse CASE
    # expression; a multi-type read filters on the plain column. When BOTH read shapes use the
    # same filter, BOTH indexes are needed — emit only one and the other read stops matching
    # and full-scans.
    indexes = []
    for (root, cols), shapes in gsi.items():
        base = "_".join(cols)
        if shapes["single"]:
            indexes.append({"name": f"{base}_gx"[:100], "type": root,
                            "columns": list(cols), "sparse": True})
        if shapes["multi"]:
            indexes.append({"name": f"{base}_xt_gx"[:100], "type": root,
                            "columns": list(cols), "sparse": False})

    return {"table": "converged_items", "discriminator": "type", "types": types,
            "indexes": indexes, "anchor": anchor}


def candidate_shapes(model, patterns, only=None):
    """The designs that can serve EVERY pattern. relational is always a candidate; the
    others require the projection to exist (declared by the agent, or proposed above)."""
    proj = model.get("projections") or {}
    shapes = {"relational"}
    if proj.get("document"):
        shapes.add("document")
    if proj.get("duality"):
        shapes.add("duality")          # falls back to sql_view for what it can't express
    if proj.get("single_table"):
        shapes.add("single_table")
    if (proj.get("hybrid") or {}).get("entities"):
        shapes.add("hybrid")
    if (proj.get("summary") or {}).get("mvs"):
        shapes.add("summary")
    if only:
        shapes &= set(only)
    return [s for s in DEFAULT_DESIGNS if s in shapes] or ["relational"]


def split_patterns(patterns):
    reads = [p for p in patterns if p.get("kind", "read") != "write"]
    writes = [p for p in patterns if p.get("kind") == "write"]
    return reads, writes


# --- 2/3. deploy + seed --------------------------------------------------------
def _exec(conn, sql):
    for stmt in (s.strip() for s in sql.split(";")):
        if not stmt:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
        except Exception as exc:
            code = getattr(exc.args[0], "code", None) if exc.args else None
            if code not in _EXISTS:
                raise
    conn.commit()


# MULTIVALUE and the table alias (`ON coll t (t.data...)`) are part of the
# grammar now — the old pattern silently skipped every multivalue index, so
# verify_indexes could not see whether the document's shared-lane indexes landed.
_IX_RE = re.compile(r"CREATE\s+(?:MULTIVALUE\s+)?INDEX\s+(\w+)\s+ON\s+(\w+)(?:\s+\w+)?\s*\(", re.I)


def expected_indexes(ddl):
    """{INDEX_NAME: TABLE} the DDL claims to create."""
    return {m.group(1).upper(): m.group(2).upper() for m in _IX_RE.finditer(ddl or "")}


def verify_indexes(conn, ddl):
    """Did the access-pattern indexes actually LAND, on the table they were meant for?

    `CREATE INDEX` is allowed to say "already exists" — that is what makes a re-run
    idempotent — so a silently skipped index is indistinguishable from a successful one. Which
    is exactly how the document's `itinerary_reservations_passenger_id_ix` on `reservation_docs`
    took the name the RELATIONAL index needed, made the relational CREATE raise a tolerated
    ORA-00955, and left relational full-scanning its filtered reads in every run of the
    capstone. The only honest check is to look afterwards.
    """
    want = expected_indexes(ddl)
    if not want:
        return []
    with conn.cursor() as cur:
        have = {n: t for n, t in cur.execute(
            "SELECT index_name, table_name FROM user_indexes")}
    return [f"{n} (wanted on {tbl}, found on {have.get(n, 'NOTHING')})"
            for n, tbl in want.items() if have.get(n) != tbl]


def deploy(conn, model, patterns, shape, sparse=True, partition_by_type=True,
           partition=True, flex_limit=8192, iot=True, compress=True):
    """Deploy the shape, then the indexes the access patterns imply. Indexes FIRST —
    otherwise you benchmark full scans production would never run.

    The organization/compress dimensions change storage, not access paths, so
    index derivation takes no knob for them."""
    st = storage_shape(shape)
    _exec(conn, generate_ddl(model, st, sparse=sparse,
                             partition_by_type=partition_by_type,
                             partition=partition, flex_limit=flex_limit,
                             iot=iot, compress=compress))
    queries = [p["query"] for p in patterns]
    idx_ddl = generate_indexes(model, queries, shape=st, partition=partition)
    try:
        _exec(conn, idx_ddl)
        wrong = verify_indexes(conn, idx_ddl)
        if wrong:
            raise RuntimeError("index(es) did not land: " + "; ".join(wrong))
    except Exception as exc:
        # A shape with no derivable index is fine. An index that FAILS TO BUILD is not: the
        # design then full-scans a filtered read and is measured as slow at something it is
        # good at. This swallowed ORA-00955 for weeks, because the document's index had taken
        # the relational index's name.
        raise RuntimeError(
            f"could not deploy the access-pattern indexes for {st!r}: {exc}. "
            f"Benchmarking an unindexed design measures full scans production would never "
            f"run — fix this before trusting any number in the matrix.") from exc


def expand_sqlplus(sql):
    """Resolve SQL*Plus DEFINE/&substitution and drop SET/PROMPT directives, so a seed
    authored for SQLcl can be run by a plain driver."""
    import re
    defines, out = {}, []
    for line in sql.splitlines():
        s = line.strip()
        m = re.match(r"(?i)^DEFINE\s+(\w+)\s*=\s*(.+?)\s*;?$", s)
        if m:
            defines[m.group(1)] = m.group(2)
            continue
        if re.match(r"(?i)^(SET|PROMPT|SPOOL|WHENEVER|EXIT|COMMIT)\b", s):
            continue
        out.append(line)
    text = "\n".join(out)
    for k, v in sorted(defines.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(f"&{k}", v)
    return text


def reset_identities(conn):
    """A seed that inserts explicit PKs does NOT advance a GENERATED BY DEFAULT AS
    IDENTITY sequence — so the first application INSERT collides (ORA-00001). Re-anchor
    every identity column to MAX(id)+1 after seeding."""
    with conn.cursor() as cur:
        cur.execute("SELECT table_name, column_name FROM user_tab_identity_cols")
        cols = cur.fetchall()
    for tbl, col in cols:
        try:
            with conn.cursor() as cur:
                cur.execute(f'ALTER TABLE "{tbl}" MODIFY ("{col}" GENERATED BY DEFAULT '
                            f'AS IDENTITY (START WITH LIMIT VALUE))')
        except Exception:
            pass
    conn.commit()


def populate_single_table(conn, model):
    """Fold the relational rows into the converged single collection, one INSERT..SELECT
    per item type, so both designs hold the SAME data and the comparison is honest."""
    st = (model.get("projections") or {}).get("single_table")
    if not st:
        return
    table, disc = st["table"], st.get("discriminator", "type")
    with conn.cursor() as cur:
        try:
            cur.execute(f"DELETE FROM {table}")
        except Exception:
            return
    anchor = st.get("anchor")
    acols = _pklist(model["entities"][anchor]) if anchor in model["entities"] else []
    for ent, e in model["entities"].items():
        spec = (st.get("types") or {}).get(ent) or {}
        own = [c for c in _pklist(e)] + [c for c in (e.get("columns") or {}).values()]
        own = list(dict.fromkeys(own))
        if not own:
            continue
        path = spec.get("path") or []
        src = e["table"]
        if path and anchor and not set(acols) <= set(own):
            # Co-located, but the anchor key does not live on this table (the far side of an
            # M:N). Walk the join path back to the anchor to CARRY the key onto the item.
            joins, prev, ok = [], src, True
            for hop in reversed(path):
                jt = hop["from_table"] if hop["to_table"] == prev else hop["to_table"]
                tk = hop.get("to_key")
                if not tk or jt == prev:
                    ok = False
                    break
                joins.append(f"JOIN {jt} ON {jt}.{tk} = {prev}.{tk}")
                prev = jt
            if not ok:
                continue
            # Carry EVERY anchor column, not just the first — an anchor with a composite key
            # would otherwise land in the item collection missing half its key, and the
            # anchor index (which spans the full key) would never be used.
            carry = [c for c in acols if c not in own]
            sel = ", ".join([f"{prev}.{c}" for c in carry] + [f"{src}.{c}" for c in own])
            collist = ", ".join(carry + own)
            sql = (f"INSERT INTO {table} ({disc}, {collist}) "
                   f"SELECT '{ent}', {sel} FROM {src} " + " ".join(joins))
        else:
            collist = ", ".join(own)
            sql = (f"INSERT INTO {table} ({disc}, {collist}) "
                   f"SELECT '{ent}', {collist} FROM {src}")
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
        except Exception:
            pass                 # an entity that doesn't map cleanly is skipped, not fatal
    conn.commit()


def _hybrid_parents(model, ent):
    """The entities `ent` holds an FK to — its insert-order prerequisites."""
    out = set()
    for r in model.get("relationships", []) or []:
        card = (r.get("cardinality") or "1:N").upper()
        holder, parent = (r["from"], r["to"]) if card == "N:1" else (r["to"], r["from"])
        if holder == ent and parent != ent:
            out.add(parent)
    return out


def _hybrid_order(model):
    """Entities parents-first, so the copy never trips a live FK constraint."""
    ents = list(model.get("entities") or {})
    done, order = set(), []
    while ents:
        progressed = False
        for ent in list(ents):
            if _hybrid_parents(model, ent) <= done:
                order.append(ent)
                done.add(ent)
                ents.remove(ent)
                progressed = True
        if not progressed:                 # a cycle: fall back to declared order
            order += ents
            break
    return order


def hybrid_populate_sql(model):
    """The statements that DERIVE the hybrid lane from the relational lane —
    same rows, one INSERT..SELECT per entity, the flex column built with
    JSON_OBJECT keyed by the PROPERTY names (the equivalence invariant) and
    ABSENT ON NULL so sparse attributes stay absent rather than null. DELETEs
    run children-first and INSERTs parents-first: the FK constraints are live
    during the copy. Pure — the seed step executes what this returns."""
    hy = ((model.get("projections") or {}).get("hybrid") or {}).get("entities") or {}
    if not hy:
        return []
    order = _hybrid_order(model)
    stmts = [f"DELETE FROM {model['entities'][ent]['table']}_h"
             for ent in reversed(order)]
    for ent in order:
        e = model["entities"][ent]
        flex = list((hy.get(ent) or {}).get("flex") or ())
        core = list(dict.fromkeys(
            _pklist(e) + [c for p, c in (e.get("columns") or {}).items()
                          if p not in flex]))
        cols = ", ".join(core)
        if flex:
            pairs = ", ".join(f"'{p}' VALUE {(e.get('columns') or {}).get(p, p)}"
                              for p in flex)
            ins, sel = f"{cols}, flex", f"{cols}, JSON_OBJECT({pairs} ABSENT ON NULL)"
        else:
            ins, sel = cols, cols
        stmts.append(f"INSERT INTO {e['table']}_h ({ins}) SELECT {sel} FROM {e['table']}")
    return stmts


def summary_populate_sql(model):
    """Derive the summary lane from the relational lane — the hybrid populate
    with an `_s` suffix and no flex column. The caller's COMMIT is what
    maintains the ON COMMIT MVs; no manual refresh call exists anywhere."""
    if not (((model.get("projections") or {}).get("summary") or {}).get("mvs")):
        return []
    order = _hybrid_order(model)
    stmts = [f"DELETE FROM {model['entities'][ent]['table']}_s"
             for ent in reversed(order)]
    for ent in order:
        e = model["entities"][ent]
        cols = ", ".join(dict.fromkeys(
            _pklist(e) + list((e.get("columns") or {}).values())))
        stmts.append(f"INSERT INTO {e['table']}_s ({cols}) "
                     f"SELECT {cols} FROM {e['table']}")
    return stmts


def populate_summary(conn, model):
    """Execute the summary derivation — tolerant per statement; the final
    commit maintains the ON COMMIT MVs (probe P3)."""
    stmts = summary_populate_sql(model)
    if not stmts:
        return
    for sql in stmts:
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
        except Exception:
            pass
    conn.commit()


def populate_hybrid(conn, model):
    """Execute the hybrid derivation — tolerant per statement, like
    populate_single_table: a lane that isn't deployed is skipped, not fatal."""
    stmts = hybrid_populate_sql(model)
    if not stmts:
        return
    for sql in stmts:
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
        except Exception:
            pass
    conn.commit()


def drop_all(conn, model):
    """Drop every object the walk deploys, so the next seed starts from a clean segment.

    DELETE does not lower a table's HIGH-WATER MARK: after a 100k-row seed is deleted and a
    30k-row seed loaded, a full scan STILL reads to the old high-water mark — 11,390 logical
    reads for 30k rows of documents. Every scan measurement is then quietly inflated by
    whatever the last run happened to load. Rebuild rather than re-fill.
    """
    proj = model.get("projections") or {}
    objs = []
    for views in (proj.get("duality") or {}).values():
        if isinstance(views, str):
            objs.append(("VIEW", views))
        else:
            objs += [("VIEW", v["view"]) for v in views]
    objs += [("TABLE", d["collection"]) for d in (proj.get("document") or {}).values()]
    if proj.get("single_table"):
        objs.append(("TABLE", proj["single_table"]["table"]))
    if (proj.get("hybrid") or {}).get("entities"):
        objs += [("TABLE", f"{e['table']}_h") for e in model["entities"].values()]
    if (proj.get("summary") or {}).get("mvs"):
        objs += [("MATERIALIZED VIEW", mv["name"])
                 for mv in proj["summary"]["mvs"]]
        objs += [("TABLE", f"{e['table']}_s") for e in model["entities"].values()]
    objs += [("TABLE", e["table"]) for e in model["entities"].values()]
    for kind, name in objs:
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP {kind} {name}"
                            + (" CASCADE CONSTRAINTS PURGE" if kind == "TABLE" else ""))
        except Exception:
            pass                          # not there yet is not a problem
    conn.commit()


def seed(conn, sql_text, model=None):
    if sql_text:
        _exec(conn, expand_sqlplus(sql_text))
    reset_identities(conn)
    if model:
        populate_single_table(conn, model)
        populate_hybrid(conn, model)
        populate_summary(conn, model)


def gather_stats(conn):
    """Plan on real cardinality before measuring anything."""
    with conn.cursor() as cur:
        cur.execute("BEGIN DBMS_STATS.GATHER_SCHEMA_STATS(USER, options=>'GATHER', "
                    "cascade=>TRUE); END;")
    conn.commit()


# --- 4. measure ----------------------------------------------------------------
def _stat(conn, name):
    """Server-side counter (logical reads / redo). These are DIAGNOSTICS — the matrix is
    built from elapsed time — so a user without SELECT_CATALOG_ROLE still gets a full
    measurement, just without the counters. Never let a diagnostic kill the run."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM v$mystat s JOIN v$statname n "
                        "ON n.statistic#=s.statistic# WHERE n.name=:1", (name,))
            row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _write_sql(model, pattern, shape):
    w = pattern.get("write") or {}
    op = w.get("op", "update")
    shape = storage_shape(shape)          # sql_view writes are relational writes
    if op == "insert":
        return generate_insert(model, pattern["query"], shape)
    if not w.get("set_ref"):
        # A write with neither a `write.set_ref` nor an explicit `sql` hatch for this shape
        # cannot be measured — and an unmeasured write silently EXCLUDES the design from
        # the decision, which is how you end up confidently choosing a shape you never
        # tested the writes on. Say so.
        raise ValueError(
            f"write pattern {pattern.get('name')!r} has no SQL for design {shape!r}: "
            f"add sql.{shape} or a write.set_ref so the write can be measured")
    return generate_update(model, pattern["query"], shape,
                           w["set_ref"], w.get("delta", 1))


def summary_compensation_sql(model, pattern):
    """The statement that undoes one measured summary write — executed
    OUTSIDE the timed region, then committed, so the commit-inclusive cell
    is net non-mutating (probe P3: the MV round-trips exactly). Derived from
    the same pattern spec as the write; an explicit `sql.summary_compensate`
    is the escape hatch. A write with no derivable compensation is a LOUD
    measurement error — measuring it would leave the lane mutated, and
    skipping it silently would exclude the design from the decision."""
    explicit = (pattern.get("sql") or {}).get("summary_compensate")
    if explicit:
        return explicit
    w = pattern.get("write") or {}
    op = w.get("op", "update")
    q = pattern["query"]
    if op == "insert":
        e = model["entities"][q["root"]]
        return f"DELETE FROM {e['table']}_s WHERE {e['pk']} = 9999"
    if op == "update" and w.get("set_ref"):
        return generate_update(model, q, "summary", w["set_ref"],
                               -int(w.get("delta", 1)))
    raise ValueError(
        f"summary write {pattern.get('name')!r} has no derivable compensation "
        f"(op={op!r}) — add sql.summary_compensate so the commit-inclusive "
        f"cell can be measured honestly")


def pattern_sql(model, pattern, shape):
    """The SQL that serves one pattern under one design.

    A workload may supply explicit SQL per shape (the escape hatch for anything the
    generator can't express); otherwise it is generated. Duality is special: the view must
    stay updatable, so it cannot express an aggregation — but that must NOT exclude the
    duality design, because it is the SAME relational storage. It simply reads that one
    pattern through a read-only JSON view (sql_view) instead.
    """
    explicit = (pattern.get("sql") or {})
    if shape in explicit:
        return explicit[shape]
    if pattern.get("kind") == "write":
        return _write_sql(model, pattern, shape)

    q = pattern["query"]
    cands = generate_candidates(model, q)
    if shape in cands:
        return cands[shape]
    if shape == "duality" and "sql_view" in cands:
        return cands["sql_view"]        # same storage, read-only projection
    return generate_relational(model, q)


def _present(value, out):
    """Every property name that carries an actual value, at any depth. A key whose value is
    NULL has not been answered — that is how a broken join hides: the column is there, the
    data is not."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k.startswith("_"):
                continue                       # _id / _metadata are plumbing, not an answer
            if v is not None and not isinstance(v, (dict, list)):
                out.add(k.lower())
            _present(v, out)
    elif isinstance(value, list):
        for v in value:
            _present(v, out)


def unanswered(pattern, rows, model=None):
    """The properties the query ASKED FOR that the answer does not contain.

    A design's cost is meaningless unless it answered the question. Twice this harness timed
    a design that was fast because it returned less: a duality view that nested the junction
    keys and never joined through to the flight number, and a "document" that embedded
    nothing. Both looked excellent. Neither answered the query.

    Checked across the whole result SET, not per row — the single collection legitimately
    answers an item-collection read with one row per type.
    """
    q = pattern.get("query") or {}
    if is_aggregate(q):
        return []                              # aggregates return computed aliases, not props
    want = {r.split(".", 1)[1].lower() for r in (q.get("returns") or []) if "." in r}
    if not want:
        return []
    got = set()
    for row in rows or []:
        _present(row, got)
    # In a document the root's primary key IS `_id` — the query asks for `reservation_id`
    # and the document answers with `_id`. Same value, different name; not a missing field.
    if model and "_id" in {k for row in (rows or []) if isinstance(row, dict)
                           for v in row.values() if isinstance(v, dict) for k in v}:
        root = (pattern.get("query") or {}).get("root")
        e = (model.get("entities") or {}).get(root) or {}
        if e:
            got |= {c.lower() for c in _pklist(e)}
    return sorted(want - got)


def plan_warning(pattern, plan):
    """A FILTERED read that full-scans is a defect, not a datapoint.

    The runner measured elapsed time and captured `consistent gets`, and never once looked at
    either. Meanwhile the relational design full-scanned two of its filtered reads in every
    run of the capstone — its access-pattern indexes had never been built, because the
    document's indexes had taken their names and the resulting ORA-00955 was tolerated as
    "already exists". A number without its access path is not evidence.

    An aggregation with no predicate legitimately scans: that is the query, not a defect.
    """
    q = pattern.get("query") or {}
    if not (q.get("predicates") or []):
        return None                       # nothing to filter on — a scan is the honest plan
    scans = [l for l in plan if "TABLE ACCESS FULL" in l.upper()]
    if not scans:
        return None
    tables = ", ".join(sorted(_scanned_tables(scans)))
    return (f"FULL SCAN of {tables or 'a table'} on a filtered read — the access-pattern "
            f"index is not being used, so this cell measures a scan production would never run")


def _fetch_rows(conn, sql, limit=50000):
    """The answer, as dicts keyed by column name — a JSON column comes back as the parsed
    document, so a nested field counts as answered wherever it lives.

    Fetch the WHOLE answer, not the first N rows. Truncating at 50 was a bug with teeth: a
    filtered read returning 167 rows with no ORDER BY hands back an arbitrary 50 per design,
    so the designs "disagree" about rows they all actually have. The comparison must see the
    whole result set or it is comparing two arbitrary samples."""
    import json as _json
    rows = []
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0].lower() for d in (cur.description or [])]
        for rec in cur.fetchmany(limit):   # cap is a runaway guard, not a sample
            row = {}
            for name, val in zip(cols, rec):
                if hasattr(val, "read"):
                    val = val.read()
                if isinstance(val, str) and val[:1] in "{[":
                    try:
                        val = _json.loads(val)
                    except ValueError:
                        pass
                row[name] = val
            rows.append(row)
    return rows


def validate_answers(conn, model, patterns, shapes, progress=None):
    """MODEL VALIDATION — every design must return the SAME ANSWER, before anything is timed.

    This is the gate the whole matrix rests on. A design that returns less is faster, and a
    timing loop cannot tell the difference: three separate defects in the airline capstone
    were exactly that — a duality view that nested the junction keys and never joined through
    to the flight number, a "document" that embedded nothing, and a pattern whose filter
    matched no rows at all. Each one looked excellent. None of them answered the query.

    Relational is the reference: it is always a candidate, and it is the design whose answer
    is defined by the schema rather than by a projection someone had to build correctly.

    Returns {(pattern, shape): [reasons]} — every cell that must NOT be compared, plus the
    patterns whose reference answer is empty (a filter that matches nothing is not a
    benchmark, it is an index probe that finds nothing).
    """
    from tooling.optimize.equivalence import (answer_diff, answers_match, canonical_answer,
                                              is_empty_answer)
    bad, empty = {}, []
    ref_shape = "relational" if "relational" in shapes else sorted(shapes)[0]
    for p in patterns:
        if p.get("kind") == "write":
            continue                    # a write's answer is its effect; it is rolled back
        q = p["query"]
        e = model["entities"][q["root"]]
        pk = e["pk"]
        id_prop = pk[0] if isinstance(pk, list) else pk    # the document spells it `_id`
        try:
            ref = canonical_answer(q, _fetch_rows(conn, pattern_sql(model, p, ref_shape)),
                                   id_prop=id_prop)
        except Exception as exc:
            bad[(p["name"], ref_shape)] = [f"the reference design failed: {exc}"]
            continue
        if is_empty_answer(ref):
            empty.append(p["name"])
        for s in shapes:
            if s == ref_shape:
                continue
            try:
                got = canonical_answer(q, _fetch_rows(conn, pattern_sql(model, p, s)),
                                       id_prop=id_prop)
            except Exception as exc:
                bad[(p["name"], s)] = [str(exc).split("\n")[0]]
                continue
            if not answers_match(ref, got):
                bad[(p["name"], s)] = answer_diff(ref, got)
        if progress:
            n = sum(1 for s in shapes if (p["name"], s) in bad)
            progress(f"  {p['name']}: " + ("all designs agree" if not n
                                           else f"{n} design(s) DISAGREE with {ref_shape}")
                     + (" [but the answer is EMPTY]" if is_empty_answer(ref) else ""))
    return bad, empty


def measure_cell(conn, model, pattern, shape, trials=7, warmup=2):
    """Median elapsed microseconds for one (pattern, shape) cell, plus the deterministic
    server-side diagnostics. Writes are ROLLED BACK — measuring must not mutate."""
    is_write = pattern.get("kind") == "write"
    sql = pattern_sql(model, pattern, shape)
    # THE COMMIT-INCLUSIVE CELL (summary only). The summary's MVs refresh
    # FAST ON COMMIT — probe-verified as the only aggregate-eligible mode
    # (ORA-32428 kills ON STATEMENT) — so a rolled-back write would never
    # pay the maintenance this design's whole trade rests on. Its write
    # cells therefore time execute + COMMIT (maintenance inside the timed
    # region, like the rollback other lanes' cells include), then run the
    # compensating statement + commit UNTIMED: net non-mutating, and the
    # commit overhead biases AGAINST summary — disclosed in the report.
    comp = (summary_compensation_sql(model, pattern)
            if is_write and shape == "summary" else None)

    def once():
        t0 = time.perf_counter_ns()
        with conn.cursor() as cur:
            cur.execute(sql)
            if not is_write:
                cur.fetchall()
        if comp is not None:
            conn.commit()
        elif is_write:
            conn.rollback()
        dt = (time.perf_counter_ns() - t0) / 1000.0          # microseconds
        if comp is not None:
            with conn.cursor() as cur:
                cur.execute(comp)
            conn.commit()
        return dt

    # THE ANSWER GATE. A design's speed means nothing until it has answered the question.
    # Twice this harness timed a design that was fast because it returned LESS — a duality
    # view that nested the junction keys and never joined through to the flight number, and
    # a "document" that embedded nothing. Both looked excellent; neither answered the query.
    # An unanswered query is a MEASUREMENT ERROR, not a fast cell.
    n_rows = None
    if not is_write:
        gate_rows = _fetch_rows(conn, sql)
        n_rows = len(gate_rows)
        missing = unanswered(pattern, gate_rows, model)
        if missing:
            raise ValueError(
                f"{shape} does not answer {pattern.get('name')!r}: the result is missing "
                f"{', '.join(missing)} — it is not doing the work the other designs are, so "
                f"its time is not comparable")

    # THE WRITE GATE — the same failure mode on the other side of the matrix. A write's
    # answer is its effect, and the effect is rolled back, so validate_answers cannot see
    # it. But a write that touches ZERO rows (a seed that silently skipped an item type, a
    # predicate that misses under this projection) is fast because it did NOTHING — and an
    # untouched-row write would win every write row of the matrix. Zero effect is a
    # MEASUREMENT ERROR, not a fast cell.
    # rowcount is only meaningful for a single DML statement: python-oracledb reports 0
    # after a BEGIN/DECLARE block even when its inner statements changed rows (verified
    # live against 23.26.2), so gating a block on rowcount invalidates real writes.
    if is_write and not sql.lstrip().upper().startswith(("BEGIN", "DECLARE")):
        with conn.cursor() as cur:
            cur.execute(sql)
            affected = cur.rowcount
        conn.rollback()
        if not affected:
            raise ValueError(
                f"{shape} write {pattern.get('name')!r} touched no rows — a zero-effect "
                f"write is fast because it did nothing, so its time is not comparable")

    for _ in range(warmup):
        once()
    # the redo bracket would count the untimed compensation too — a summary
    # write's redo diagnostic would read ~double, so it is omitted honestly
    before = None if comp is not None else _stat(
        conn, "redo size" if is_write else "consistent gets")
    samples = [once() for _ in range(trials)]
    after = None if comp is not None else _stat(
        conn, "redo size" if is_write else "consistent gets")

    med = statistics.median(samples)
    cv = (statistics.pstdev(samples) / med) if med else 0.0
    diag = {}
    if before is not None and after is not None:
        diag[("redo_bytes" if is_write else "logical_reads")] = (after - before) / max(trials, 1)
    warn, access = None, None
    if not is_write:
        try:
            plan = explain(conn, sql)
            access = plan_access(plan)
            warn = plan_warning(pattern, plan)
        except Exception:
            pass                          # a plan we cannot pull is not a reason to fail
    return {"us": med, "cv": cv, "diag": diag, "sql": sql,
            "plan_warning": warn, "access": access, "rows": n_rows}


def measure(conn, model, patterns, shapes, trials=7, warmup=2, on_cell=None, invalid=None):
    """The full sweep: every pattern x every shape. Returns {pattern: {shape: us}} plus
    the per-cell detail (cv + server-side diagnostics).

    `invalid` is the verdict of validate_answers — cells whose design did not return the
    same answer as the reference. They are NOT timed. Timing a design that answers a
    different question produces a number, and the number is meaningless."""
    invalid = invalid or {}
    meas, detail = {}, {}
    for p in patterns:
        meas[p["name"]], detail[p["name"]] = {}, {}
        for s in shapes:
            why = invalid.get((p["name"], s))
            if why:
                detail[p["name"]][s] = {
                    "error": "ANSWER MISMATCH — " + "; ".join(why)[:120]}
                continue
            try:
                cell = measure_cell(conn, model, p, s, trials=trials, warmup=warmup)
            except Exception as exc:
                # CAREFUL: decide_model excludes any design missing a cell. That is right
                # when the design genuinely cannot serve the pattern, but a MEASUREMENT
                # ERROR must never silently exclude a design — that inverts the
                # recommendation. Record it and surface it loudly in the report.
                detail[p["name"]][s] = {"error": str(exc).splitlines()[0][:140]}
                continue
            meas[p["name"]][s] = cell["us"]
            detail[p["name"]][s] = cell
            if on_cell:
                on_cell(p["name"], s, cell)
    return meas, detail


# --- 5. the cost matrix -> the decision ----------------------------------------

# The access-path split the Exadata disclosure rests on (research-verified,
# 3-0): Smart Scan offload applies ONLY to direct-path full-segment scans;
# single-block buffer-cache access never offloads. So point-read-decided
# verdicts transfer to Exadata-class deployments; scan-decided ones are
# environment-conditional.
_POINT_ACCESS = {"IDX UNIQUE", "IDX RANGE", "BY ROWID"}
_SCAN_ACCESS = {"FULL SCAN", "IDX FFS", "IDX FULL", "IDX SKIP"}


def _decided_by(drivers, detail, chosen):
    """Classify the election by the access paths of the cells its margin rests
    on, weighted by each driver's rate-weighted contribution. None when no
    deciding cell has plan data — no disclosure beats a wrong one."""
    if not (drivers and detail and chosen):
        return None
    point_w = scan_w = 0.0
    point, scan = [], []
    for d in drivers:
        cell = (detail.get(d["pattern"]) or {}).get(chosen)
        acc = cell.get("access") if isinstance(cell, dict) else None
        if acc in _POINT_ACCESS:
            point_w += float(d.get("cost", 0) or 0)
            point.append(d["pattern"])
        elif acc in _SCAN_ACCESS:
            scan_w += float(d.get("cost", 0) or 0)
            scan.append(d["pattern"])
    if not (point or scan):
        return None
    label = ("point" if point_w > scan_w
             else "scan" if scan_w > point_w else "mixed")
    return {"label": label, "point": point, "scan": scan}


def _provisional(patterns, detail, chosen):
    """The mechanized production-cardinality check: a pattern that DECLARED an
    expected magnitude (`expect_rows`) whose measured cell answered fewer rows
    ran against a degenerate fixture — the verdict it contributed to is
    provisional, said out loud."""
    out = []
    if not (detail and chosen):
        return out
    for p in patterns:
        expect = p.get("expect_rows")
        if not expect:
            continue
        cell = (detail.get(p["name"]) or {}).get(chosen)
        rows = cell.get("rows") if isinstance(cell, dict) else None
        if rows is not None and rows < int(expect):
            out.append({"pattern": p["name"], "rows": rows, "expected": int(expect)})
    return out


def _summary_maintenance(patterns, meas):
    """The decided disclosure (Phase-2 charging model): per write pattern,
    the summary design's measured cell beside relational's — the delta IS the
    MV upkeep (+the commit other lanes' rolled-back cells do not pay)."""
    out = []
    for p in patterns:
        if p.get("kind") != "write":
            continue
        costs = meas.get(p["name"]) or {}
        s, r = costs.get("summary"), costs.get("relational")
        if s is not None and r is not None:
            out.append({"pattern": p["name"], "summary_us": s,
                        "relational_us": r, "delta_us": s - r})
    return out


def build_result(model, patterns, meas, write_scale=1.0, walk_scales=None, detail=None):
    """The full cost matrix — every pattern a row (reads AND writes, each with its own
    rate), every candidate design a column, every cell measured — then the decision.

    `detail` is measure()'s per-cell record; its `cv` is what makes the noise gate a
    GATE — the effective noise_floor is raised to the worst cv among the cells the
    first-vs-second verdict actually rests on."""
    matrix, rows, cost = [], {}, {}
    for p in patterns:
        name, kind, rate = p["name"], p.get("kind", "read"), float(p.get("rate", 0))
        costs = meas.get(name, {})
        matrix.append({"pattern": name, "kind": kind, "rate": rate,
                       "category": p.get("category", ""), "costs": costs})
        if costs:
            rows[name] = {"kind": kind, "rate": rate}
            cost[name] = dict(costs)

    kw = {"walk_scales": tuple(walk_scales)} if walk_scales else {}
    decision = decide_model(rows, cost, write_scale=write_scale, **kw) if rows else {}
    ranked = decision.get("ranked", [])
    # How much daylight is there between first and second? Timings on a live database carry
    # a few percent of noise, so a 3% "win" is a coin flip wearing a lab coat. Report the
    # margin, and let the caller refuse to make an architectural decision on it.
    margin = None
    if len(ranked) >= 2 and ranked[0][1]:
        margin = (ranked[1][1] - ranked[0][1]) / float(ranked[0][1])
    # THE NOISE GATE. NOISE_FLOOR is a floor, not the gate: if the cells the verdict
    # rests on carry a cv above it, the trials disagree with THEMSELVES by more than the
    # designs disagree with each other, and no separation can be declared on that margin.
    noise_floor = NOISE_FLOOR
    if detail:
        top = {name for name, _ in ranked[:2]}
        for name, row in rows.items():
            if not row["rate"]:
                continue                      # a zero-rate pattern weighs nothing here
            for s, cell in (detail.get(name) or {}).items():
                cv = cell.get("cv") if isinstance(cell, dict) else None
                if s in top and cv is not None:
                    noise_floor = max(noise_floor, cv)
    return {
        "matrix": matrix,
        "chosen": decision.get("chosen"),
        "ranked": ranked,
        "margin": margin,
        "noise_floor": noise_floor,
        "drivers": decision.get("drivers", []),
        "read_cost": decision.get("read_cost", {}),
        "write_cost": decision.get("write_cost", {}),
        "walk": decision.get("walk", []),
        "excluded": decision.get("excluded", {}),
        "notes": decision.get("notes", []),
        "decided_by": _decided_by(decision.get("drivers"), detail,
                                  decision.get("chosen")),
        "provisional": _provisional(patterns, detail, decision.get("chosen")),
        "summary_maintenance": _summary_maintenance(patterns, meas),
    }


def scenario_sweep(model, patterns, meas, scenarios, detail=None):
    """Turn the knob that actually matters: **the mix**.

    A cell in the matrix is a property of the schema and the data — not of how often the
    pattern runs. So a scenario is a re-weighting of measurements already taken, and every
    named mix costs zero extra database work. That is what makes "the winner changes with
    the workload" a demonstration rather than an assertion.

    scenarios: [{"name": str, "rates": {pattern: rate}, "note": str?}] — a pattern absent
    from `rates` runs at zero in that scenario.
    """
    rows = []
    for sc in scenarios or []:
        rates = sc.get("rates") or {}
        pats = [dict(p, rate=float(rates.get(p["name"], 0))) for p in patterns]
        res = build_result(model, pats, meas, detail=detail)
        reads = sum(p["rate"] for p in pats if p.get("kind", "read") != "write")
        writes = sum(p["rate"] for p in pats if p.get("kind") == "write")
        rows.append({
            "name": sc["name"],
            "note": sc.get("note", ""),
            "ranked": res["ranked"],
            "winner": res["chosen"],
            "margin": res["margin"] or 0.0,
            # SEPARATES only past the EFFECTIVE floor — a margin that beats 5% but not
            # the measured cv of its own cells flips winners between runs.
            "separates": (res["margin"] or 0.0) >= res["noise_floor"],
            "read_write_ratio": (reads / writes) if writes else None,
        })
    return rows


def flip_sweep(model, patterns, meas, scales=(1.0, 0.3, 0.1, 0.03, 0.01, 0.0), anchor=None):
    """Where does the winner flip? Shrink every pattern EXCEPT the dominant point-read
    toward zero and re-decide. This is the crossover the whole thesis rests on."""
    if anchor is None:                       # default: the highest-rate read
        reads = [p for p in patterns if p.get("kind", "read") != "write"]
        anchor = max(reads, key=lambda p: p.get("rate", 0))["name"] if reads else None
    out = []
    for sc in scales:
        scaled = [dict(p, rate=(p["rate"] if p["name"] == anchor
                                else p.get("rate", 0) * sc)) for p in patterns]
        res = build_result(model, scaled, meas)
        out.append({"scale": sc, "winner": res["chosen"],
                    "totals": dict(res["ranked"])})
    return out


# --- 6. the winning schema -----------------------------------------------------
def winning_ddl(model, chosen, sparse=True, partition_by_type=True,
                partition=True, flex_limit=8192, iot=True, compress=True):
    """The DDL that realizes the winning design. `sql_view` wins on relational storage —
    it differs only in the read projection — so emit the relational schema. The knobs
    must match what was deployed and measured, or the emitted winner is a different
    design than the one that won."""
    return (generate_ddl(model, storage_shape(chosen),
                         sparse=sparse, partition_by_type=partition_by_type,
                         partition=partition, flex_limit=flex_limit,
                         iot=iot, compress=compress)
            if chosen else "")


# --- reporting -----------------------------------------------------------------
def format_report(result, sweep=None, detail=None, scenarios=None):
    detail = detail if detail is not None else result.get("detail")
    shapes = sorted({s for row in result["matrix"] for s in row["costs"]})
    w = max([len(r["pattern"]) for r in result["matrix"]] + [10])
    out = ["", "FULL COST MATRIX — every pattern measured against every candidate design",
           "  (unit: median elapsed microseconds; reads AND writes are first-class rows)", ""]
    head = f"  {'pattern':<{w}}  {'category':<13} {'kind':<6} {'rate/hr':>8}"
    head += "".join(f"{s:>13}" for s in shapes)
    out += [head, "  " + "-" * (len(head) - 2)]
    for r in result["matrix"]:
        line = (f"  {r['pattern']:<{w}}  {r.get('category',''):<13} "
                f"{r['kind']:<6} {r['rate']:>8,.0f}")
        for s in shapes:
            v = r["costs"].get(s)
            line += f"{v:>13,.0f}" if v is not None else f"{'n/a':>13}"
        out.append(line)

    # ACCESS PATHS — a number without its access path is not evidence. The plan is what says
    # WHY a cell costs what it costs, and whether the number can be trusted at all.
    if detail:
        out += ["", "ACCESS PATHS — how each design actually served each pattern",
                "  (method - logical reads; the plan is the WHY behind every cell above)", ""]
        h = f"  {'pattern':<{w}}  " + "".join(f"{s:>20}" for s in shapes)
        out += [h, "  " + "-" * (len(h) - 2)]
        for r in result["matrix"]:
            if r["kind"] == "write":
                continue
            line = f"  {r['pattern']:<{w}}  "
            for s in shapes:
                cell = (detail.get(r["pattern"]) or {}).get(s) or {}
                acc = cell.get("access") or "-"
                lr = (cell.get("diag") or {}).get("logical_reads")
                line += f"{acc + (f' {lr:.0f}' if lr is not None else ''):>20}"
            out.append(line)

    warns = []
    for pname, cells in (detail or {}).items():
        for s, cell in (cells or {}).items():
            if isinstance(cell, dict) and cell.get("plan_warning"):
                warns.append(f"   {pname} / {s}: {cell['plan_warning']}")
    if warns:
        out += ["", "!! ACCESS PATH WARNINGS — these cells measure a full scan, not the query",
                "!! production would run. Fix the indexes before believing these numbers:"]
        out += warns
    elif detail:
        out += ["", "  Every filtered read uses an index."]

    # NOISY CELLS — benchparse's CV_GATE applied to the Python path. A cell whose own
    # trials disagree above the gate is not a measurement, whatever its median says.
    noisy = []
    for pname, cells in (detail or {}).items():
        for s, cell in (cells or {}).items():
            if isinstance(cell, dict) and (cell.get("cv") or 0) > CV_GATE:
                noisy.append(f"   {pname} / {s}: cv={cell['cv'] * 100:.0f}%")
    if noisy:
        out += ["", "!! NOISY CELLS — the trials WITHIN these cells disagree by more than",
                f"!! the {CV_GATE * 100:.0f}% cv trust gate, so the cells themselves cannot be",
                "!! trusted. Re-run with more trials on a quieter host before believing",
                "!! any margin built on them:"]
        out += noisy

    # ANSWER VALIDATION — printed BEFORE the decision, because if the designs disagree the
    # decision is not a decision.
    inv = result.get("invalid") or {}
    empt = result.get("empty_patterns") or []
    if inv or empt:
        out += ["", "!! ANSWER VALIDATION FAILED — the designs did not return the same answer",
                "!! A design that returns LESS is faster. These cells were NOT timed:"]
        for (pname, s), why in sorted(inv.items()):
            out.append(f"   {pname} / {s}: {'; '.join(why)[:110]}")
        for pname in empt:
            out.append(f"   {pname}: the reference answer is EMPTY — this pattern's filter "
                       f"matches no data, so every design is timing an index probe that "
                       f"finds nothing. Fix the workload, not the schema.")
    else:
        out += ["", "ANSWER VALIDATION: every design returns the same answer for every "
                "pattern."]

    out += ["", "DECISION (rate-weighted over the whole matrix)"]
    for i, (name, total) in enumerate(result["ranked"], 1):
        out.append(f"  {i}. {name:<14} total weighted cost = {total:>15,.0f}")
    out.append(f"  CHOSEN: {result['chosen']}")
    if result["drivers"]:
        top = ", ".join(f"{d['pattern']} ({d['kind']})" for d in result["drivers"][:3])
        out.append(f"  driven by: {top}")

    # THE EXADATA TRANSFERABILITY DISCLOSURE (Phase-1 report contract). The
    # access-path split is research-verified: offload touches only direct-path
    # full-segment scans, so a point-read-decided margin means the same thing
    # on production hardware; a scan-decided one does not.
    db = result.get("decided_by")
    if db:
        if db["label"] == "point":
            out.append(f"  decided by: point reads ({', '.join(db['point'][:3])})"
                       f" -> verdict carries to Exadata-class deployments")
        elif db["label"] == "scan":
            out += [f"  decided by: scan economics ({', '.join(db['scan'][:3])})",
                    "   -> environment-conditional: Exadata smart scan / storage "
                    "indexes cheapen",
                    "      full-segment scans — re-validate this margin on the "
                    "deployment target"]
        else:
            out += [f"  decided by: mixed access paths (point: "
                    f"{', '.join(db['point'][:2])}; scan: {', '.join(db['scan'][:2])})",
                    "   -> the scan-decided share is environment-conditional on "
                    "Exadata-class targets"]

    # THE PRODUCTION-CARDINALITY FLAG (mechanized): a deciding pattern that
    # answered fewer rows than the workload declared ran against a degenerate
    # fixture — a small-seed winner is chosen on its incidental costs.
    for pv in result.get("provisional") or []:
        out += ["",
                f"  !! PROVISIONAL — {pv['pattern']} answered {pv['rows']} rows against a",
                f"  !! declared expectation of {pv['expected']}; production cardinality "
                f"unproven.",
                "  !! Re-seed at representative volume before trusting this verdict."]

    m = result.get("margin")
    nf = result.get("noise_floor") or NOISE_FLOOR
    if m is not None:
        out.append(f"  margin over 2nd: {m * 100:.1f}%")
    if nf > NOISE_FLOOR:
        out.append(f"  noise floor: {nf * 100:.1f}% — raised above the default "
                   f"{NOISE_FLOOR * 100:.0f}% by the measured cv of the deciding cells")
    if m is not None and m < nf:
        near = [n for n, t in result["ranked"]
                if result["ranked"][0][1] and
                (t - result["ranked"][0][1]) / float(result["ranked"][0][1]) < nf]
        out += ["",
                f"  !! TOO CLOSE TO CALL — {result['chosen']} leads by {m * 100:.1f}%, inside the",
                f"  !! ~{nf * 100:.0f}% noise floor of this run's timings. These are TIED: "
                f"{', '.join(near)}.",
                "  !! Do not rebuild a schema on this. Break the tie on what the matrix cannot",
                "  !! measure — operability, the shape the app already speaks, blast radius of",
                "  !! change — or re-run with more trials and production-representative volume."]

    # THE DECIDED CHARGING DISCLOSURE (Phase-2): maintenance lives IN the
    # write cells, and the breakdown shows exactly what it cost, per write.
    sm = result.get("summary_maintenance")
    if sm:
        out += ["", "  SUMMARY MAINTENANCE (measured, charged to the write cells)"]
        for row in sm:
            out.append(f"    {row['pattern']:<18} summary {row['summary_us']:>10,.0f}us"
                       f"  vs relational {row['relational_us']:>10,.0f}us"
                       f"  -> {row['delta_us']:+,.0f}us/write is the MV upkeep (+commit)")
        out += ["    (the summary's cells include commit + incremental MV maintenance;",
                "     other designs' cells are rolled back — the bias runs against summary)"]

    # NO SILENT CAPS: a design missing any cell is out of the WHOLE decision —
    # say which design, and which pattern disqualified it, so a 4-way race that
    # became a 3-way one is disclosed rather than discovered.
    if result.get("excluded"):
        out += ["", "  EXCLUDED FROM THE DECISION (a missing cell disqualifies the whole design):"]
        for d, pats in result["excluded"].items():
            out.append(f"    {d} — no measurement for: {', '.join(pats)}")

    if scenarios:
        sw = max([len(s["name"]) for s in scenarios] + [8])
        shapes_s = sorted({n for s in scenarios for n, _ in s["ranked"]})
        out += ["", "SHIFT THE MIX — the same measurements, re-weighted",
                "  (a cell is a property of the schema, not of how often the pattern runs,",
                "   so every scenario below is free: one measurement pass, many workloads)", ""]
        h = f"  {'scenario':<{sw}} {'read:write':>11}" + "".join(f"{s:>13}" for s in shapes_s)
        h += f"  {'winner':<13} {'margin':>7}"
        out += [h, "  " + "-" * (len(h) - 2)]
        for s in scenarios:
            tot = dict(s["ranked"])
            ratio = s["read_write_ratio"]
            if not ratio:
                rw = "read-only"
            elif ratio >= 1:
                rw = f"{ratio:.0f}:1"
            else:
                rw = f"1:{1 / ratio:.0f}"        # write-dominated: don't round it away to 0:1
            line = f"  {s['name']:<{sw}} {rw:>11}"
            line += "".join(f"{tot.get(n, 0):>13,.0f}" for n in shapes_s)
            # winner None is the HONEST verdict (inside the noise floor, or no
            # viable design) — it must render, not TypeError after the
            # measurement has already been paid for.
            if s["winner"] is None:
                line += f"  {'TOO CLOSE TO CALL':<13}"
            else:
                line += f"  {s['winner']:<13} {(s['margin'] or 0) * 100:>6.1f}%"
            if s["separates"]:
                line += "  <= SEPARATES"
            out.append(line)
        out += ["",
                "  A scenario marked SEPARATES beats the field by more than the noise floor —",
                "  there the design is a decision. Where nothing separates, the designs are tied",
                "  and the mix simply does not care which one you pick."]

    if sweep:
        out += ["", "WHERE THE WINNER FLIPS (shrink everything but the dominant read)", ""]
        cols = sorted({s for row in sweep for s in row["totals"]})
        h = f"  {'scale':>7}" + "".join(f"{c:>15}" for c in cols) + "   winner"
        out += [h, "  " + "-" * (len(h) - 2)]
        for row in sweep:
            line = f"  {row['scale']:>7.3g}"
            for c in cols:
                v = row["totals"].get(c)
                line += f"{v:>15,.0f}" if v is not None else f"{'-':>15}"
            out.append(line + f"   {row['winner']}")
    errs = []
    if detail:
        for pname, per_shape in detail.items():
            for s, cell in per_shape.items():
                if isinstance(cell, dict) and "error" in cell:
                    errs.append((pname, s, cell["error"]))
    if errs:
        out += ["", "!! MEASUREMENT ERRORS — these cells are MISSING, so the design was",
                "!! EXCLUDED from the decision above. Fix these before trusting the result:"]
        for pname, s, e in errs:
            out.append(f"   {pname} / {s}: {e}")
    out.append("")
    return "\n".join(out)


# --- the whole loop ------------------------------------------------------------
def optimize(conn, spec, shapes=None, trials=7, warmup=2, do_seed=True,
             fresh=False, write_scale=1.0, walk_scales=None,
             sparse=True, partition_by_type=True, partition=True,
             flex_limit=8192, iot=True, compress=True, progress=None):
    """Steps 1-6 end to end against a live database.

    write_scale/walk_scales tune the election's write mix; sparse/
    partition_by_type tune the single-table realization; partition, iot and
    compress toggle the per-entity partition, organization and compression
    dimensions; flex_limit sets the hybrid flex column's inline guarantee.
    Each knob is passed all the way through — a
    knob that exists but is not threaded is the write_scale regression this
    signature exists to prevent."""
    model, patterns = spec["model"], spec["patterns"]
    # The consolidation walk competes by default: document -> single collection -> duality
    # -> relational. Anything the agent declared itself is kept; the rest is derived from
    # the patterns and relationships.
    model = propose_projections(model, patterns)
    cands = candidate_shapes(model, patterns, only=shapes)
    if progress:
        progress(f"candidate designs: {', '.join(cands)}")

    if fresh:
        if progress:
            progress("dropping every object (a re-fill leaves the old high-water mark behind)")
        drop_all(conn, model)
    for st in sorted({storage_shape(s) for s in cands}):
        if progress:
            progress(f"deploying {st} storage (+ access-pattern-derived indexes)")
        deploy(conn, model, patterns, st, sparse=sparse,
               partition_by_type=partition_by_type, partition=partition,
               flex_limit=flex_limit, iot=iot, compress=compress)
    if do_seed and spec.get("seed"):
        if progress:
            progress("seeding representative volume")
        # The single collection and the hybrid lane are populated FROM the relational
        # overlay, so every design holds the same data — otherwise the comparison
        # measures the seed, not the shape.
        seed(conn, spec["seed"],
             model if ({"single_table", "hybrid", "summary"} & set(cands)) else None)
    try:
        gather_stats(conn)
    except Exception:
        pass

    # MODEL VALIDATION, before a single timing. Every design must return the SAME ANSWER;
    # a design that returns less is faster, and a stopwatch cannot tell the difference.
    if progress:
        progress("validating: every design must return the same answer")
    invalid, empty = validate_answers(conn, model, patterns, cands, progress=progress)

    if progress:
        progress(f"measuring {len(patterns)} patterns x {len(cands)} designs on the live DB")
    meas, detail = measure(conn, model, patterns, cands, trials=trials, warmup=warmup,
                           invalid=invalid)

    result = build_result(model, patterns, meas, write_scale=write_scale,
                          walk_scales=walk_scales, detail=detail)
    result["invalid"] = invalid
    result["empty_patterns"] = empty
    result["sweep"] = flip_sweep(model, patterns, meas)
    if spec.get("scenarios"):
        result["scenarios"] = scenario_sweep(model, patterns, meas, spec["scenarios"],
                                             detail=detail)
    result["detail"] = detail
    result["ddl"] = winning_ddl(model, result["chosen"],
                                sparse=sparse, partition_by_type=partition_by_type,
                                partition=partition, flex_limit=flex_limit,
                                iot=iot, compress=compress)
    return result

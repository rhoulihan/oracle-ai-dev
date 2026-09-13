# Copyright (c) 2026 Oracle and/or its affiliates.
"""Canonical result-set hashing for equivalence checks.

Two result sets are equivalent when they carry the same logical content — the
same rows with the same values — regardless of row order, column order, or the
minor type formatting a driver applies (10 vs "10" vs 10.0). Used to gate shape
comparisons in the benchmark (P9: a shape that looks fast because it returns the
wrong rows must not win) and to verify the generated data layer returns consistent
results across runtimes.
"""
import hashlib
import json


def _norm_scalar(v):
    """Normalize a scalar so 10, 10.0, and "10" compare equal; None stays None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return int(f) if f.is_integer() else f
    s = str(v).strip()
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return s


def _norm_row(row):
    """A row (dict or sequence) -> a sorted tuple of (key, normalized-value).
    Dict rows key by column name; sequences key by position."""
    if isinstance(row, dict):
        items = row.items()
    else:
        items = enumerate(row)
    return tuple(sorted((str(k), _norm_scalar(v)) for k, v in items))


def _canonical(rows):
    return sorted(_norm_row(r) for r in rows)


def canonical_hash(rows) -> str:
    """A stable hash of a result set, invariant to row/column order and scalar
    formatting."""
    canon = _canonical(rows)
    payload = json.dumps(canon, default=str, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def results_equivalent(a, b) -> bool:
    """True if two result sets carry the same logical content (row count included)."""
    return canonical_hash(a) == canonical_hash(b)


# --- cross-DESIGN equivalence ---------------------------------------------------
# The four designs answer the same question in four legitimately different SHAPES:
#
#   relational     flat columns, child collections as JSON_ARRAYAGG columns
#   document       one nested JSON document per row
#   duality        one nested JSON document per row, nested differently again
#   single table   one row PER ITEM TYPE, every other type's columns NULL
#
# So the raw rows cannot be hashed against each other. What IS comparable is the ANSWER:
# for every property the query asked for, the set of values that came back. That is
# invariant to nesting, to row-vs-column, to key order — and it still catches every way a
# design can silently answer a different question:
#
#   * a join that never happened   (duality returned the junction keys, no flight number)
#   * a collection that was empty  (the "document" embedded nothing)
#   * a filter that matched nothing (`status = 'OPEN'` against PENDING/CONFIRMED/CANCELLED)
#   * a wrong value, a dropped row, stale data in one projection
#
# It deliberately compares SETS of values, not multisets: the relational fan-trap join
# returns each leg once per payment, which is a performance defect (fixed elsewhere) rather
# than a different answer. Duplicate multiplicity is the one difference this will not flag.
#
# Pools alone are not enough, though: a broken join can return the right value POOLS in the
# WRONG PAIRINGS — every payment amount present, each attached to the wrong reservation. So
# alongside the pools, the answer records which wanted values appeared TOGETHER in one row,
# and two answers must pair them the same way wherever BOTH express the pairing. "Wherever
# both" because the pairing is not shape-invariant: the single collection legitimately
# answers with one row per item type, pairing nothing with anything.


def _collect(value, out, key=None):
    """{property -> set of values} for every scalar reachable in a row, at any depth.
    A scalar inside an array belongs to the property that named the array —
    `{"tags": ["red", "small"]}` answers `tags` with red and small.
    NULLs are not values: a column that is present but never populated has answered
    nothing, which is exactly how a broken join hides."""
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                _collect(v, out, key=str(k).lower())
            elif v is not None:
                out.setdefault(str(k).lower(), set()).add(_norm_scalar(v))
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, (dict, list)):
                _collect(v, out, key=key)
            elif v is not None and key is not None:
                out.setdefault(key, set()).add(_norm_scalar(v))


def _scopes(value, inherited=None):
    """Pairing scopes for one row: each dict node — the row itself, or an array
    element at any depth — pairs its OWN scalars (and scalar-array values) with its
    ANCESTORS' scalars, never with a sibling element's. Pooling the whole row and
    cross-producting invented pairings a nested answer never made (FL1 with FL2's
    departure time), which both failed correct typed-row answers and waved through
    nested answers whose elements paired values wrongly."""
    if isinstance(value, list):
        out = []
        for x in value:
            if isinstance(x, (dict, list)):
                out.extend(_scopes(x, inherited))
        return out
    if not isinstance(value, dict):
        return []
    own = {k: set(v) for k, v in (inherited or {}).items()}
    children = []
    for k, v in value.items():
        key = str(k).lower()
        if isinstance(v, dict):
            children.append(v)
        elif isinstance(v, list):
            if any(isinstance(x, (dict, list)) for x in v):
                children.append(v)
            else:
                for x in v:
                    if x is not None:
                        own.setdefault(key, set()).add(_norm_scalar(x))
        elif v is not None:
            own.setdefault(key, set()).add(_norm_scalar(v))
    out = [own]
    for c in children:
        out.extend(_scopes(c, own))
    return out


def _unwrap(row):
    """A row that is a single JSON column IS the document — unwrap it, so `SELECT d.data`
    and `SELECT JSON_OBJECT(...) AS doc` compare against flat columns. A single column
    holding a list of SCALARS is not a wrapper, though — it is an array property, and
    unwrapping it would lose the property name its values answer."""
    if isinstance(row, dict) and len(row) == 1:
        only = next(iter(row.values()))
        if isinstance(only, dict):
            return only
        if isinstance(only, list) and all(isinstance(v, (dict, list)) for v in only):
            return only
    return row


def canonical_answer(query, rows, id_prop=None):
    """The shape-independent ANSWER to `query` — comparable across every design.

    reads:      {requested property -> frozenset of values returned}, plus the
                row-wise PAIRINGS — for each pair of wanted properties that came
                back together in one row, the set of value pairs they formed
    aggregates: a set of groups, each a sorted tuple of (alias, value)

    `id_prop` is the root's primary-key property. In a document the root key is spelled
    `_id` — the query asks for `reservation_id` and the document answers with `_id`. Same
    value, different name; not a different answer.
    """
    is_agg = bool(query.get("aggregates") or query.get("group_by"))
    if is_agg:
        names = {r.split(".", 1)[1].lower() for r in (query.get("group_by") or []) if "." in r}
        names |= {str(a.get("name", "")).lower() for a in (query.get("aggregates") or [])}
        groups = set()
        for row in rows or []:
            flat = {}
            _collect(_unwrap(row), flat)
            groups.add(tuple(sorted((k, sorted(v)[0]) for k, v in flat.items()
                                    if k in names and v)))
        return {"kind": "aggregate", "groups": frozenset(groups)}

    want = {r.split(".", 1)[1].lower() for r in (query.get("returns") or []) if "." in r}
    found, pairs = {}, {}
    for row in rows or []:
        rowf = {}
        _collect(_unwrap(row), rowf)
        for k, vals in rowf.items():
            found.setdefault(k, set()).update(vals)
        # The pairings: which wanted values appeared TOGETHER — per pairing SCOPE
        # (the row, or each array element with its ancestors), not per pooled row.
        # Sets, not multisets, for the same fan-trap reason as the pools above.
        for scope in _scopes(_unwrap(row)):
            keys = sorted(k for k in scope if k in want)
            for i, p in enumerate(keys):
                for q in keys[i + 1:]:
                    pairs.setdefault((p, q), set()).update(
                        (pv, qv) for pv in scope[p] for qv in scope[q])
    if id_prop and "_id" in found:
        found.setdefault(str(id_prop).lower(), found["_id"])
    return {"kind": "rows",
            "facts": {p: frozenset(found.get(p, ())) for p in sorted(want)},
            "pairs": {k: frozenset(v) for k, v in pairs.items()}}


def is_empty_answer(answer) -> bool:
    """Nothing came back. Four designs agreeing on nothing is not agreement — it means the
    pattern's filter matches no data, and the cell is timing an index probe that finds
    nothing rather than the query the workload actually runs."""
    if not answer:
        return True
    if answer.get("kind") == "aggregate":
        return not answer["groups"]
    return not any(answer["facts"].values())


def answers_match(a, b) -> bool:
    """True when two designs answered the query identically."""
    if not a or not b or a.get("kind") != b.get("kind"):
        return False
    if a["kind"] == "aggregate":
        return a["groups"] == b["groups"]
    if a["facts"] != b["facts"]:
        return False
    # Row-wise pairings must agree wherever BOTH designs express them. A design that
    # never co-locates two properties in one row (the single collection answers one
    # row per item type) has no pairing to check — but two designs that both pair
    # status with amount must pair them the SAME way, or one joined the wrong rows.
    ap, bp = a.get("pairs") or {}, b.get("pairs") or {}
    return all(ap[k] == bp[k] for k in set(ap) & set(bp))


def answer_diff(ref, other):
    """Why they disagree, in the words of the query — for the report."""
    if not ref or not other or ref.get("kind") != other.get("kind"):
        return ["the two designs returned incomparable result kinds"]
    if ref["kind"] == "aggregate":
        missing, extra = ref["groups"] - other["groups"], other["groups"] - ref["groups"]
        out = []
        if missing:
            out.append(f"{len(missing)} group(s) missing, e.g. {sorted(missing)[0]}")
        if extra:
            out.append(f"{len(extra)} unexpected group(s), e.g. {sorted(extra)[0]}")
        return out
    out = []
    for prop, vals in ref["facts"].items():
        got = other["facts"].get(prop, frozenset())
        if got == vals:
            continue
        if not got:
            out.append(f"{prop}: returned nothing (expected {len(vals)} value(s))")
        else:
            miss, extra = vals - got, got - vals
            bits = []
            if miss:
                bits.append(f"missing {sorted(miss, key=str)[:3]}")
            if extra:
                bits.append(f"unexpected {sorted(extra, key=str)[:3]}")
            out.append(f"{prop}: " + ", ".join(bits))
    ap, bp = ref.get("pairs") or {}, other.get("pairs") or {}
    for p, q in sorted(set(ap) & set(bp)):
        if ap[(p, q)] != bp[(p, q)]:
            out.append(f"{p}+{q}: the same values come back paired into different rows "
                       f"(a join matched the wrong rows)")
    return out

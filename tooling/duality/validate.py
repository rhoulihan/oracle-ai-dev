# Copyright (c) 2026 Oracle and/or its affiliates.
"""Enforce the duality design gates that a ModelSpec alone can decide.

`skills/oracle-data-modeling/references/duality-design-gates.md` states the
rulebook; this module is its enforcement for the spec-level subset, and gate
numbers map 1:1 to the RULE numbering there. Severity mirrors the measured
optimizer's own split: a BLOCKER refuses to emit (the view cannot exist, or
exists and is silently wrong); a WARNING emits and annotates (a design-quality
call the user may legitimately override). Gates that need the live data
dictionary (7 nullability, 10 textual JSON, 22 VPD, 23 indexes) or human
judgment (17, 19-21) remain live/advisory checks in the reference.
"""

from dataclasses import dataclass

from tooling.generate.ddl import (_junction_far_side, _needed_for, _pks,
                                  duality_views, is_junction)
from tooling.generate.model import validate_model

# Gate 9: duality's projected-column type allowlist (26ai). Base token only —
# length, precision, and WITH TIME ZONE qualifiers do not change eligibility.
_TYPE_ALLOWLIST = {
    "JSON", "VARCHAR2", "NVARCHAR2", "VARCHAR", "CHAR", "NCHAR",
    "CLOB", "NCLOB", "BLOB", "RAW", "BOOLEAN",
    "NUMBER", "INTEGER", "INT", "SMALLINT", "FLOAT", "REAL", "DECIMAL",
    "NUMERIC", "DOUBLE", "BINARY_DOUBLE", "BINARY_FLOAT",
    "DATE", "TIMESTAMP", "INTERVAL", "VECTOR",
}


@dataclass(frozen=True)
class Violation:
    gate: int        # RULE number in duality-design-gates.md; 0 = ModelSpec defect
    severity: str    # "blocker" | "warning"
    where: str       # view name (view-scoped) or entity/model (spec-scoped)
    message: str

    def __str__(self):
        return f"{self.severity.upper()} gate-{self.gate} [{self.where}] {self.message}"


class DualityGateError(ValueError):
    """Raised by the DDL emit path when a duality view trips a blocker gate."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__("; ".join(str(v) for v in self.violations))


def validate_duality(model, root=None) -> list:
    """Every gate finding for the duality projections of `root` (default: all
    declared roots) -> [Violation]. Empty == clean; blockers mean the DDL must
    not be emitted."""
    base = validate_model(model)
    if base:
        return [Violation(0, "blocker", "model", m) for m in base]
    decl = (model.get("projections") or {}).get("duality") or {}
    out = []
    for r in ([root] if root else decl):
        out += _validate_root(model, r)
    return out


def _base_type(t):
    return t.split(" GENERATED")[0].split("(")[0].split()[0].upper()


def _validate_root(model, root):
    ents = model["entities"]
    e = ents.get(root)
    views = duality_views(model, root)
    if e is None:
        return [Violation(2, "blocker", v["view"],
                          f"projection root {root!r} is not a known entity")
                for v in views] or \
               [Violation(2, "blocker", str(root),
                          f"projection root {root!r} is not a known entity")]

    # Gate 1 — the root key becomes the document _id; keyless is un-rootable.
    pks = _pks(e)
    if not pks or not all(pks):
        return [Violation(1, "blocker", v["view"],
                          f"root {root} declares no PK/UK; a keyless table cannot "
                          f"root a duality view (ORA-42647)")
                for v in views]

    out = []
    for v in views:
        out += _validate_view(model, root, v)

    # Gate 18 — one view per aggregate root: a single all-in view makes every
    # point read pay for the widest read's joins.
    if len(views) == 1 and views[0]["includes"] is None:
        parents, children, _ = _needed_for(model, root, None)
        n = len(parents) + len(children)
        if n >= 2:
            out.append(Violation(18, "warning", views[0]["view"],
                                 f"single all-in view nests {n} entities; a view costs "
                                 f"exactly what it nests — consider one lean view per aggregate"))
    return out


def _validate_view(model, root, v):
    out = []
    ents = model["entities"]
    name = v["view"]
    inc = None if v["includes"] is None else set(v["includes"])

    # Gate 2 — every included entity must exist and be reachable from the root
    # (as a parent, a child, or a junction far-side): the generator would
    # otherwise SILENTLY omit it and its queries would match nothing.
    if inc is not None:
        for u in sorted(inc - set(ents)):
            out.append(Violation(2, "blocker", name,
                                 f"includes names unknown entity {u!r}"))
        inc &= set(ents)
    parents, children, _ = _needed_for(model, root, inc)
    fars = [far for r in children
            for far, _ in _junction_far_side(model, r["to"], root)
            if inc is None or far in inc]
    if inc is not None:
        reach = {p for p, _ in parents} | {r["to"] for r in children} | set(fars)
        for miss in sorted(inc - reach):
            out.append(Violation(2, "blocker", name,
                                 f"{miss} is not reachable from root {root} as a parent, "
                                 f"child, or junction far-side; the generated view would "
                                 f"silently omit it"))

    # Gate 3 — the parent side of every nesting join must be that entity's key;
    # joining to a non-unique column fans rows out and breaks one-doc-per-root.
    for rel in model.get("relationships", []):
        card = (rel.get("cardinality") or "1:N").upper()
        parent = pcol = None
        if rel["from"] == root and card == "N:1":
            parent, pcol = rel["to"], rel["to_key"]
        elif rel["to"] == root and card in ("1:N", "1:1") and not is_junction(model, rel["from"]):
            parent, pcol = rel["from"], rel["from_key"]
        if parent and parent in ents and (inc is None or parent in inc) \
                and pcol not in _pks(ents[parent]):
            out.append(Violation(3, "blocker", name,
                                 f"{root}->{parent} joins on {parent}.{pcol}, which is not "
                                 f"{parent}'s key; a non-unique parent-side join fans rows out"))
    for rel in children:
        if rel["from_key"] not in _pks(ents[root]):
            out.append(Violation(3, "blocker", name,
                                 f"child {rel['to']} joins the root on {root}.{rel['from_key']}, "
                                 f"which is not {root}'s key"))
        for far, frel in _junction_far_side(model, rel["to"], root):
            if inc is not None and far not in inc:
                continue
            pcol = frel["from_key"] if frel.get("from") == far else frel["to_key"]
            if pcol not in _pks(ents[far]):
                out.append(Violation(3, "blocker", name,
                                     f"junction {rel['to']} joins {far} on {far}.{pcol}, "
                                     f"which is not {far}'s key"))

    # Gate 9 — every declared column type on a projected entity must sit on the
    # duality allowlist; an unsupported type is a modeling decision, not a
    # CREATE-time surprise.
    touched = [root] + [p for p, _ in parents] + [r["to"] for r in children] + fars
    for ent in dict.fromkeys(touched):
        ee = ents[ent]
        declared = dict(ee.get("column_types") or {})
        if ee.get("pk_type"):
            declared.setdefault("<pk>", ee["pk_type"])
        for prop, t in declared.items():
            if _base_type(t) not in _TYPE_ALLOWLIST:
                out.append(Violation(9, "blocker", name,
                                     f"{ent}.{prop} declares type {t!r}, off the duality "
                                     f"column-type allowlist — retype, exclude, or project around it"))

    # Gate 11 — self-nesting has no distinct-predicate syntax in the spec, and
    # duplicate JSON keys at one level make an invalid document.
    nested = {p for p, _ in parents} | {r["to"] for r in children} | set(fars)
    if root in nested:
        out.append(Violation(11, "blocker", name,
                             f"{root} nests under itself; the spec cannot express the "
                             f"distinct join predicate an acyclic document needs"))

    pks = _pks(ents[root])
    cols_scope = v.get("columns")

    def props_of(ent):
        return None if cols_scope is None else cols_scope.get(ent, [])

    def level_keys(ent, extra=()):
        ee, props = ents[ent], props_of(ent)
        keys = list(_pks(ee))
        keys += [p for p, c in (ee.get("columns") or {}).items()
                 if c not in _pks(ee) and (props is None or p in props)]
        return keys + list(extra)

    parent_fks = {fk for _, fk in parents if fk}
    rp = props_of(root)
    root_keys = (["_id"] if len(pks) == 1 else list(pks))
    root_keys += [p for p, c in (ents[root].get("columns") or {}).items()
                  if c not in pks and c not in parent_fks and (rp is None or p in rp)]
    root_keys += [p.lower() for p, _ in parents]
    root_keys += [r["to"].lower() + "s" for r in children]
    levels = [("document root", root_keys)]
    levels += [(p, level_keys(p)) for p, _ in parents if p != root]
    for r in children:
        if r["to"] == root:
            continue
        far_keys = [f.lower() for f, _ in _junction_far_side(model, r["to"], root)
                    if inc is None or f in inc]
        levels.append((r["to"], level_keys(r["to"], far_keys)))
    for where, keys in levels:
        for dup in sorted({k for k in keys if keys.count(k) > 1}):
            out.append(Violation(11, "blocker", name,
                                 f"duplicate key {dup!r} at one object level ({where}); "
                                 f"duplicate keys make an invalid document"))

    # Gate 12 — generated views are writable by default (the optimizer must
    # measure writes); the gate wants each writable table recorded on purpose.
    out.append(Violation(12, "warning", name,
                         "writable view: root and child tables carry @insert @update "
                         "@delete; record each writable table as a deliberate decision"))
    return out

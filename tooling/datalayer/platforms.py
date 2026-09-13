# Copyright (c) 2026 Oracle and/or its affiliates.
"""Render a full data-access layer from a datalayer spec — one method per access
pattern, per platform. The SQL comes from `bound_sql` (parameterized), so every
method binds its inputs by name; no literal is ever inlined.

Spec: {"model": ModelSpec, "patterns": [{"name","shape","query"}, ...],
       "platforms": [...]?}. Default = every supported platform.

Generated code reads the connection from environment variables (DB_USER,
DB_PASSWORD, DB_DSN) rather than embedding credentials.
"""
from tooling.datalayer.generate import bound_sql
from tooling.generate.ddl import (duality_views, generate_ddl, generate_indexes,
                                  json_value_expr)

ALL_PLATFORMS = ["python", "node", "java", "go", "dotnet"]


# ---- name helpers ---------------------------------------------------------
def _parts(name):
    return [p for p in name.replace("-", "_").split("_") if p]


def _snake(name):
    return "_".join(_parts(name)).lower()


def _camel(name):
    p = _parts(name)
    return p[0].lower() + "".join(w.capitalize() for w in p[1:]) if p else name


def _pascal(name):
    return "".join(w.capitalize() for w in _parts(name)) or name


def _bind_names(binds):
    # distinct, in first-seen order
    seen, out = set(), []
    for b in binds:
        if b["name"] not in seen:
            seen.add(b["name"])
            out.append(b["name"])
    return out


def _embed(sql, style):
    """Embed a SQL string into a target-language literal safely."""
    if style == "py":       # triple-quoted; SQL never contains \"\"\"
        return '"""' + sql + '"""'
    if style == "backtick":  # node / go raw — SQL never contains a backtick
        return "`" + sql + "`"
    if style == "java":     # one line, escape double quotes
        return '"' + " ".join(sql.split()).replace('"', '\\"') + '"'
    if style == "csharp":   # verbatim @, double the double quotes
        return '@"' + sql.replace('"', '""') + '"'
    raise ValueError(style)


def _duality_write_roots(spec):
    """The optimistic-write targets: one per DISTINCT root the duality patterns
    touch -> [(root, view, typed _id expression)]. A composite-key root has no
    single `_id` and gets no generated write pair; the widest declared view is
    the write path (a scoped view leaves unprojected columns untouched, which
    is not what "replace the document" means)."""
    model = spec["model"]
    out, seen = [], set()
    for p in spec["patterns"]:
        root = p["query"]["root"]
        if p["shape"] != "duality" or root in seen:
            continue
        seen.add(root)
        e = model["entities"][root]
        if isinstance(e["pk"], list):
            continue
        specs = duality_views(model, root)
        if not specs:
            continue
        view = next((v for v in specs if v["includes"] is None),
                    max(specs, key=lambda v: len(v["includes"] or ())))
        prop = next((pr for pr, c in (e.get("columns") or {}).items() if c == e["pk"]),
                    e["pk"])
        out.append((root, view["view"], json_value_expr(model, root, prop, path="$._id")))
    return out


# ---- per-platform renderers ----------------------------------------------
def _render_python(patterns, schema_ddl=None, probe=None, duality_writes=None):
    L = ['# Generated data-access layer (python-oracledb). Binds by name; reads',
         '# the connection from DB_USER / DB_PASSWORD / DB_DSN.',
         'import os', 'import oracledb', '', '',
         'def connect():',
         '    return oracledb.connect(user=os.environ["DB_USER"],',
         '                            password=os.environ["DB_PASSWORD"],',
         '                            dsn=os.environ["DB_DSN"])', '']
    if duality_writes:
        L += ['',
              'class StaleDocumentError(Exception):',
              '    """The document changed since it was read (ORA-42699) — re-read,',
              '    re-apply the change, and retry. Map to HTTP 409 in an API."""', '']
    if schema_ddl:
        L += [f'SCHEMA_DDL = {_embed(schema_ddl, "py")}', '',
              'def ensure_schema(conn):',
              '    """Deploy the schema if it is not already present. Returns True if',
              '    it deployed, False if it already existed."""',
              '    with conn.cursor() as cur:',
              '        try:',
              f'            cur.execute("SELECT 1 FROM {probe} WHERE ROWNUM = 1")',
              '            return False',
              '        except oracledb.DatabaseError:',
              '            pass',
              '    for stmt in (s.strip() for s in SCHEMA_DDL.split(";")):',
              '        if not stmt:',
              '            continue',
              '        try:',
              '            with conn.cursor() as cur:',
              '                cur.execute(stmt)',
              '        except oracledb.DatabaseError as exc:',
              '            # tolerate "already exists" so a partial prior deploy is idempotent',
              '            if exc.args[0].code not in (955, 1430, 2260, 2264, 2275):',
              '                raise',
              '    conn.commit()',
              '    return True', '']
    for root, view, id_expr in duality_writes or ():
        fn = _snake(root)
        get_c, rep_c = f"SQL_GET_{fn.upper()}_DOC", f"SQL_REPLACE_{fn.upper()}_DOC"
        get_sql = f"SELECT d.data\nFROM {view} d\nWHERE {id_expr} = :id"
        rep_sql = f"UPDATE {view} d\nSET d.data = :doc\nWHERE {id_expr} = :id"
        L += [f'{get_c} = {_embed(get_sql, "py")}', '',
              f'def get_{fn}_doc(conn, doc_id):',
              f'    """One {root} document, INCLUDING _metadata — the etag must round-trip',
              '    (duality design gate 16): strip it anywhere between read and write and',
              '    conflict detection silently disappears."""',
              '    with conn.cursor() as cur:',
              f'        cur.execute({get_c}, {{"id": doc_id}})',
              '        row = cur.fetchone()',
              '        return row[0] if row else None', '',
              f'{rep_c} = {_embed(rep_sql, "py")}', '',
              f'def replace_{fn}_doc(conn, doc):',
              f'    """Optimistic replace through {view}. `doc` is the document AS READ',
              f'    (get_{fn}_doc), modified in place, _metadata untouched: Oracle compares',
              '    the embedded etag and raises ORA-42699 on a stale write. A document',
              '    with _metadata stripped would write UNCHECKED, so it is refused before',
              '    any database call. Raises StaleDocumentError on conflict."""',
              '    if not isinstance(doc, dict) or "_metadata" not in doc or "_id" not in doc:',
              '        raise ValueError("replace needs the document as read: _id and _metadata"',
              '                         " must round-trip unmodified (design gate 16)")',
              '    with conn.cursor() as cur:',
              '        try:',
              '            # NATIVE JSON bind: the driver reads NUMBER values back as',
              '            # decimal.Decimal, which a text serializer would reject.',
              '            cur.setinputsizes(doc=oracledb.DB_TYPE_JSON)',
              f'            cur.execute({rep_c}, {{"doc": doc, "id": doc["_id"]}})',
              '        except oracledb.DatabaseError as exc:',
              '            if exc.args[0].code == 42699:',
              '                raise StaleDocumentError(str(exc)) from exc',
              '            raise',
              '        conn.commit()',
              '        return cur.rowcount', '']
    for p in patterns:
        const = "SQL_" + _snake(p["name"]).upper()
        args = _bind_names(p["binds"])
        # keyword-only binds — but a zero-bind pattern (an aggregation) must
        # not render `def f(conn, *):`, which is a SyntaxError that poisons
        # the whole generated module (caught live by the e2e exercise).
        kw = ", *" + "".join(", " + a for a in args) if args else ""
        params = "{" + ", ".join(f"'{a}': {a}" for a in args) + "}"
        L += [f'{const} = {_embed(p["sql"], "py")}', '',
              f'def {_snake(p["name"])}(conn{kw}):',
              f'    """{p["name"]} — {p["shape"]} shape."""',
              '    with conn.cursor() as cur:',
              f'        cur.execute({const}, {params})',
              '        cols = [c[0] for c in cur.description]',
              '        return [dict(zip(cols, r)) for r in cur.fetchall()]', '']
    return "\n".join(L)


def _render_node(patterns):
    L = ['// Generated data-access layer (node-oracledb). Binds by name; reads the',
         '// connection from DB_USER / DB_PASSWORD / DB_DSN.',
         "const oracledb = require('oracledb');", '',
         'async function getConnection() {',
         '  return oracledb.getConnection({ user: process.env.DB_USER,',
         '    password: process.env.DB_PASSWORD, connectString: process.env.DB_DSN });',
         '}', '']
    exports = ['getConnection']
    for p in patterns:
        const = "SQL_" + _snake(p["name"]).upper()
        fn = _camel(p["name"])
        args = _bind_names(p["binds"])
        L += [f'const {const} = {_embed(p["sql"], "backtick")};', '',
              f'// {p["name"]} — {p["shape"]} shape',
              f'async function {fn}(conn, {{ {", ".join(args)} }}) {{',
              f'  const r = await conn.execute({const}, {{ {", ".join(args)} }},',
              '    { outFormat: oracledb.OUT_FORMAT_OBJECT });',
              '  return r.rows;', '}', '']
        exports.append(fn)
    L += [f'module.exports = {{ {", ".join(exports)} }};']
    return "\n".join(L)


def _render_java(patterns):
    L = ['// Generated data-access layer (Oracle JDBC). Binds by name via the Oracle',
         '// extension; reads DB_USER / DB_PASSWORD / DB_DSN from the environment.',
         'import java.sql.*;',
         'import oracle.jdbc.OraclePreparedStatement;', '',
         'public final class Repository {',
         '  public static Connection connect() throws SQLException {',
         '    return DriverManager.getConnection("jdbc:oracle:thin:@" + System.getenv("DB_DSN"),',
         '        System.getenv("DB_USER"), System.getenv("DB_PASSWORD"));',
         '  }']
    for p in patterns:
        const = "SQL_" + _snake(p["name"]).upper()
        fn = _camel(p["name"])
        args = _bind_names(p["binds"])
        sig = ", ".join(f"Object {a}" for a in args)
        binds = "\n".join(f'    ps.setObjectAtName("{a}", {a});' for a in args)
        L += [f'  static final String {const} = {_embed(p["sql"], "java")};',
              f'  // {p["name"]} — {p["shape"]} shape',
              f'  public static ResultSet {fn}(Connection conn{", " + sig if sig else ""}) throws SQLException {{',
              f'    OraclePreparedStatement ps = (OraclePreparedStatement) conn.prepareStatement({const});',
              binds,
              '    return ps.executeQuery();', '  }']
    L += ['}']
    return "\n".join(L)


def _render_go(patterns):
    L = ['// Generated data-access layer (godror). Binds by name; reads the',
         '// connection from DB_USER / DB_PASSWORD / DB_DSN.',
         'package datalayer', '',
         'import (', '\t"database/sql"', '\t"os"', '', '\t_ "github.com/godror/godror"', ')', '',
         'func Connect() (*sql.DB, error) {',
         '\treturn sql.Open("godror", `user="`+os.Getenv("DB_USER")+`" password="`+os.Getenv("DB_PASSWORD")+`" connectString="`+os.Getenv("DB_DSN")+`"`)',
         '}', '']
    for p in patterns:
        const = "SQL" + _pascal(p["name"])
        fn = _pascal(p["name"])
        args = _bind_names(p["binds"])
        sig = ", ".join(f"{a} interface{{}}" for a in args)
        named = ", ".join(f'sql.Named("{a}", {a})' for a in args)
        L += [f'const {const} = {_embed(p["sql"], "backtick")}', '',
              f'// {fn} — {p["shape"]} shape',
              f'func {fn}(db *sql.DB{", " + sig if sig else ""}) (*sql.Rows, error) {{',
              f'\treturn db.Query({const}{", " + named if named else ""})', '}', '']
    return "\n".join(L)


def _render_dotnet(patterns):
    L = ['// Generated data-access layer (ODP.NET managed). BindByName; reads the',
         '// connection from DB_USER / DB_PASSWORD / DB_DSN.',
         'using System;',
         'using Oracle.ManagedDataAccess.Client;', '',
         'public static class Repository {',
         '  public static OracleConnection Connect() {',
         '    // read into locals first — nested quotes inside an interpolated string are invalid C#',
         '    var u = Environment.GetEnvironmentVariable("DB_USER");',
         '    var p = Environment.GetEnvironmentVariable("DB_PASSWORD");',
         '    var d = Environment.GetEnvironmentVariable("DB_DSN");',
         '    var c = new OracleConnection($"User Id={u};Password={p};Data Source={d}");',
         '    c.Open(); return c;',
         '  }']
    for p in patterns:
        const = "Sql" + _pascal(p["name"])
        fn = _pascal(p["name"])
        args = _bind_names(p["binds"])
        sig = ", ".join(f"object {a}" for a in args)
        binds = "\n".join(f'    cmd.Parameters.Add("{a}", {a});' for a in args)
        L += [f'  const string {const} = {_embed(p["sql"], "csharp")};',
              f'  // {p["name"]} — {p["shape"]} shape',
              f'  public static OracleDataReader {fn}(OracleConnection conn{", " + sig if sig else ""}) {{',
              f'    var cmd = new OracleCommand({const}, conn) {{ BindByName = true }};',
              binds,
              '    return cmd.ExecuteReader();', '  }']
    L += ['}']
    return "\n".join(L)


_RENDER = {
    "python": ("repository.py", _render_python),
    "node": ("repository.js", _render_node),
    "java": ("Repository.java", _render_java),
    "go": ("repository.go", _render_go),
    "dotnet": ("Repository.cs", _render_dotnet),
}


def _schema_for(spec):
    """The CREATE DDL for the optimal schema — the union of the shapes the access
    patterns use. Duality's DDL already includes the base tables, so it subsumes
    a relational realization; document adds its collection."""
    model = spec["model"]
    shapes = {p["shape"] for p in spec["patterns"]}
    parts = []
    if "duality" in shapes:
        parts.append(generate_ddl(model, "duality"))
    elif shapes & {"relational", "sql_view"}:
        parts.append(generate_ddl(model, "relational"))
    if "document" in shapes:
        parts.append(generate_ddl(model, "document"))
    # Indexes DERIVED from the access-pattern filter conditions — analyze index
    # requirements before trusting any performance numbers.
    for shape in sorted(shapes):
        qs = [p["query"] for p in spec["patterns"] if p["shape"] == shape]
        idx = generate_indexes(model, qs, "document" if shape == "document" else "relational")
        if idx:
            parts.append("-- Indexes derived from the access patterns\n" + idx)
    return "\n\n".join(parts)


def _probe_object(spec):
    """A representative object to test for the schema's presence."""
    model = spec["model"]
    shapes = {p["shape"] for p in spec["patterns"]}
    if "document" in shapes and not (shapes & {"relational", "sql_view", "duality"}):
        # document-only: probe the collection
        docs = (model.get("projections") or {}).get("document") or {}
        return next(iter(docs.values()))["collection"]
    # else a base table exists — probe the first pattern root's table
    root = spec["patterns"][0]["query"]["root"]
    return model["entities"][root]["table"]


_DEPLOY_SH = """#!/usr/bin/env bash
# Deploy the generated schema. Reads DB_USER / DB_PASSWORD / DB_DSN.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CONNECT="${DB_USER}/${DB_PASSWORD}@${DB_DSN}"
# A `sql` that EXISTS is not a `sql` that WORKS: on developer machines the name
# is often a shim or another tool entirely, and trusting it fails opaquely.
# Require it to identify as SQLcl; otherwise fall back to sqlplus; otherwise
# say exactly what is missing.
if command -v sql >/dev/null 2>&1 && sql -version 2>/dev/null </dev/null | grep -qi sqlcl; then
  exec sql -S "$CONNECT" < "$HERE/schema.sql"
elif command -v sqlplus >/dev/null 2>&1; then
  exec sqlplus -S -L "$CONNECT" < "$HERE/schema.sql"
else
  echo "deploy.sh: no usable SQL client — need Oracle SQLcl ('sql' must identify itself as SQLcl) or sqlplus on PATH" >&2
  exit 1
fi
"""


def render_all(spec):
    """Return {filename: source} for the requested platforms (default: all)."""
    model = spec["model"]
    platforms = spec.get("platforms") or ALL_PLATFORMS
    unknown = [p for p in platforms if p not in _RENDER]
    if unknown:
        raise ValueError(f"unknown platform(s): {unknown}; supported: {ALL_PLATFORMS}")

    # Compute the bound SQL once per pattern; every platform shares it.
    compiled = []
    for pat in spec["patterns"]:
        sql, binds = bound_sql(model, pat["query"], pat["shape"])
        compiled.append({"name": pat["name"], "shape": pat["shape"],
                         "sql": sql, "binds": binds})

    schema_ddl = _schema_for(spec)
    probe = _probe_object(spec)
    duality_writes = _duality_write_roots(spec)

    out = {}
    for plat in platforms:
        fname, fn = _RENDER[plat]
        if plat == "python":
            out[fname] = fn(compiled, schema_ddl=schema_ddl, probe=probe,
                            duality_writes=duality_writes)
        else:
            out[fname] = fn(compiled)
    if schema_ddl:
        # statement-terminated for sqlplus/SQLcl
        out["schema.sql"] = ";\n".join(s.strip() for s in schema_ddl.split(";") if s.strip()) + ";\n"
        out["deploy.sh"] = _DEPLOY_SH
    out["README.md"] = _render_readme(spec, platforms, compiled, duality_writes)
    return out


def _render_readme(spec, platforms, compiled, duality_writes=()):
    lines = ["# Data-access layer",
             "",
             "Generated from the model's access patterns against the chosen shape.",
             "Every method binds its inputs by name; connections come from the",
             "`DB_USER` / `DB_PASSWORD` / `DB_DSN` environment variables.",
             "",
             "## Platforms",
             *(f"- **{p}** → `{_RENDER[p][0]}`" for p in platforms),
             "",
             "## Access patterns",
             "| Pattern | Shape | Binds |",
             "|---|---|---|"]
    for c in compiled:
        binds = ", ".join(f"`:{n}`" for n in _bind_names(c["binds"])) or "—"
        lines.append(f"| `{c['name']}` | {c['shape']} | {binds} |")
    lines += ["",
              "## Schema",
              "`schema.sql` is the CREATE DDL for the optimal schema. Deploy it with",
              "`./deploy.sh` (reads `DB_USER`/`DB_PASSWORD`/`DB_DSN`), or let the code do",
              "it: the Python layer's `ensure_schema(conn)` checks for the schema and",
              "deploys it if absent (returns True if it deployed)."]
    if duality_writes:
        helpers = ", ".join(f"`get_{_snake(r)}_doc` / `replace_{_snake(r)}_doc`"
                            for r, _, _ in duality_writes)
        lines += ["",
                  "## Writes and concurrency (duality)",
                  "Writes go THROUGH the duality view and ride Oracle's optimistic ETag:",
                  "read the document, modify it, write the WHOLE document back with",
                  "`_metadata` exactly as read. Oracle compares the embedded etag and",
                  "raises ORA-42699 on a stale write — map it to your API's 409/conflict.",
                  "Stripping `_metadata` does NOT error: it silently disables conflict",
                  "detection, the single most likely duality integration bug (design",
                  f"gate 16). The Python layer's {helpers} show the canonical round-trip",
                  "(a stripped `_metadata` is refused; ORA-42699 raises",
                  "`StaleDocumentError`) — port the same shape to the other platforms."]
    return "\n".join(lines) + "\n"


def write_datalayer(spec, out_dir):
    """Render the data layer and write every file into out_dir. Returns the paths."""
    import os
    files = render_all(spec)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name, content in files.items():
        path = os.path.join(out_dir, name)
        with open(path, "w") as fh:
            fh.write(content)
        written.append(path)
    return sorted(written)

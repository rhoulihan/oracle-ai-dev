import subprocess
from pathlib import Path

TPL = "assets/tooling/connection-kit/templates"
LANGS = ["python-oracledb.py", "node-oracledb.js", "jdbc-java.java", "odp-dotnet.cs",
         "godror-go.go", "sqlcl.sh", "mongosh.sh", "pymongo.py", "mongodb-node.js",
         "ords-rest.sh"]
PLACEHOLDERS = ["{{HOST}}", "{{PORT}}", "{{SERVICE}}", "{{USER}}", "{{PASSWORD}}"]


def test_all_language_templates_exist(repo_root: Path):
    missing = [t for t in LANGS if not (repo_root / TPL / t).is_file()]
    assert not missing, f"missing connection templates: {missing}"


def test_sql_driver_templates_use_service_and_port(repo_root: Path):
    for t in ("python-oracledb.py", "node-oracledb.js", "jdbc-java.java"):
        txt = (repo_root / TPL / t).read_text()
        assert "{{SERVICE}}" in txt and "{{PORT}}" in txt and "{{HOST}}" in txt


def test_mongo_templates_use_mongo_port_and_plain_auth(repo_root: Path):
    for t in ("mongosh.sh", "pymongo.py", "mongodb-node.js"):
        txt = (repo_root / TPL / t).read_text()
        assert "{{MONGO_PORT}}" in txt
        assert "authmechanism=plain" in txt.lower()
        assert "tls=true" in txt.lower()


def test_rest_template_uses_ords_url(repo_root: Path):
    assert "{{ORDS_URL}}" in (repo_root / TPL / "ords-rest.sh").read_text()


def test_access_readme_template_documents_apis(repo_root: Path):
    r = (repo_root / TPL / "README.md.tmpl").read_text().lower()
    assert "1521" in r or "{{port}}" in r
    assert "27017" in r or "{{mongo_port}}" in r
    assert "sql" in r and "mongo" in r and "rest" in r


def test_generator_passes_shellcheck(repo_root: Path):
    r = subprocess.run(["shellcheck", str(repo_root / "scripts/gen-connection-kit.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_generator_renders_kit_with_no_placeholders_left(repo_root: Path, tmp_path):
    out = tmp_path / "kit"
    env = {
        "HOST": "localhost", "PORT": "1521", "SERVICE": "FREEPDB1",
        "DB_USER": "demo", "DB_PASSWORD": "Demo_pw_12345", "MONGO_PORT": "27017",
        "ORDS_URL": "http://localhost:8080/ords",
    }
    import os
    r = subprocess.run(["bash", str(repo_root / "scripts/gen-connection-kit.sh"), str(out)],
                       capture_output=True, text=True, env={**os.environ, **env})
    assert r.returncode == 0, r.stdout + r.stderr
    # every rendered file has no leftover placeholders
    rendered = list(out.glob("*"))
    assert rendered, "generator produced no files"
    for f in rendered:
        if f.is_file():
            assert "{{" not in f.read_text(), f"unrendered placeholder in {f.name}"
    # substituted values are present
    assert "27017" in (out / "mongosh.sh").read_text()
    assert (out / "README.md").is_file()
    assert (out / "MANIFEST").is_file()

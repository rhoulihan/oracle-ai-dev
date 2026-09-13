import sys
from pathlib import Path


def _check(repo_root, root, md):
    sys.path.insert(0, str(repo_root / "tests" / "lint"))
    from link_check import check_links
    return check_links(root, md)


def test_existing_relative_link_ok(repo_root, tmp_path):
    (tmp_path / "target.md").write_text("x")
    md = tmp_path / "doc.md"
    md.write_text("See [t](target.md).")
    assert _check(repo_root, tmp_path, md) == []


def test_missing_relative_link_flagged(repo_root, tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("See [t](missing.md).")
    assert _check(repo_root, tmp_path, md)


def test_external_url_ignored(repo_root, tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("See [t](https://oracle.com).")
    assert _check(repo_root, tmp_path, md) == []

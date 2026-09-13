from pathlib import Path

REQUIRED_FILES = [
    "LICENSE.txt", "SECURITY.md", "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md", "CODEOWNERS", ".gitattributes",
]


def test_required_oss_files_exist(repo_root: Path):
    missing = [f for f in REQUIRED_FILES if not (repo_root / f).is_file()]
    assert not missing, f"missing OSS files: {missing}"


def test_license_is_upl(repo_root: Path):
    text = (repo_root / "LICENSE.txt").read_text(encoding="utf-8")
    assert "Universal Permissive License" in text
    assert "Copyright (c) 2026 Oracle and/or its affiliates." in text


def test_security_contact_uses_underscore_address(repo_root: Path):
    text = (repo_root / "SECURITY.md").read_text(encoding="utf-8")
    assert "secalert_us@oracle.com" in text
    assert "secalert@oracle.com" not in text.replace("secalert_us@oracle.com", "")


def test_gitattributes_forces_lf_on_scripts(repo_root: Path):
    text = (repo_root / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in text

import subprocess
from pathlib import Path


def test_installer_passes_shellcheck(repo_root: Path):
    r = subprocess.run(["shellcheck", str(repo_root / "scripts/install-sqlcl.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_installer_is_idempotent_and_asserts(repo_root: Path):
    sh = (repo_root / "scripts/install-sqlcl.sh").read_text()
    assert "if [ -x" in sh  # skips re-download when already installed
    assert "ASSERT:sqlcl:" in sh


def test_installer_uses_futc_download_url(repo_root: Path):
    sh = (repo_root / "scripts/install-sqlcl.sh").read_text()
    assert "download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip" in sh

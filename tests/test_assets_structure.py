import subprocess
from pathlib import Path


def test_compose_profiles_exist(repo_root: Path):
    assert (repo_root / "assets/compose/db.compose.yml").is_file()
    assert (repo_root / "assets/compose/db-ords.compose.yml").is_file()


def test_db_compose_pins_free_image_and_healthcheck(repo_root: Path):
    text = (repo_root / "assets/compose/db.compose.yml").read_text()
    assert "container-registry.oracle.com/database/free" in text
    assert "healthcheck" in text


def test_assert_helper_reports_pass_and_fail(repo_root: Path):
    lib = repo_root / "assets/verify/lib.sh"
    script = f'source "{lib}"; assert ok true; assert bad false; true'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
    assert "ASSERT:ok:PASS" in out
    assert "ASSERT:bad:FAIL" in out


def test_verify_scripts_pass_shellcheck(repo_root: Path):
    r = subprocess.run(
        ["shellcheck", str(repo_root / "assets/verify/lib.sh"),
         str(repo_root / "assets/verify/verify-setup.sh")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout

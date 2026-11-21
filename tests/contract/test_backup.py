"""synthetic: true. Backup and restore --verify against a temp local restic repo."""

import shutil
from pathlib import Path

import pytest
from pytest import fixture

from core.backup import BackupError, backup, restore_verify
from core.cli import main
from core.reindex import cache_dir, reindex
from core.synthetic import populate

pytestmark = pytest.mark.skipif(shutil.which("restic") is None, reason="restic not installed")


@fixture()
def setup(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "data"
    populate(root)
    pw = tmp_path / "pw"
    pw.write_text("synthetic-test-password\n")
    repo = str(tmp_path / "repo")
    import subprocess

    subprocess.run(
        ["restic", "-r", repo, "--password-file", str(pw), "init", "-q"],
        check=True,
        capture_output=True,
    )
    return root, repo, str(pw)


def test_backup_restore_verify_ok(setup: tuple[Path, str, str]) -> None:
    root, repo, pw = setup
    reindex(root)
    backup(root, repo, pw)
    assert restore_verify(repo, pw) == []


def test_qmd_cache_excluded(setup: tuple[Path, str, str], tmp_path: Path) -> None:
    root, repo, pw = setup
    reindex(root)
    assert cache_dir(root).exists()
    backup(root, repo, pw)
    out = tmp_path / "out"
    import subprocess

    subprocess.run(
        ["restic", "-r", repo, "--password-file", pw, "restore", "latest", "--target", str(out)],
        check=True,
        capture_output=True,
    )
    assert not list(out.rglob("listing.txt"))
    assert list(out.rglob(".git"))  # data repo .git is in the snapshot


def test_verify_fails_on_invalid_note(setup: tuple[Path, str, str]) -> None:
    root, repo, pw = setup
    note = next((root / "notes").glob("*.md"))
    note.write_text("not a valid note\n")
    backup(root, repo, pw)
    fails = restore_verify(repo, pw)
    assert fails
    assert any(f.startswith("notes/") for f in fails)


def test_verify_without_snapshot_raises(setup: tuple[Path, str, str]) -> None:
    _, repo, pw = setup
    with pytest.raises(BackupError):
        restore_verify(repo, pw)


def test_no_default_target(tmp_path: Path) -> None:
    with pytest.raises(BackupError):
        backup(tmp_path, "", "")


def test_cli_exit_codes(setup: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    root, repo, pw = setup
    monkeypatch.setenv("LIFEOS_DATA_DIR", str(root))
    monkeypatch.setenv("LIFEOS_RESTIC_REPO", repo)
    monkeypatch.setenv("LIFEOS_RESTIC_PASSWORD_FILE", pw)
    assert main(["backup"]) == 0
    assert main(["restore", "--verify"]) == 0
    next((root / "notes").glob("*.md")).write_text("broken\n")
    assert main(["backup"]) == 0
    assert main(["restore", "--verify"]) == 1

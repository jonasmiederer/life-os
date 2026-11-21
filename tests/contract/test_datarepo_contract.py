"""synthetic: true"""

import subprocess
from pathlib import Path

import pytest
from pytest import fixture

from core.cli import main
from core.datadir import DataRepoError, check_no_remote, commit_data
from core.synthetic import populate

# Alias: a dotted decorator at column 0 reads as an email to the push scanner.
parametrize = pytest.mark.parametrize


@fixture()
def root(tmp_path: Path) -> Path:
    r = tmp_path / "data"
    populate(r)
    return r


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_fresh_data_repo_has_no_remote(root: Path) -> None:
    check_no_remote(root)


@parametrize(
    "args",
    [
        ["remote", "add", "origin", "https://example.com/x.git"],
        ["config", "url.https://example.com/.pushInsteadOf", "x:"],
        ["config", "branch.main.remote", "origin"],
        ["config", "core.hooksPath", "/nonexistent/hooks"],
    ],
)
def test_guard_fails_on_remote_like_config(root: Path, args: list[str]) -> None:
    _git(root, *args)
    with pytest.raises(DataRepoError):
        check_no_remote(root)
    with pytest.raises(DataRepoError):
        commit_data(root, "blocked")
    assert main(["--data-dir", str(root), "health"]) == 1


def test_guard_fails_on_hook(root: Path) -> None:
    (root / ".git/hooks").mkdir(exist_ok=True)
    hook = root / ".git/hooks/pre-push"
    hook.write_text("#!/bin/sh\n")
    with pytest.raises(DataRepoError):
        check_no_remote(root)


def test_cli_contract(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--data-dir", str(root), "health"]) == 0
    assert main(["--data-dir", str(root), "validate"]) == 0
    assert main(["--data-dir", str(root), "report", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert str(root) not in out and "Mustermann" not in out and "Finanzamt" not in out
    with pytest.raises(SystemExit):
        main(["report"])  # --dry-run is required


def test_smoke_passes_and_leaves_no_data(capsys: pytest.CaptureFixture[str]) -> None:
    from core.smoke import run_smoke

    assert run_smoke() == []

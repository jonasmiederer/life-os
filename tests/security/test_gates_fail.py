"""Negative tests: each gate must exit non-zero on a bad sample generated at test time."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixturegen.gen import generate, generate_known_bad

pytestmark = pytest.mark.security
ROOT = Path(__file__).resolve().parents[2]


def run(script: str, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


def test_fixtures_clean_passes_on_generated(tmp_path: Path) -> None:
    generate(tmp_path)
    assert run("check_fixtures_clean.py", tmp_path).returncode == 0


def test_fixtures_clean_fails_on_known_bad(tmp_path: Path) -> None:
    generate(tmp_path)
    generate_known_bad(tmp_path)
    res = run("check_fixtures_clean.py", tmp_path)
    assert res.returncode == 1
    assert "email domain" in res.stdout and "IBAN" in res.stdout and "home path" in res.stdout


def test_canary_script_fails_on_planted_canary(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text('{"event": "x", "v": "CANARY-0123456789abcdef"}\n', encoding="utf-8")
    assert run("check_canary.py", log).returncode == 1
    log.write_text('{"event": "x"}\n', encoding="utf-8")
    assert run("check_canary.py", log).returncode == 0


def test_widened_permissions_without_lock_fails(tmp_path: Path) -> None:
    helper = tmp_path / "helpers" / "demo"
    helper.mkdir(parents=True)
    perm = helper / "permissions.yml"
    perm.write_text(
        "helper: demo\nagents:\n  - {name: a, role: reader, reads: [C3], network: none}\n",
        encoding="utf-8",
    )
    assert run("check_permissions_lock.py", "--root", tmp_path, "--update").returncode == 0
    assert run("check_permissions_lock.py", "--root", tmp_path).returncode == 0
    perm.write_text(perm.read_text(encoding="utf-8").replace("[C3]", "[C3, C4]"), encoding="utf-8")
    assert run("check_permissions_lock.py", "--root", tmp_path).returncode == 1
    # a new helper that is not in the lock also fails
    run("check_permissions_lock.py", "--root", tmp_path, "--update")
    (tmp_path / "helpers" / "new").mkdir()
    (tmp_path / "helpers" / "new" / "permissions.yml").write_text("helper: new\n", encoding="utf-8")
    assert run("check_permissions_lock.py", "--root", tmp_path).returncode == 1

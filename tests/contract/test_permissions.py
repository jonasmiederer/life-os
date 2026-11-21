"""Contract tests over the real repo: permission files match the lock and the schema."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.permissions import load_permissions
from scripts.check_permissions_lock import current

ROOT = Path(__file__).resolve().parents[2]


def test_repo_matches_permissions_lock() -> None:
    import json

    lock = json.loads((ROOT / "tests/security/permissions.lock").read_text(encoding="utf-8"))
    assert current(ROOT) == lock


def test_loader_rejects_unknown_role(tmp_path: Path) -> None:
    p = tmp_path / "permissions.yml"
    p.write_text("helper: x\nagents:\n  - {name: a, role: root}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_permissions(p)


def test_repo_permission_files_load() -> None:
    for p in sorted(ROOT.glob("helpers/*/permissions.yml")):
        load_permissions(p)

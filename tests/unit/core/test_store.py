"""synthetic: true"""

import json
from pathlib import Path

import pytest
from pytest import fixture

from core.datadir import (
    DIRS,
    check_layout,
    commit_data,
    init_data_dir,
)
from core.store import scan
from core.synthetic import populate, populate_invalid

# Alias: a dotted decorator at column 0 reads as an email to the push scanner.
parametrize = pytest.mark.parametrize


@fixture()
def root(tmp_path: Path) -> Path:
    r = tmp_path / "data"
    populate(r)
    return r


def test_init_layout_and_idempotent(tmp_path: Path) -> None:
    r = tmp_path / "d"
    init_data_dir(r)
    init_data_dir(r)
    assert check_layout(r) == []
    assert all((r / d).is_dir() for d in DIRS)
    assert json.loads((r / ".lifeos/schema.json").read_text())["schema_version"] == 1


def test_files_and_audit_not_in_git(root: Path) -> None:
    import subprocess

    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True
    ).stdout
    assert "files/" not in tracked and "audit/" not in tracked
    assert "notes/" in tracked and "raw/" in tracked


def test_valid_fixtures_pass_and_are_committed(root: Path) -> None:
    assert scan(root, move=False) == {}
    assert commit_data(root, "again") is False


def test_unknown_key_goes_to_review(root: Path) -> None:
    assert populate_invalid(root) == ["unknown_key:surprise"]
    assert (root / "review/2026-11-04-musterfirma-rechnung-deadbeef.md").exists()
    assert not (root / "notes/2026-11-04-musterfirma-rechnung-deadbeef.md").exists()


def _edit(root: Path, old: str, new: str) -> Path:
    p = next((root / "notes").glob("*steuerbescheid*.md"))
    p.write_text(p.read_text().replace(old, new))
    return p


@parametrize(
    "old,new,code",
    [
        ("type: steuerbescheid", "type: bogus", "bad_enum:type"),
        ("date: 2026-11-03", "date: not-a-date", "bad_date:date"),
        ("deadline: 2026-12-07\n", "", "confirmed_without_deadline"),
        ("raw: raw/", "raw: raw/x", "raw_path_mismatch"),
        ("amount: 412.5", "amount: abc", "bad_value:amount"),
    ],
)
def test_hand_edit_rejected(root: Path, old: str, new: str, code: str) -> None:
    if code == "confirmed_without_deadline":
        _edit(root, "status: draft", "status: confirmed")
    p = _edit(root, old, new)
    bad = scan(root)
    assert code in bad[f"notes/{p.name}"]
    assert (root / "review" / p.name).exists()
    assert not p.exists()


def test_missing_raw_and_bad_slug(root: Path) -> None:
    next((root / "raw").glob("*steuerbescheid*.md")).unlink()
    bad = scan(root, move=False)
    assert any("raw_missing" in v for v in bad.values())
    (root / "notes/oops.md").write_text("---\ntype: sonstiges\n---\n")
    assert scan(root, move=False)["notes/oops.md"][0].startswith("missing_key")


def test_no_frontmatter_and_oversize(root: Path) -> None:
    (root / "notes/a.md").write_text("hello")
    (root / "notes/b.md").write_bytes(b"x" * 1_000_001)
    bad = scan(root, move=False)
    assert bad["notes/a.md"] == ["frontmatter_missing"]
    assert bad["notes/b.md"] == ["file_too_large"]


def test_reason_file_has_codes_only(root: Path) -> None:
    populate_invalid(root)
    reason = json.loads(next((root / "review").glob("*.reason.json")).read_text())
    assert reason == {"codes": ["unknown_key:surprise"]}

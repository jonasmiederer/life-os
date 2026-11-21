from __future__ import annotations

from pathlib import Path

from scripts.check_workflows import check

ROOT = Path(__file__).resolve().parents[2]


def test_repo_workflows_are_pinned() -> None:
    for p in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        assert check(p) == []


def test_unpinned_action_is_found(tmp_path: Path) -> None:
    p = tmp_path / "w.yml"
    p.write_text("permissions: {}\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert len(check(p)) == 1

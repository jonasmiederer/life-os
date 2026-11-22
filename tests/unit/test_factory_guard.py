"""Factory guard tests. Synthetic names only."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import factory_guard as g

OWNER = "owner-x"


def ev(**over: Any) -> dict[str, Any]:
    e: dict[str, Any] = {
        "action": "labeled",
        "label": {"name": "agent:build"},
        "sender": {"login": OWNER},
        "issue": {"user": {"login": OWNER}, "labels": [{"name": "agent:build"}]},
        "repository": {"fork": False, "owner": {"login": OWNER}},
    }
    e.update(over)
    return e


def test_owner_starts() -> None:
    assert g.decide_start(ev(), OWNER) == (True, "ok")


def test_owner_compare_ignores_case() -> None:
    assert g.decide_start(ev(), "Owner-X")[0] is True


def test_non_owner_issue_does_not_start() -> None:
    e = ev(issue={"user": {"login": "someone-else"}, "labels": [{"name": "agent:build"}]})
    assert g.decide_start(e, OWNER) == (False, "issue author is not the owner")


def test_non_owner_label_actor_does_not_start() -> None:
    ok, why = g.decide_start(ev(sender={"login": "someone-else"}), OWNER)
    assert (ok, why) == (False, "label actor is not the owner")


def test_stop_label_present_in_event_blocks() -> None:
    e = ev(
        issue={
            "user": {"login": OWNER},
            "labels": [{"name": "agent:build"}, {"name": "agent:stop"}],
        }
    )
    assert g.decide_start(e, OWNER) == (False, "stop label present")


def test_stop_label_in_live_labels_blocks() -> None:
    assert g.decide_start(ev(), OWNER, ["agent:build", "agent:stop"]) == (
        False,
        "stop label present",
    )


def test_start_label_removed_meanwhile() -> None:
    assert g.decide_start(ev(), OWNER, [])[0] is False


def test_stop_label_event_does_not_start() -> None:
    assert g.decide_start(ev(label={"name": "agent:stop"}), OWNER)[0] is False


@pytest.mark.parametrize(
    "over",
    [
        {"label": {"name": "bug"}},
        {"action": "opened"},
        {"repository": {"fork": True, "owner": {"login": OWNER}}},
        {"repository": {"owner": {"login": OWNER}}},
        {"repository": {"fork": False, "owner": {"login": "other"}}},
        {"issue": {"user": {"login": OWNER}, "labels": [], "pull_request": {}}},
        {"issue": None},
        {"sender": None},
    ],
)
def test_other_cases_do_not_start(over: dict[str, Any]) -> None:
    assert g.decide_start(ev(**over), OWNER)[0] is False


def test_disabled_and_empty_owner() -> None:
    assert g.decide_start(ev(), OWNER, enabled=False)[0] is False
    assert g.decide_start(ev(), "")[0] is False


def staged(
    tmp_path: Path, files: dict[str, str | bytes], mode: str | None = None
) -> tuple[str, bytes, bytes]:
    """Stage files in a scratch repo; return (patch, raw -z, numstat -z) as the publish job does."""

    def git(*a: str) -> bytes:
        return subprocess.run(
            ["git", "-c", "core.quotepath=true", *a], cwd=tmp_path, check=True, capture_output=True
        ).stdout

    tmp_path.mkdir(parents=True, exist_ok=True)
    git("init", "-q")
    for name, data in files.items():
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data if isinstance(data, bytes) else data.encode())
        if mode:
            f.chmod(0o755)
    git("add", "-A")
    base = ["diff", "--cached", "--no-renames"]
    return (
        git(*base).decode("utf-8", "replace"),
        git(*base, "--raw", "-z"),
        git(*base, "--numstat", "-z"),
    )


def test_patch_allowed(tmp_path: Path) -> None:
    assert g.check_patch(*staged(tmp_path, {"core/a.py": "x\n", "tests/unit/t.py": "y\n"})) == []


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/x.yml",
        "AGENTS.md",
        "scripts/x.py",
        "factory/agents/actor.json",
        "core/gateway/x.py",
        "tests/security/x.py",
        "evals/baselines/x.json",
        ".github/workflows/a b.yml",
        ".github/workflows/\u00e9.yml",
    ],
)
def test_patch_denied_paths(tmp_path: Path, path: str) -> None:
    assert g.check_patch(*staged(tmp_path, {path: "x\n"})) != []


def test_path_with_space_is_checked(tmp_path: Path) -> None:
    text, raw, num = staged(tmp_path, {"core/ok file.py": "x\n"})
    assert g.check_patch(text, raw, num) == []
    text, raw, num = staged(tmp_path / "b", {".github/a b.yml": "x\n"})
    assert any("not allowed" in f for f in g.check_patch(text, raw, num))


def test_no_header_patch_fails_closed(tmp_path: Path) -> None:
    text, raw, num = staged(tmp_path, {"core/a.py": "x\n"})
    assert g.check_patch("--- a\n+++ b\n+x\n", raw, num) != []
    assert g.check_patch(text, b"", b"") == ["no paths", "diff headers (1) do not match paths (0)"]
    assert g.check_patch(text, b"junk", num) == ["unparsable diff output"]


def test_patch_binary_exec_symlink_large(tmp_path: Path) -> None:
    assert "binary change" in g.check_patch(*staged(tmp_path / "a", {"core/a.bin": b"\x00\x01"}))
    assert any(
        "mode" in f for f in g.check_patch(*staged(tmp_path / "b", {"core/a.sh": "x\n"}, mode="x"))
    )
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "core").mkdir()
    (tmp_path / "d" / "core" / "l").symlink_to("/etc/passwd")
    assert any("mode" in f for f in g.check_patch(*staged(tmp_path / "d", {})))
    assert any(
        "too large" in f for f in g.check_patch(*staged(tmp_path / "c", {"core/a.py": "x\n" * 401}))
    )


def test_cli_writes_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "e.json"
    f.write_text(json.dumps(ev(sender={"login": "x"})))
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert g.main(["start", "--event", str(f), "--owner", OWNER]) == 0
    assert "start=false" in out.read_text()

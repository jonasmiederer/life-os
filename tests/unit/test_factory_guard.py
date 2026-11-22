"""Factory guard tests. Synthetic names only."""

from __future__ import annotations

import json
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


def patch(path: str, lines: int = 1) -> str:
    body = "".join("+x\n" for _ in range(lines))
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n{body}"


def test_patch_allowed() -> None:
    assert g.check_patch(patch("core/a.py") + patch("tests/unit/test_a.py")) == []


@pytest.mark.parametrize(
    "path",
    [".github/workflows/x.yml", "AGENTS.md", "scripts/x.py", "../x", "factory/agents/actor.json"],
)
def test_patch_denied_paths(path: str) -> None:
    assert g.check_patch(patch(path)) != []


def test_patch_binary_empty_large() -> None:
    assert g.check_patch("") == ["empty patch"]
    assert "binary change" in g.check_patch(patch("core/a.py") + "GIT binary patch\n")
    assert any("too large" in f for f in g.check_patch(patch("core/a.py", 401)))


def test_cli_writes_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "e.json"
    f.write_text(json.dumps(ev(sender={"login": "x"})))
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert g.main(["start", "--event", str(f), "--owner", OWNER]) == 0
    assert "start=false" in out.read_text()

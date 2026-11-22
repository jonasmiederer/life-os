"""Factory guard: decides whether the agent may start, and whether a patch may be published.

Pure functions plus a small CLI used by .github/workflows/factory.yml. The owner is
never hard-coded: it is passed in (github.repository_owner).

  factory_guard.py start --event FILE --owner NAME [--live-labels FILE] [--enabled true|false]
    [--require]
  factory_guard.py patch --patch FILE --raw FILE --numstat FILE

`start` writes start=true|false and reason=... to $GITHUB_OUTPUT (or stdout) and exits 0,
or 1 with --require when the agent may not start.
`patch` exits 1 when the patch is not allowed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

START_LABELS = frozenset({"agent:spec", "agent:build"})
STOP_LABEL = "agent:stop"

# Patch gate. shortcut: coarse path prefixes, no per-helper check yet; add the
# `helper:*` label check when the first helper exists.
ALLOWED_PREFIXES = ("core/", "helpers/", "tests/", "docs/")
# Same list as factory/agents/actor.json fs_write deniedPaths, plus gateway code.
DENIED_PREFIXES = ("core/gateway/", "tests/security/", "evals/baselines/")
MAX_CHANGED_LINES = 400


def _same(a: object, b: object) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a != "" and a.lower() == b.lower()


def decide_start(
    event: dict[str, Any],
    owner: str,
    live_labels: Iterable[str] | None = None,
    enabled: bool = True,
) -> tuple[bool, str]:
    """Return (start, reason). Fails closed: anything unexpected means no start."""
    if not enabled:
        return False, "factory disabled"
    if not owner:
        return False, "no owner given"
    if event.get("action") != "labeled":
        return False, "not a labeled event"
    issue = event.get("issue")
    if not isinstance(issue, dict):
        return False, "no issue in event"
    if "pull_request" in issue:
        return False, "target is a pull request, not an issue"
    repo = event.get("repository")
    if not isinstance(repo, dict) or repo.get("fork") is not False:
        return False, "repository is a fork or unknown"
    if not _same((repo.get("owner") or {}).get("login"), owner):
        return False, "repository owner differs from the expected owner"
    label = (event.get("label") or {}).get("name")
    if label == STOP_LABEL:
        return False, "stop label applied"
    if label not in START_LABELS:
        return False, "not a start label"
    if not _same((issue.get("user") or {}).get("login"), owner):
        return False, "issue author is not the owner"
    if not _same((event.get("sender") or {}).get("login"), owner):
        return False, "label actor is not the owner"
    names = (
        list(live_labels)
        if live_labels is not None
        else [x.get("name") for x in issue.get("labels", []) if isinstance(x, dict)]
    )
    if STOP_LABEL in names:
        return False, "stop label present"
    if label not in names:
        return False, "start label no longer present"
    return True, "ok"


def _path_findings(path: str) -> list[str]:
    if path.startswith("/") or ".." in path.split("/"):
        return [f"path not allowed: {path!r}"]
    if not path.startswith(ALLOWED_PREFIXES) or path.startswith(DENIED_PREFIXES):
        return [f"path not allowed: {path!r}"]
    return []


def check_patch(
    patch_text: str, raw: bytes, numstat: bytes, max_lines: int = MAX_CHANGED_LINES
) -> list[str]:
    """Return findings; empty list means the patch may be published.

    `raw` is `git diff --cached --no-renames --raw -z` and `numstat` is
    `git diff --cached --no-renames --numstat -z`, both taken after `git apply --index`.
    Paths come only from these NUL-separated outputs, never from parsing diff headers.
    The count of `diff --git` lines must equal the number of paths, so a header git
    reports differently (or an empty result) fails closed.
    """
    out: list[str] = []
    toks = raw.decode("utf-8", "surrogateescape").split("\0")
    if toks and toks[-1] == "":
        toks.pop()
    n = 0
    i = 0
    while i < len(toks):
        meta = toks[i].split()
        if len(toks[i]) == 0 or toks[i][0] != ":" or len(meta) != 5 or i + 1 >= len(toks):
            return out + ["unparsable diff output"]
        old_mode, new_mode, status, path = meta[0][1:], meta[1], meta[4], toks[i + 1]
        n += 1
        i += 2
        if status not in ("A", "M", "D"):
            out.append(f"status not allowed: {status} {path!r}")
        if new_mode not in ("100644", "000000") or old_mode not in ("100644", "000000"):
            out.append(f"mode not allowed: {old_mode} {new_mode} {path!r}")
        out += _path_findings(path)
    if n == 0:
        out.append("no paths")
    headers = sum(1 for ln in patch_text.splitlines() if ln.startswith("diff --git "))
    if headers != n:
        out.append(f"diff headers ({headers}) do not match paths ({n})")
    changed = 0
    for rec in numstat.decode("utf-8", "surrogateescape").split("\0"):
        if not rec:
            continue
        add, _, rest = rec.partition("\t")
        dele, _, _path = rest.partition("\t")
        if add == "-" or dele == "-":
            out.append("binary change")
        else:
            changed += int(add) + int(dele)
    if changed > max_lines:
        out.append(f"too large: {changed} changed lines (max {max_lines})")
    return out


def _emit(pairs: dict[str, str]) -> None:
    dest = os.environ.get("GITHUB_OUTPUT")
    text = "".join(f"{k}={v}\n" for k, v in pairs.items())
    if dest:
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text, end="")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--event", required=True)
    s.add_argument("--owner", required=True)
    s.add_argument("--live-labels")
    s.add_argument("--enabled", default="true")
    s.add_argument("--require", action="store_true", help="exit 1 when the agent may not start")
    p = sub.add_parser("patch")
    p.add_argument("--patch", required=True)
    p.add_argument("--raw", required=True)
    p.add_argument("--numstat", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "start":
        event = json.loads(Path(a.event).read_text(encoding="utf-8"))
        live = None
        if a.live_labels:
            live = json.loads(Path(a.live_labels).read_text(encoding="utf-8"))
        ok, why = decide_start(event, a.owner, live, a.enabled.lower() == "true")
        _emit({"start": "true" if ok else "false", "reason": why})
        return 1 if a.require and not ok else 0
    found = check_patch(
        Path(a.patch).read_text(encoding="utf-8", errors="replace"),
        Path(a.raw).read_bytes(),
        Path(a.numstat).read_bytes(),
    )
    for f in found:
        print(f"PATCH {f}")
    print(f"patch-gate: {len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

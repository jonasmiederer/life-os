"""Inbox writer and state file. Contract: docs/contracts/inbox-v1.md.

Order: `<id>.eml.tmp` -> fsync -> rename `<id>.eml` -> `<id>.json` last (commit marker).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

MODE = 0o600
SIDECAR_VERSION = 1


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)  # removes a stale file or a planted symlink, never its target
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, MODE)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.chmod(tmp, MODE)
    os.rename(tmp, path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def write_pair(inbox: Path, mail_id: str, raw: bytes, sidecar: dict[str, Any]) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    _write_atomic(inbox / f"{mail_id}.eml", raw)
    body = json.dumps(sidecar, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_atomic(inbox / f"{mail_id}.json", body)


def _valid(d: Any) -> bool:
    """Type check of a loaded state file. Anything odd means: ignore the file."""
    if not isinstance(d, dict):
        return False
    strs = ("accept_day", "cap_alert_day", "login_alert_day", "next_try")
    seen, counts = d.get("seen", []), d.get("reject_counts", {})
    ok = isinstance(seen, list) and all(isinstance(x, str) for x in seen)
    ok = ok and isinstance(counts, dict)
    ok = ok and all(isinstance(k, str) and type(v) is int for k, v in counts.items())
    ok = ok and all(type(d.get(k, 0)) is int for k in ("accepted", "login_failures"))
    ok = ok and all(isinstance(d.get(k, ""), str) for k in strs)
    if ok and d.get("next_try"):
        try:
            if datetime.fromisoformat(d["next_try"]).tzinfo is None:
                return False
        except ValueError:
            return False
    return ok


class State:
    """Small JSON file `inbox/.state`. Dedupe hashes, daily counters, backoff, alert days."""

    def __init__(self, inbox: Path) -> None:
        self.path = inbox / ".state"
        self.data: dict[str, Any] = {
            "seen": [],
            "accept_day": "",
            "accepted": 0,
            "reject_counts": {},
            "cap_alert_day": "",
            "login_alert_day": "",
            "login_failures": 0,
            "next_try": "",
        }
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None  # first run, or damaged: start empty (worst case: a duplicate M2 dedupes)
        if _valid(loaded):
            self.data.update(loaded)
        self._seen = set(self.data["seen"])

    def seen(self, mail_id: str) -> bool:
        return mail_id in self._seen

    def add_seen(self, mail_id: str) -> None:
        if mail_id not in self._seen:
            self._seen.add(mail_id)
            self.data["seen"].append(mail_id)  # shortcut: grows forever, ~65 bytes per mail

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.path, json.dumps(self.data, sort_keys=True).encode("utf-8"))

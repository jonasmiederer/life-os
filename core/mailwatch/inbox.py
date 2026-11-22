"""Inbox writer and state file. Contract: docs/contracts/inbox-v1.md.

Order: `<id>.eml.tmp` -> fsync -> rename `<id>.eml` -> `<id>.json` last (commit marker).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MODE = 0o600
SIDECAR_VERSION = 1


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, MODE)
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
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass  # first run, or damaged: start empty. Worst case is a duplicate that M2 dedupes.
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

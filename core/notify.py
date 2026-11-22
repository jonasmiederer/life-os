"""Deadline reminders and the ntfy sender (design 2.9).

No job table. A reminder is due when its lead date has come, the note is confirmed and the
audit log has no `reminder.sent` line for that note and lead. A push counts as sent only
after ntfy answers 2xx. Push text is generic, details stay in the web UI.

shortcut: fixed lead times, one push per note and run, 09:00 UTC send time, no escalation,
quiet hours or "verspätet" text, and no "Kündigung margin date" yet. Phase 1c adds them.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from core.log import audit, log_event
from core.schema import ValidationError, read_note

LEADS: dict[str, tuple[int, ...]] = {
    "einspruch": (14, 7, 3, 1, 0),
    "zahlung": (7, 3, 1, 0),
    "kuendigung": (90, 30, 14, 7),
    "other": (7, 1),
}
SEND_HOUR = 9
PUSH_TEXT = "1 Frist wartet"
_TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

Sender = Callable[[str], None]


class NotifyError(RuntimeError):
    """ntfy did not confirm the push. The message never contains the push text."""


def ntfy_sender(base_url: str, topic: str, timeout: float = 5.0) -> Sender:
    if not base_url.startswith(("http://", "https://")) or not _TOPIC.match(topic):
        raise ValueError("bad ntfy url or topic")
    url = f"{base_url.rstrip('/')}/{topic}"

    def send(text: str) -> None:
        req = urllib.request.Request(  # noqa: S310 - scheme checked above
            url, data=text.encode("utf-8"), method="POST", headers={"Title": "life-os"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                if not 200 <= resp.status < 300:
                    raise NotifyError(f"ntfy answered {resp.status}")
        except (urllib.error.URLError, OSError) as exc:
            raise NotifyError(f"ntfy unreachable: {type(exc).__name__}") from None

    return send


def _sent(root: Path) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for path in (root / "audit").glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("event") == "reminder.sent":
                out.add((str(rec.get("slug")), int(rec.get("count", -1))))
    return out


def _fire_time(deadline: date, lead: int) -> datetime:
    return datetime.combine(deadline - timedelta(days=lead), time(SEND_HOUR), tzinfo=UTC)


def due_reminders(root: Path, now: datetime) -> dict[str, tuple[str, list[int]]]:
    """slug -> (deadline kind, unsent lead days whose time has come). Confirmed notes only."""
    sent = _sent(root)
    out: dict[str, tuple[str, list[int]]] = {}
    for path in sorted((root / "notes").glob("*.md")):
        try:
            meta, _ = read_note(path)
        except ValidationError:
            continue
        deadline, kind = meta.get("deadline"), meta.get("deadline_kind")
        if meta.get("status") != "confirmed" or not isinstance(deadline, date):
            continue
        snooze = meta.get("snooze")
        if isinstance(snooze, date) and snooze > now.date():
            continue
        if now.date() > deadline:  # missed: shown in the UI, never pushed
            continue
        due = [
            lead
            for lead in LEADS.get(str(kind), ())
            if _fire_time(deadline, lead) <= now and (path.stem, lead) not in sent
        ]
        if due:
            out[path.stem] = (str(kind), due)
    return out


def run_due(root: Path, clock: Any, send: Sender) -> int:
    """Send one push per note with due reminders. Returns the number of pushes."""
    now = clock.now()
    pushes = 0
    for slug, (kind, leads) in due_reminders(root, now).items():
        try:
            send(PUSH_TEXT)
        except NotifyError as exc:
            log_event("notify.failed", code=type(exc).__name__)
            continue
        pushes += 1
        for lead in leads:
            audit(root, "reminder.sent", now, slug=slug, kind=kind, count=lead, code="ok")
    return pushes

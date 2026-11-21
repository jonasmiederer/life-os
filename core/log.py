"""Log API. Only ids, hashes, counts and codes can be logged, never free text.

Free text from letters or mails must not reach logs. The API allows only known
field names and short values from a safe character set. A violation raises, so a
leak fails a test instead of reaching a log file.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

ALLOWED_FIELDS = frozenset(
    {
        "id", "doc_id", "slug", "sha256", "count", "chars", "pages", "status", "code",
        "kind", "helper", "agent", "schema_version", "ok",
    }
)  # fmt: skip
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:-]{0,64}$")
_EVENT = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


class LogError(ValueError):
    pass


def _check(event: str, fields: dict[str, Any]) -> dict[str, Any]:
    if not _EVENT.match(event):
        raise LogError("bad event name")
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in ALLOWED_FIELDS:
            raise LogError(f"field not allowed: {key}")
        if isinstance(value, bool | int):
            out[key] = value
        elif isinstance(value, str) and _SAFE_VALUE.match(value):
            out[key] = value
        else:
            raise LogError(f"value not allowed for field: {key}")
    return out


def _line(event: str, fields: dict[str, Any], ts: datetime) -> str:
    record = {"ts": ts.isoformat(timespec="seconds"), "event": event}
    record.update(_check(event, fields))
    return json.dumps(record, sort_keys=True)


class LogSink:
    """Checked JSON-lines log. Keeps lines in memory; also writes to `stream` if given."""

    def __init__(self, stream: IO[str] | None = None) -> None:
        self.lines: list[str] = []
        self._stream = stream

    def info(self, event: str, **fields: Any) -> None:
        line = _line(event, fields, datetime.now(UTC))
        self.lines.append(line)
        if self._stream is not None:
            print(line, file=self._stream)

    def text(self) -> str:
        return "\n".join(self.lines)


def log_event(event: str, *, stream: IO[str] | None = None, **fields: Any) -> None:
    print(_line(event, fields, datetime.now(UTC)), file=stream or sys.stderr)


def audit(data_dir: Path, event: str, now: datetime, **fields: Any) -> None:
    """Append one line to audit/YYYY-MM.jsonl. Same field rules as log_event."""
    line = _line(event, fields, now)
    path = data_dir / "audit" / f"{now:%Y-%m}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

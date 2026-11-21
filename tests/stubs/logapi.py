"""Stub log API (review-p0 29). Same call shape as the planned core log API: ids only."""

from __future__ import annotations

import json
from typing import Any


class LogSink:
    """Collects JSON log lines in memory."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, event: str, **fields: Any) -> None:
        self.lines.append(json.dumps({"event": event, **fields}, sort_keys=True))

    def text(self) -> str:
        return "\n".join(self.lines)

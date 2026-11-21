"""Audit JSONL: one line per cloud call. Ids, labels and numbers only, never content."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class AuditError(ValueError):
    pass


def _safe(name: str, value: str) -> str:
    if not _SAFE.match(value):
        raise AuditError(f"unsafe value for {name}")
    return value


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = path

    def write(
        self,
        *,
        doc_id: str,
        privacy_class: str,
        purpose: str,
        backend: str,
        model: str,
        duration_ms: int,
        outcome: str,
    ) -> None:
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "doc_id": _safe("doc_id", doc_id),
            "class": _safe("class", privacy_class),
            "purpose": _safe("purpose", purpose),
            "backend": _safe("backend", backend),
            "model": _safe("model", model),
            "duration_ms": int(duration_ms),
            "outcome": _safe("outcome", outcome),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")

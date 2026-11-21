"""Note writer and scanner. Only core writes notes: lock, temp file, validate, rename."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from core.clock import SystemClock
from core.datadir import commit_data
from core.log import audit
from core.schema import validate_note, validate_raw


@contextmanager
def data_lock(root: Path) -> Iterator[None]:
    with (root / ".lifeos" / "lock").open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def render(meta: dict[str, Any], body: str) -> str:
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{front}---\n{body}"


def quarantine(root: Path, path: Path, codes: list[str], clock: Any = None) -> None:
    """Move a rejected file to review/ with <name>.reason.json. Reminders and qmd ignore review/."""
    clock = clock or SystemClock()
    review = root / "review"
    review.mkdir(exist_ok=True)
    name = path.name.removesuffix(".tmp")
    dest = review / name
    shutil.move(str(path), dest)
    (review / (name + ".reason.json")).write_text(
        json.dumps({"codes": codes}, sort_keys=True) + "\n"
    )
    audit(
        root,
        "review.rejected",
        clock.now(),
        code=(codes[0] if codes else "unknown").replace(":", "."),
        count=len(codes),
    )


def _atomic_write(path: Path, text: str) -> Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    return tmp


def write_note(
    root: Path,
    slug: str,
    note_meta: dict[str, Any],
    note_body: str,
    raw_meta: dict[str, Any],
    raw_body: str,
    clock: Any = None,
) -> list[str]:
    """Write raw then note. Returns reason codes. A non-empty list means it went to review/."""
    clock = clock or SystemClock()
    with data_lock(root):
        raw_path = root / "raw" / f"{slug}.md"
        raw_tmp = _atomic_write(raw_path, render(raw_meta, raw_body))
        codes = validate_raw(raw_tmp)
        if codes:
            quarantine(root, raw_tmp, codes, clock)
            return codes
        os.replace(raw_tmp, raw_path)
        note_path = root / "notes" / f"{slug}.md"
        note_tmp = _atomic_write(note_path, render(note_meta, note_body))
        codes = validate_note(note_tmp, root, stem=slug)
        if codes:
            quarantine(root, note_tmp, codes, clock)
            return codes
        os.replace(note_tmp, note_path)
        audit(root, "note.written", clock.now(), slug=slug)
        commit_data(root, f"note {slug}")
        return []


def scan(root: Path, move: bool = True, clock: Any = None) -> dict[str, list[str]]:
    """Validate every note and raw file. Invalid ones go to review/ when move is true."""
    bad: dict[str, list[str]] = {}
    with data_lock(root):
        for sub, check in (("notes", lambda p: validate_note(p, root)), ("raw", validate_raw)):
            for path in sorted((root / sub).glob("*.md")):
                codes = check(path)
                if codes:
                    bad[f"{sub}/{path.name}"] = codes
                    if move:
                        quarantine(root, path, codes, clock)
        if bad and move:
            commit_data(root, f"quarantine {len(bad)}")
    return bad

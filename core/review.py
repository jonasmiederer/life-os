"""Owner review of a draft note: read it, edit the fields, confirm.

Confirm writes status `confirmed` plus the owner's values into the note frontmatter and makes
one data-repo commit. Only a confirmed deadline drives reminders (design 2.8).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.clock import SystemClock
from core.datadir import commit_data
from core.extract.draft import DraftFields
from core.extract.schema import DOC_TYPES
from core.ingest import note_body
from core.log import audit
from core.schema import FROM_RE, SLUG_RE, ValidationError, read_note, validate_note
from core.store import data_lock, render


class ReviewError(ValueError):
    """The owner's input or the note state is not acceptable. Message is safe to show."""


@dataclass(frozen=True)
class Draft:
    slug: str
    meta: dict[str, Any]
    file: str  # files/<sha>.<ext>
    text: str = ""  # raw body, shown for mail drafts


def _parse_date(text: str, label: str) -> date | None:
    if not text.strip():
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ReviewError(f"{label}: Datum als JJJJ-MM-TT eingeben.") from None


def list_drafts(root: Path) -> list[str]:
    out = []
    for path in sorted((root / "notes").glob("*.md")):
        try:
            if read_note(path)[0].get("status") == "draft":
                out.append(path.stem)
        except ValidationError:
            continue
    return out


def load_draft(root: Path, slug: str) -> Draft:
    if not SLUG_RE.match(slug):
        raise ReviewError("Nicht gefunden.")
    path = root / "notes" / f"{slug}.md"
    try:
        meta, _ = read_note(path)
        raw_meta, raw_body = read_note(root / "raw" / f"{slug}.md")
    except (OSError, ValidationError):
        raise ReviewError("Nicht gefunden.") from None
    return Draft(slug, meta, str(raw_meta.get("file", "")), raw_body)


def confirm(
    root: Path,
    slug: str,
    *,
    doc_type: str,
    sender: str,
    doc_date: str,
    amount: str,
    deadline: str,
    clock: Any = None,
) -> None:
    """Validate the owner's values, write them, set status confirmed, commit once."""
    clock = clock or SystemClock()
    if doc_type not in DOC_TYPES:
        raise ReviewError("Dokumenttyp ungültig.")
    sender = " ".join(sender.split())
    if not FROM_RE.match(sender):
        raise ReviewError("Absender fehlt oder enthält ungültige Zeichen.")
    day = _parse_date(doc_date, "Datum")
    if day is None:
        raise ReviewError("Datum fehlt.")
    due = _parse_date(deadline, "Frist")
    amount = amount.strip().replace(",", ".")
    if amount:
        try:
            if not Decimal(amount).is_finite() or len(amount) > 20:
                raise InvalidOperation
        except InvalidOperation:
            raise ReviewError("Betrag ungültig.") from None
    fields = DraftFields(doc_type=doc_type, sender=sender, doc_date=day, amount=amount or None,
                         deadline=due)  # fmt: skip
    with data_lock(root):
        path = root / "notes" / f"{slug}.md"
        if not SLUG_RE.match(slug) or not path.is_file():
            raise ReviewError("Nicht gefunden.")
        meta, _ = read_note(path)
        if meta.get("status") != "draft":
            raise ReviewError("Schon bestätigt.")
        meta.update(type=doc_type, status="confirmed", date=day, deadline_kind=fields.deadline_kind)
        meta["from"] = sender
        for key, value in (("amount", fields.amount), ("deadline", due)):
            if value:
                meta[key] = value
            else:
                meta.pop(key, None)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(render(meta, note_body(fields, "Bestätigt.")), encoding="utf-8")
        codes = validate_note(tmp, root, stem=slug)
        if codes:
            tmp.unlink()
            raise ReviewError("Notiz ungültig: " + ", ".join(codes[:3]))
        os.replace(tmp, path)
        audit(root, "note.confirmed", clock.now(), slug=slug, kind=fields.deadline_kind)
        commit_data(root, f"confirm {slug}")

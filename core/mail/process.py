"""Process inbox/<id>.eml + inbox/<id>.json pairs into draft notes (design 2.14, D21).

The watcher writes the .json last, so only ids with a .json are processed. Every draft gets
class `local`: no gateway call happens before the owner confirms a class on the review page.
Done pairs move to inbox/done/, refused ones to inbox/rejected/ with the reason in the audit log.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from core.clock import SystemClock
from core.extract.draft import DraftFields
from core.gateway.interface import Backend, PrivacyClass
from core.ingest import (
    MailOrigin,
    OcrFn,
    UnsupportedFile,
    ingest_text,
    ingest_upload,
    save_original,
)
from core.log import LogError, audit
from core.mail.parse import MAX_MAIL_BYTES, MailRejected, ParsedMail, parse_mail
from core.ocr import OcrError, TesseractMissing, ocr_file

MAX_PER_RUN = 5  # OCR is slow and runs inside the scheduler tick
TIME_BUDGET_SECONDS = 300
BODY_NOTE_MIN_CHARS = 200
MIN_IMAGE_BYTES = 10_000  # smaller images are signature logos
MAX_SIDECAR_BYTES = 64 * 1024
_ID_JSON = re.compile(r"^([0-9a-f]{64})\.json$")
_TAG_TYPE = {"tax": "steuerbescheid", "contract": "kuendigung_vertrag"}  # hints, owner reviews


@dataclass
class Summary:
    done: int = 0
    rejected: int = 0
    notes: int = 0
    duplicates: int = 0
    backend_calls: int = 0
    waiting: bool = False  # left in inbox/ because OCR is not installed


def _read_regular(path: Path, limit: int) -> bytes:
    """Read a regular file (no symlink) of at most `limit` bytes."""
    st = path.lstat()
    if not path.is_file() or path.is_symlink() or st.st_size > limit:
        raise MailRejected("bad_file")
    return path.read_bytes()


def _sidecar(inbox: Path, mail_id: str, eml: bytes) -> dict[str, Any]:
    try:
        side = json.loads(_read_regular(inbox / f"{mail_id}.json", MAX_SIDECAR_BYTES))
    except (ValueError, OSError):
        raise MailRejected("bad_sidecar") from None
    if not isinstance(side, dict) or side.get("v") != 1:
        raise MailRejected("bad_sidecar")
    if side.get("id") != mail_id or side.get("sha256") != mail_id or side.get("size") != len(eml):
        raise MailRejected("bad_sidecar")
    if side.get("plus_tag") not in (None, "tax", "contract", "local"):
        raise MailRejected("bad_sidecar")
    if hashlib.sha256(eml).hexdigest() != mail_id:
        raise MailRejected("hash_mismatch")
    return side


def _received(side: dict[str, Any], fallback: date) -> date:
    try:
        stamp = datetime.fromisoformat(str(side["received_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return fallback
    return stamp.astimezone(UTC).date() if stamp.tzinfo else stamp.date()


def _move(inbox: Path, mail_id: str, sub: str) -> None:
    dest = inbox / sub
    dest.mkdir(exist_ok=True)
    for name in (f"{mail_id}.eml", f"{mail_id}.json"):  # .json last: it is the marker
        src = inbox / name
        if src.exists() or src.is_symlink():
            os.replace(src, dest / name)


def _origin(mail: ParsedMail, mail_sha: str, tag: str | None, today: date) -> MailOrigin:
    # A plus-tag is a type hint only. It never changes the class (always local).
    doc_type = _TAG_TYPE.get(tag or "", "sonstiges")
    fields = DraftFields(doc_type=doc_type, sender=mail.sender, doc_date=mail.date or today)
    return MailOrigin(mail_sha, mail.forward, fields, tuple(mail.notes))


def _usable(blobs: list[bytes]) -> tuple[list[bytes], int]:
    """Drop tiny images (signature logos). PDFs are always kept."""
    keep = [b for b in blobs if b.startswith(b"%PDF-") or len(b) >= MIN_IMAGE_BYTES]
    return keep, len(blobs) - len(keep)


def _one(
    root: Path, mail_id: str, eml: bytes, side: dict[str, Any], backend: Backend | None,
    ocr: OcrFn, clock: Any, summary: Summary,
) -> int:  # fmt: skip
    """Write the notes of one mail. Returns how many new notes it made."""
    today = clock.now().date()
    mail = parse_mail(eml, _received(side, today))
    blobs, logos = _usable(mail.attachments)
    skipped = mail.dropped + logos
    body = len(mail.text.strip()) > BODY_NOTE_MIN_CHARS or not blobs
    origin = _origin(mail, mail_id, side.get("plus_tag"), _received(side, today))
    rule = ["Regel: pro Anhang eine Notiz; der Mail-Text ist eine eigene Notiz ab 200 Zeichen."]
    if skipped:
        rule.append(f"{skipped} Anhänge nicht verarbeitet (Typ, Größe oder Logo).")
    results = []
    failed = 0
    if skipped:
        audit(root, "mail.attachment_skipped", clock.now(), id=mail_id, count=skipped)
    with_lines = replace(origin, lines=origin.lines + tuple(rule))
    for blob in blobs:
        try:
            results.append(
                ingest_upload(root, blob, PrivacyClass.LOCAL, backend=backend, ocr=ocr,
                              clock=clock, mail=with_lines)
            )  # fmt: skip
        except TesseractMissing:
            raise
        except (UnsupportedFile, OcrError):
            failed += 1
    if failed:
        audit(root, "mail.attachment_skipped", clock.now(), id=mail_id, count=failed)
    if blobs and not results and not body:
        raise MailRejected("attachments_unreadable")
    if results:
        save_original(root, eml, "eml")  # only after the first note succeeded
    if body and mail.text.strip():
        lines = origin.lines + tuple(rule)
        if failed:
            lines += (f"{failed} weitere Anhänge nicht lesbar.",)
        results.append(
            ingest_text(root, mail.text, eml, "eml", PrivacyClass.LOCAL, backend=backend,
                        clock=clock, mail=replace(origin, lines=lines))
        )  # fmt: skip
    if not results:
        raise MailRejected("empty")
    new = 0
    for res in results:
        summary.duplicates += res.duplicate
        summary.notes += not res.duplicate
        summary.backend_calls += res.backend_calls
        new += not res.duplicate
    return new


def process_inbox(
    root: Path,
    *,
    backend: Backend | None = None,
    ocr: OcrFn = ocr_file,
    clock: Any = None,
) -> Summary:
    """Process up to MAX_PER_RUN ready mails. Safe to run again: duplicates make no new note."""
    clock = clock or SystemClock()
    inbox = root / "inbox"
    summary = Summary()
    ids = sorted(m[1] for p in inbox.glob("*.json") if (m := _ID_JSON.match(p.name)))
    started = time.monotonic()
    for mail_id in ids[:MAX_PER_RUN]:
        if time.monotonic() - started > TIME_BUDGET_SECONDS:
            break
        eml_path = inbox / f"{mail_id}.eml"
        try:
            if not eml_path.exists() and (inbox / "done" / f"{mail_id}.eml").exists():
                _move(inbox, mail_id, "done")  # an earlier run stopped between the two moves
                summary.done += 1
                continue
            eml = _read_regular(eml_path, MAX_MAIL_BYTES)
            side = _sidecar(inbox, mail_id, eml)
            count = _one(root, mail_id, eml, side, backend, ocr, clock, summary)
        except TesseractMissing:
            summary.waiting = True  # leave in inbox/ and go on: text-only mails need no OCR
            continue
        except (MailRejected, UnsupportedFile, OSError, LogError) as exc:
            if isinstance(exc, MailRejected):
                code = exc.args[0]
            else:
                code = "log" if isinstance(exc, LogError) else type(exc).__name__.lower()
            audit(root, "mail.rejected", clock.now(), id=mail_id, code=str(code)[:40])
            _move(inbox, mail_id, "rejected")
            summary.rejected += 1
            continue
        _move(inbox, mail_id, "done")
        summary.done += 1
        audit(root, "mail.done", clock.now(), id=mail_id, count=count)
    return summary

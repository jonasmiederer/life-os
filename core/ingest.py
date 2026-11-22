"""Ingest one uploaded document: files/ -> OCR -> raw/ -> draft note in notes/ -> one commit.

Extraction goes through the gateway router (one audit line per backend call) and only when
the confirmed class is `allow` and the text has no health or ID keyword. Classes `local`
and `block` (and the "nur lokal" box) make zero backend calls.
The caller (web form, later folder or mail) must pass a class the owner confirmed (D21).
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.clock import SystemClock
from core.extract.draft import DraftFields, from_extraction
from core.gateway.audit import AuditLog
from core.gateway.interface import Backend, GatewayError, GatewayRequest, PrivacyClass
from core.gateway.router import Gateway, intake_class
from core.images import BadImage, clean_image, is_heic
from core.log import audit
from core.ocr import OcrResult, PageText, ocr_file
from core.store import data_lock, write_note

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"%PDF-", "pdf"))

OcrFn = Callable[[Path], OcrResult]


class UnsupportedFile(ValueError):
    """Upload is not a PNG, JPEG, HEIC or PDF, or is empty, too large or unreadable."""


@dataclass(frozen=True)
class IngestResult:
    slug: str
    sha256: str
    ext: str
    duplicate: bool = False
    quarantined: tuple[str, ...] = ()
    backend_calls: int = 0


def detect_ext(data: bytes) -> str:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise UnsupportedFile("empty or too large")
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if is_heic(data):
        return "heic"
    raise UnsupportedFile("not png, jpeg, heic or pdf")


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text.lower().replace("ß", "ss"))
    ascii_text = ascii_text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:60].strip("-") or "unbekannt"


def _save_file(root: Path, sha: str, ext: str, data: bytes) -> Path:
    dest = root / "files" / f"{sha}.{ext}"
    if not dest.exists():
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    return dest


def note_body(fields: DraftFields, header: str) -> str:
    lines = [header, "", f"Absender: {fields.sender}"]
    if fields.amount:
        lines.append(f"Betrag: {fields.amount} {fields.currency or ''}".rstrip())
    if fields.deadline:
        lines.append(f"Frist: {fields.deadline.isoformat()}")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class MailOrigin:
    """What a mail adds to a draft: prefilled fields and the shared mail (never mail headers)."""

    sha256: str
    forward: str  # attached | inline
    prefill: DraftFields = DraftFields()
    lines: tuple[str, ...] = ()


def save_original(root: Path, data: bytes, ext: str) -> str:
    """Store original bytes under files/<sha>.<ext> (idempotent). Returns the sha256."""
    sha = hashlib.sha256(data).hexdigest()
    with data_lock(root):
        _save_file(root, sha, ext, data)
    return sha


def ingest_upload(
    root: Path,
    data: bytes,
    privacy_class: PrivacyClass,
    *,
    backend: Backend | None = None,
    ocr: OcrFn = ocr_file,
    clock: Any = None,
    mail: MailOrigin | None = None,
) -> IngestResult:
    """Store one file and write a draft note. Raises UnsupportedFile, OcrError."""
    ext = detect_ext(data)
    if ext != "pdf":
        try:
            data, ext = clean_image(data, ext)
        except BadImage:
            raise UnsupportedFile("unreadable image") from None
    return _ingest(root, data, ext, privacy_class, backend, ocr, clock, mail)


def ingest_text(
    root: Path,
    text: str,
    original: bytes,
    ext: str,
    privacy_class: PrivacyClass,
    *,
    backend: Backend | None = None,
    clock: Any = None,
    mail: MailOrigin | None = None,
) -> IngestResult:
    """Draft note from already extracted text. `original` (for mail: the .eml) goes to files/."""
    if not original or len(original) > MAX_UPLOAD_BYTES:
        raise UnsupportedFile("empty or too large")
    result = OcrResult([PageText(1, text)], extractor="text", model_id="text")
    return _ingest(root, original, ext, privacy_class, backend, lambda _p: result, clock, mail)


def _ingest(
    root: Path,
    data: bytes,
    ext: str,
    privacy_class: PrivacyClass,
    backend: Backend | None,
    ocr: OcrFn,
    clock: Any,
    mail: MailOrigin | None,
) -> IngestResult:
    """Shared tail: save file, text, optional extraction, raw + note write, one commit."""
    if privacy_class is PrivacyClass.REDACTED:
        raise ValueError("class redacted is not implemented in Phase 1a")
    clock = clock or SystemClock()
    sha = hashlib.sha256(data).hexdigest()
    with data_lock(root):
        if any((root / "raw").glob(f"*-{sha[:8]}.md")):
            return IngestResult("", sha, ext, duplicate=True)
        path = _save_file(root, sha, ext, data)
    result = ocr(path)

    calls = 0
    extracted: dict[str, object] | None = None
    code = "skipped"
    if privacy_class is PrivacyClass.ALLOW and backend is not None and result.text.strip():
        # Health or ID keywords downgrade allow to block before any call (design 2.13).
        klass = intake_class(result.text, local_only=False, default=privacy_class)
        if klass is PrivacyClass.ALLOW:
            calls = 1
            code = "failed"
            gateway = Gateway(backend, AuditLog(root / "audit" / "gateway.jsonl"))
            try:
                extracted = gateway.run(
                    GatewayRequest(f"doc-{sha[:8]}", klass, "extract", result.text)
                ).data
                code = "ok"
            except GatewayError:
                extracted = None
    fields = from_extraction(extracted) if extracted is not None else None
    fields = fields or (mail.prefill if mail else DraftFields())

    received = clock.now().date()
    doc_date = fields.doc_date or received
    # sender part <= 25 chars keeps the slug <= 64 chars (log field limit)
    who = slugify(fields.sender)[:25].strip("-") or "unbekannt"
    slug = f"{doc_date.isoformat()}-{who}-{fields.doc_type}-{sha[:8]}"
    note_meta: dict[str, Any] = {
        "type": fields.doc_type,
        "from": fields.sender,
        "date": doc_date,
        "status": "draft",
        "source": "mail" if mail else "upload",
        "raw": f"raw/{slug}.md",
    }
    if mail:
        note_meta["forward"] = mail.forward
        note_meta["class"] = "local"  # mail drafts stay local until a later confirm step exists
    if fields.deadline:
        note_meta["deadline"] = fields.deadline
        note_meta["deadline_kind"] = fields.deadline_kind
    if fields.amount:
        note_meta["amount"] = fields.amount
    raw_meta: dict[str, Any] = {
        "file": f"files/{sha}.{ext}",
        "sha256": sha,
        "pages": len(result.pages),
        "extractor": result.extractor,
        "model_id": result.model_id,
    }
    if mail:
        raw_meta["mail_sha256"] = mail.sha256
        raw_meta["class"] = "local"
    raw_body = "".join(f"\n## Seite {p.number}\n\n{p.text}\n" for p in result.pages)
    body = note_body(fields, "Entwurf, bitte prüfen.")
    if mail:
        body += "".join(f"{line}\n" for line in mail.lines)
    codes = write_note(root, slug, note_meta, body, raw_meta, raw_body, clock)
    audit(
        root,
        "ingest.done",
        clock.now(),
        slug=slug,
        pages=len(result.pages),
        kind=privacy_class.value,
        count=calls,
        code=code,
    )
    return IngestResult(slug, sha, ext, quarantined=tuple(codes), backend_calls=calls)

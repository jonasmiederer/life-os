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
from core.ocr import OcrResult, ocr_file
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


def ingest_upload(
    root: Path,
    data: bytes,
    privacy_class: PrivacyClass,
    *,
    backend: Backend | None = None,
    ocr: OcrFn = ocr_file,
    clock: Any = None,
) -> IngestResult:
    """Store one file and write a draft note. Raises UnsupportedFile, OcrError."""
    if privacy_class is PrivacyClass.REDACTED:
        raise ValueError("class redacted is not implemented in Phase 1a")
    clock = clock or SystemClock()
    ext = detect_ext(data)
    if ext != "pdf":
        try:
            data, ext = clean_image(data, ext)
        except BadImage:
            raise UnsupportedFile("unreadable image") from None
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
    fields = from_extraction(extracted)

    received = clock.now().date()
    doc_date = fields.doc_date or received
    slug = f"{doc_date.isoformat()}-{slugify(fields.sender)}-{fields.doc_type}-{sha[:8]}"
    note_meta: dict[str, Any] = {
        "type": fields.doc_type,
        "from": fields.sender,
        "date": doc_date,
        "status": "draft",
        "source": "upload",
        "raw": f"raw/{slug}.md",
    }
    if fields.deadline:
        note_meta["deadline"] = fields.deadline
        note_meta["deadline_kind"] = fields.deadline_kind
    if fields.amount:
        note_meta["amount"] = fields.amount
    raw_meta = {
        "file": f"files/{sha}.{ext}",
        "sha256": sha,
        "pages": len(result.pages),
        "extractor": result.extractor,
        "model_id": result.model_id,
    }
    raw_body = "".join(f"\n## Seite {p.number}\n\n{p.text}\n" for p in result.pages)
    codes = write_note(
        root,
        slug,
        note_meta,
        note_body(fields, "Entwurf, bitte prüfen."),
        raw_meta,
        raw_body,
        clock,
    )
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

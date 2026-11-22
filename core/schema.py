"""Note and raw frontmatter schema (design 2.12). Strict: unknown keys are rejected."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 1_000_000

TYPES = {"steuerbescheid", "rechnung", "mahnung", "kuendigung_vertrag", "versicherung", "sonstiges"}
DEADLINE_KINDS = {"einspruch", "zahlung", "kuendigung", "other", "none"}
STATUSES = {"draft", "confirmed", "done"}
SOURCES = {"upload", "folder", "mail"}
EXTRACTORS = {"cloud", "tesseract", "text"}
FORWARDS = {"attached", "inline"}

SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]{1,60}-[a-z0-9_]+-[0-9a-f]{8}$")
FROM_RE = re.compile(r"^[\w .,&@'()/-]{1,120}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

NOTE_REQUIRED = {"type", "from", "date", "status", "source", "raw"}
NOTE_OPTIONAL = {"deadline", "deadline_kind", "amount", "snooze", "forward"}
RAW_REQUIRED = {"file", "sha256", "pages", "extractor", "model_id"}
RAW_OPTIONAL = {"mail_sha256"}


class ValidationError(ValueError):
    """Carries short reason codes. Codes never contain note content."""

    def __init__(self, codes: list[str]) -> None:
        super().__init__(",".join(codes))
        self.codes = codes


def _unknown(key: object) -> str:
    return "unknown_key:" + re.sub(r"[^A-Za-z0-9_]", "_", str(key))[:32]


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValidationError(["frontmatter_missing"])
    end = text.find("\n---\n", 3)
    if end == -1:
        if text.rstrip().endswith("\n---"):
            end = text.rstrip().rfind("\n---")
        else:
            raise ValidationError(["frontmatter_unclosed"])
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        raise ValidationError(["frontmatter_yaml"]) from exc
    if not isinstance(data, dict):
        raise ValidationError(["frontmatter_not_mapping"])
    return data, text[end + 5 :]


def read_note(path: Path) -> tuple[dict[str, Any], str]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValidationError(["file_too_large"])
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(["not_utf8"]) from exc
    return split_frontmatter(text)


def _opt_date(value: Any) -> bool:
    return value in (None, "") or isinstance(value, date)


def validate_note(path: Path, data_dir: Path, stem: str | None = None) -> list[str]:
    """Return reason codes for a note file under data_dir/notes. Empty list means valid."""
    try:
        meta, _body = read_note(path)
    except ValidationError as exc:
        return exc.codes
    codes: list[str] = []
    for key in sorted(set(meta) - NOTE_REQUIRED - NOTE_OPTIONAL):
        codes.append(_unknown(key))
    for key in sorted(NOTE_REQUIRED - set(meta)):
        codes.append(f"missing_key:{key}")
    if codes:
        return codes
    if meta["type"] not in TYPES:
        codes.append("bad_enum:type")
    if meta["status"] not in STATUSES:
        codes.append("bad_enum:status")
    if meta["source"] not in SOURCES:
        codes.append("bad_enum:source")
    if meta.get("forward") is not None and meta["forward"] not in FORWARDS:
        codes.append("bad_enum:forward")
    kind = meta.get("deadline_kind") or "none"
    if kind not in DEADLINE_KINDS:
        codes.append("bad_enum:deadline_kind")
    if not isinstance(meta["from"], str) or not FROM_RE.match(meta["from"]):
        codes.append("bad_value:from")
    if not isinstance(meta["date"], date):
        codes.append("bad_date:date")
    for key in ("deadline", "snooze"):
        if not _opt_date(meta.get(key)):
            codes.append(f"bad_date:{key}")
    amount = meta.get("amount")
    if amount not in (None, ""):
        try:
            if isinstance(amount, bool) or not Decimal(str(amount)).is_finite():
                raise InvalidOperation
        except InvalidOperation:
            codes.append("bad_value:amount")
    if meta["status"] == "confirmed" and kind != "none" and meta.get("deadline") in (None, ""):
        codes.append("confirmed_without_deadline")
    stem = stem or path.stem
    if not SLUG_RE.match(stem):
        codes.append("bad_slug")
    raw = meta["raw"]
    expected_raw = f"raw/{stem}.md"
    if raw != expected_raw:
        codes.append("raw_path_mismatch")
    elif not (data_dir / raw).is_file():
        codes.append("raw_missing")
    return codes


def validate_raw(path: Path) -> list[str]:
    try:
        meta, _ = read_note(path)
    except ValidationError as exc:
        return exc.codes
    codes = [
        f"unknown_key:{re.sub(r'[^A-Za-z0-9_]', '_', str(k))[:32]}"
        for k in sorted(set(meta) - RAW_REQUIRED - RAW_OPTIONAL, key=str)
    ]
    codes += [f"missing_key:{k}" for k in sorted(RAW_REQUIRED - set(meta))]
    if codes:
        return codes
    if not isinstance(meta["sha256"], str) or not SHA_RE.match(meta["sha256"]):
        codes.append("bad_value:sha256")
    if not isinstance(meta["pages"], int) or isinstance(meta["pages"], bool) or meta["pages"] < 1:
        codes.append("bad_value:pages")
    if "mail_sha256" in meta and not (
        isinstance(meta["mail_sha256"], str) and SHA_RE.match(meta["mail_sha256"])
    ):
        codes.append("bad_value:mail_sha256")
    if meta["extractor"] not in EXTRACTORS:
        codes.append("bad_enum:extractor")
    if not isinstance(meta["model_id"], str) or len(meta["model_id"]) > 80:
        codes.append("bad_value:model_id")
    if (
        not isinstance(meta["file"], str)
        or not meta["file"].startswith("files/")
        or ".." in meta["file"]
    ):
        codes.append("bad_value:file")
    return codes

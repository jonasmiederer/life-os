"""Parse one untrusted .eml into sender, date, text and allowlisted attachments.

Limits are checked while walking, before any payload is decoded. HTML is stripped to text,
never rendered, and no link is followed. Mail headers never leave this module except the
cleaned sender and the date (design 2.14, review p1b points 13, 14, 25).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from core.extract.draft import UNKNOWN_SENDER, _sender
from core.ingest import UnsupportedFile, detect_ext

MAX_MAIL_BYTES = 20 * 1024 * 1024
MAX_PARTS = 100
MAX_DEPTH = 6
MAX_TEXT_CHARS = 200_000
MAX_HEADER_CHARS = 2000
MAX_ATTACHMENTS = 10
MIN_YEAR = 1990

# Bounded policy: no header refolding, defects are tolerated and never raised.
_POLICY = policy.default.clone(raise_on_defect=False, refold_source="none", max_line_length=None)


class MailRejected(ValueError):
    """The mail breaks a limit or cannot be parsed. The message is a short code, never content."""


@dataclass
class ParsedMail:
    forward: str  # attached | inline
    sender: str = UNKNOWN_SENDER
    date: date | None = None
    text: str = ""
    attachments: list[bytes] = field(default_factory=list)
    dropped: int = 0
    notes: list[str] = field(default_factory=list)  # fixed German lines for the note body


class _Budget:
    def __init__(self) -> None:
        self.parts = 0

    def count(self, depth: int) -> None:
        self.parts += 1
        if self.parts > MAX_PARTS or depth > MAX_DEPTH:
            raise MailRejected("too_complex")


@dataclass
class _Collected:
    plain: list[str] = field(default_factory=list)
    html: list[str] = field(default_factory=list)
    blobs: list[bytes] = field(default_factory=list)
    inner: list[Message] = field(default_factory=list)
    dropped: int = 0


def _decode_text(part: Message) -> str:
    raw = part.get_payload(decode=True)
    if not isinstance(raw, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, ValueError):
        return raw.decode("utf-8", errors="replace")


class _Strip(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "head"}:
            self._skip += 1
        elif tag in {"br", "p", "div", "tr", "li"}:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    parser = _Strip()
    parser.feed(html[: MAX_TEXT_CHARS * 2])
    parser.close()
    return "".join(parser.out)


def _collect(root: Message, depth: int, budget: _Budget) -> _Collected:
    """Walk one message. Does not descend into message/rfc822: those are returned in .inner."""
    out = _Collected()
    stack = [(root, depth)]
    while stack:
        part, level = stack.pop()
        budget.count(level)
        ctype = part.get_content_type()
        if part.is_multipart() and ctype != "message/rfc822":
            subs = part.get_payload()
            if isinstance(subs, list):
                stack.extend((sub, level + 1) for sub in reversed(subs))
            continue
        if ctype == "message/rfc822":
            subs = part.get_payload()
            if isinstance(subs, list) and subs and isinstance(subs[0], Message):
                out.inner.append(subs[0])
            continue
        is_attachment = part.get_content_disposition() == "attachment"
        if ctype in {"text/plain", "text/html"} and not is_attachment:
            text = _decode_text(part)[:MAX_TEXT_CHARS]
            (out.plain if ctype == "text/plain" else out.html).append(text)
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes) and payload:
            if len(out.blobs) < MAX_ATTACHMENTS:
                out.blobs.append(payload)
            else:
                out.dropped += 1
    return out


def _header(msg: Message, name: str) -> str:
    try:
        value = msg.get(name)
        return str(value)[:MAX_HEADER_CHARS] if value is not None else ""
    except (ValueError, TypeError, LookupError):
        return ""


def clean_sender(value: str) -> str:
    """Display name (else address) through the same cleaner as model output."""
    name, addr = parseaddr(value.replace("\r", " ").replace("\n", " ")[:MAX_HEADER_CHARS])
    return _sender(name or addr)


_MONTHS = {
    "januar": 1, "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2,
    "märz": 3, "maerz": 3, "march": 3, "mar": 3, "mär": 3, "april": 4, "apr": 4,
    "mai": 5, "may": 5, "juni": 6, "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "oktober": 10, "october": 10,
    "okt": 10, "oct": 10, "november": 11, "nov": 11, "dezember": 12, "december": 12, "dez": 12,
    "dec": 12,
}  # fmt: skip
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DMY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_DMONY = re.compile(r"(\d{1,2})\.?\s+([A-Za-zäÄ]{3,9})\.?,?\s+(\d{4})")
_MONDY = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})")


def _mk(year: int, month: int, day: int, today: date) -> date | None:
    try:
        found = date(year, month, day)
    except ValueError:
        return None
    return found if MIN_YEAR <= found.year and found <= today else None


def parse_date(value: str, today: date) -> date | None:
    """Strict date from a header value. None when it does not parse or lies in the future."""
    value = value.strip()[:100]
    if not value:
        return None
    if (m := re.match(_ISO, value)) is not None:
        return _mk(int(m[1]), int(m[2]), int(m[3]), today)
    if (m := re.match(_DMY, value)) is not None:
        return _mk(int(m[3]), int(m[2]), int(m[1]), today)
    if (m := re.match(_DMONY, value)) is not None and m[2].lower() in _MONTHS:
        return _mk(int(m[3]), _MONTHS[m[2].lower()], int(m[1]), today)
    if (m := re.match(_MONDY, value)) is not None and m[1].lower() in _MONTHS:
        return _mk(int(m[3]), _MONTHS[m[1].lower()], int(m[2]), today)
    try:
        parsed: datetime = parsedate_to_datetime(value)
    except (ValueError, TypeError, IndexError, OverflowError):
        return None
    return _mk(parsed.year, parsed.month, parsed.day, today)


_KEY = re.compile(
    r"^[\s>*_]*(von|from|datum|date|betreff|subject|an|to|cc)\s*:\s*\**\s*(.*)$", re.I
)
_FROM_KEYS = {"von", "from"}
_DATE_KEYS = {"datum", "date"}
_SUBJ_KEYS = {"betreff", "subject"}
_QUOTE = re.compile(r"^[\s>]*")
_BEGIN = re.compile(
    r"^[\s>*_-]*(anfang der weitergeleiteten (e-)?mail|begin forwarded message|"
    r"forwarded message|weitergeleitete nachricht)",
    re.I,
)
MAX_SCAN_LINES = 3000
# A line that starts with "--", is short and is not a quoted-printable soft break.
_BOUNDARY_LINE = re.compile(rb"\n--[^\r\n]{0,200}(?<!=)\r?\n")
MAX_LINE_CHARS = 500  # longer lines are never header lines, and skipping them bounds regex time
MAX_BOUNDARIES = MAX_PARTS * 4
_BLOCK_SPAN = 8


def parse_inline_block(text: str) -> tuple[dict[str, str], str] | None:
    """Find a quoted "Von:/Datum:/Betreff:" block. Returns (headers, text after the block)."""
    lines = text.splitlines()[:MAX_SCAN_LINES]
    for i, line in enumerate(lines):
        m = _KEY.match(line) if len(line) <= MAX_LINE_CHARS else None
        if not m or m[1].lower() not in _FROM_KEYS:
            continue
        found = {"from": m[2]}
        end = i
        for j in range(i + 1, min(i + 1 + _BLOCK_SPAN, len(lines))):
            n = _KEY.match(lines[j]) if len(lines[j]) <= MAX_LINE_CHARS else None
            if n is None:
                if lines[j].strip(" >*\t") == "":
                    continue
                break
            key = n[1].lower()
            if key in _DATE_KEYS:
                found.setdefault("date", n[2])
            elif key in _SUBJ_KEYS:
                found.setdefault("subject", n[2])
            end = j
        if "date" in found or "subject" in found:
            rest = [_QUOTE.sub("", ln, count=1) for ln in lines[end + 1 :]]
            return found, "\n".join(rest).strip()
    return None


def _strip_begin_marker(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if len(ln) > MAX_LINE_CHARS or not _BEGIN.match(ln)
    )


def _text_of(col: _Collected) -> str:
    if any(t.strip() for t in col.plain):
        return "\n\n".join(col.plain)[:MAX_TEXT_CHARS]
    return html_to_text("\n".join(col.html))[:MAX_TEXT_CHARS]


def _allowlisted(blobs: list[bytes]) -> tuple[list[bytes], int]:
    keep: list[bytes] = []
    dropped = 0
    for blob in blobs:
        try:
            detect_ext(blob)  # magic bytes decide, never the file name
        except UnsupportedFile:
            dropped += 1
        else:
            keep.append(blob)
    return keep, dropped


def parse_mail(data: bytes, received: date) -> ParsedMail:
    """Parse one forwarded mail: an attached message/rfc822, else a normal (inline) forward.

    Raises MailRejected: too_large, too_complex, unparseable.
    """
    if len(data) > MAX_MAIL_BYTES:
        raise MailRejected("too_large")
    if (
        len(_BOUNDARY_LINE.findall(data)) > MAX_BOUNDARIES
    ):  # cheap guard: the parser builds every part first
        raise MailRejected("too_complex")
    try:
        outer = BytesParser(policy=_POLICY).parsebytes(data)
        budget = _Budget()
        col = _collect(outer, 0, budget)
        if col.inner:
            source = col.inner[0]
            inner_col = _collect(source, 1, budget)  # outer attachments are dropped
            blobs, dropped = _allowlisted(inner_col.blobs)
            mail = ParsedMail(forward="attached", attachments=blobs, text=_text_of(inner_col))
            mail.dropped = dropped + inner_col.dropped + len(inner_col.inner)
            from_value, date_value = _header(source, "From"), _header(source, "Date")
        else:
            blobs, dropped = _allowlisted(col.blobs)
            text = _strip_begin_marker(_text_of(col))
            mail = ParsedMail(forward="inline", attachments=blobs, text=text)
            mail.dropped = dropped + col.dropped
            from_value = date_value = ""
            block = parse_inline_block(text)
            if block is not None:
                headers, mail.text = block
                from_value, date_value = headers["from"], headers.get("date", "")
            else:
                mail.notes.append(
                    "Kopfzeilen der Original-Mail nicht gefunden. Betreff und Eingangsdatum "
                    "der Weiterleitung verwendet."
                )
    except MailRejected:
        raise
    except (RecursionError, MemoryError, ValueError, TypeError, LookupError, AttributeError):
        raise MailRejected("unparseable") from None
    mail.sender = clean_sender(from_value)
    mail.date = parse_date(date_value, received)
    if mail.forward == "attached":
        mail.notes.append(
            "Weiterleitung: angehängte Mail, Absender und Datum aus der Original-Mail."
        )
    else:
        mail.notes.append("Weiterleitung: normal (inline). Absender und Datum nicht gesichert.")
    if mail.date is None:
        mail.notes.append("Datum nicht lesbar oder nicht gefunden. Eingangsdatum verwendet.")
    if mail.sender == UNKNOWN_SENDER:
        mail.notes.append("Absender nicht lesbar.")
    return mail

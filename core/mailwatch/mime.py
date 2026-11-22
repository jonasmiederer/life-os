"""Structure checks on the outer mail. Attachments are counted, never opened or decoded."""

from __future__ import annotations

import email
import email.parser
import email.policy
from dataclasses import dataclass
from email.message import Message
from email.utils import getaddresses

from core.mailwatch.config import TAGS


class MimeReject(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Structure:
    message_id: str | None
    attachments_dropped: int


HEADER_CAP = 64 * 1024


def header_block(data: bytes, cap: int = HEADER_CAP) -> bytes | None:
    """Bytes before the first blank line, or None if there is none within `cap` bytes."""
    ends = [i for i in (data.find(b"\r\n\r\n"), data.find(b"\n\n")) if i >= 0]
    if not ends or min(ends) > cap:
        return None
    return data[: min(ends)]


def parse_headers(head: bytes) -> Message:
    """Parse the header block only. No body, no parts."""
    try:
        return email.parser.BytesHeaderParser(policy=email.policy.compat32).parsebytes(head)
    except (RecursionError, ValueError, TypeError):
        raise MimeReject("parse") from None


def too_many_boundaries(raw: bytes, max_parts: int) -> bool:
    """Cheap count before building the tree: every part needs a boundary line."""
    return raw.count(b"\n--") > 2 * max_parts + 2


def parse(raw: bytes) -> Message:
    try:
        return email.message_from_bytes(raw, policy=email.policy.compat32)
    except (RecursionError, ValueError, TypeError):
        raise MimeReject("parse") from None


def structure(msg: Message, *, max_parts: int, max_depth: int) -> Structure:
    """Walk the outer tree without recursion. The limits stop the walk, not just the result.

    message/rfc822 parts are leaves: the inner mail is not entered. Every other leaf that is
    not the body text counts as a dropped attachment.
    """
    stack: list[tuple[Message, int]] = [(msg, 1)]
    parts = 0
    dropped = 0
    while stack:
        part, depth = stack.pop()
        parts += 1
        if parts > max_parts:
            raise MimeReject("parts")
        if depth > max_depth:
            raise MimeReject("depth")
        if part.get_content_type() == "message/rfc822":
            continue
        payload = part.get_payload()
        if part.is_multipart() and isinstance(payload, list):
            stack.extend((p, depth + 1) for p in payload if isinstance(p, Message))
        elif part is not msg and part.get_content_type() not in ("text/plain", "text/html"):
            dropped += 1
        elif part is not msg and part.get_content_disposition() == "attachment":
            dropped += 1
    mid = str(msg.get("Message-ID", "")).strip()[:256] or None
    return Structure(message_id=mid, attachments_dropped=dropped)


def plus_tag(msg: Message, header: str) -> str | None:
    """Tag from the outer header (To or Delivered-To). Lowercased, fixed set, else None."""
    values = [str(v) for v in msg.get_all(header, [])]
    for _, addr in getaddresses(values):
        local = addr.rsplit("@", 1)[0].lower()
        _, plus, tag = local.partition("+")
        if plus and tag in TAGS:
            return tag
    return None


def addressed_to(msg: Message, address: str) -> bool:
    """True if To or Delivered-To names the ingest address. A +tag is stripped first."""
    values = [str(v) for h in ("To", "Delivered-To") for v in msg.get_all(h, [])]
    for _, addr in getaddresses(values):
        local, _, domain = addr.lower().rpartition("@")
        if f"{local.partition('+')[0]}@{domain}" == address:
            return True
    return False

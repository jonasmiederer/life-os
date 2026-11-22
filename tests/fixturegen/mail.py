"""synthetic: true

Builders for forwarded-mail fixtures. Pairs follow the watcher contract:
inbox/<sha>.eml plus inbox/<sha>.json, the .json written last. Only example.com addresses.
"""

from __future__ import annotations

import hashlib
import json
from email.message import EmailMessage
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def inner_mail(
    body: str = "Rechnung Nr. 1 über 10 EUR.",
    sender: str = "Beispielwerke <billing@example.com>",
    date: str = "Tue, 03 Mar 2026 10:15:00 +0100",
    subject: str = "Ihre Rechnung",
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Date"], msg["Subject"] = sender, "me@example.com", date, subject
    msg.set_content(body)
    return msg


def forward(inner: EmailMessage | None, outer_body: str = "Fwd") -> bytes:
    """Outer mail with the inner mail attached as message/rfc822 (None: plain mail only)."""
    outer = EmailMessage()
    outer["From"], outer["To"] = "owner@example.com", "ingest@example.com"
    outer["Subject"] = "Fwd: Ihre Rechnung"
    outer.set_content(outer_body)
    if inner is not None:
        outer.add_attachment(inner)
    return outer.as_bytes()


def with_attachment(inner: EmailMessage, data: bytes, subtype: str, name: str) -> EmailMessage:
    inner.add_attachment(data, maintype="application", subtype=subtype, filename=name)
    return inner


def write_pair(
    inbox: Path, eml: bytes, *, tag: str | None = None, v: int = 1, with_json: bool = True
) -> str:
    sha = hashlib.sha256(eml).hexdigest()
    (inbox / f"{sha}.eml").write_bytes(eml)
    if with_json:
        side = {
            "v": v, "id": sha, "sha256": sha, "size": len(eml),
            "received_at": "2026-03-04T08:00:00Z", "plus_tag": tag, "auth": "pass",
            "message_id": "<x@example.com>", "attachments_dropped": 0,
        }  # fmt: skip
        (inbox / f"{sha}.json").write_text(json.dumps(side))
    return sha


def nested_loop(depth: int) -> EmailMessage:
    msg = inner_mail("innermost")
    for _ in range(depth):
        wrap = EmailMessage()
        wrap["From"] = "loop@example.com"
        wrap.set_content("wrap")
        wrap.add_attachment(msg)
        msg = wrap
    return msg


def many_parts(count: int) -> EmailMessage:
    multi = MIMEMultipart()
    multi["From"], multi["Date"] = "many@example.com", "Tue, 03 Mar 2026 10:15:00 +0100"
    for i in range(count):
        multi.attach(MIMEText(f"part {i}", "plain"))
    return multi  # type: ignore[return-value]


def html_only(html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["Date"] = "html@example.com", "Tue, 03 Mar 2026 10:15:00 +0100"
    msg.set_content(html, subtype="html")
    return msg


def raw_app(data: bytes, name: str, subtype: str = "octet-stream") -> MIMEApplication:
    return MIMEApplication(data, subtype, Name=name)


DE_BLOCK = (
    "Anfang der weitergeleiteten E-Mail:\n\n"
    "Von: Beispielwerke <billing@example.com>\n"
    "Betreff: Ihre Rechnung\n"
    "Datum: 3. März 2026 um 10:15:00 MEZ\n"
    "An: Max Muster <me@example.com>\n\n"
    "Guten Tag, anbei die Rechnung über 10 EUR.\n"
)
EN_BLOCK = (
    "Begin forwarded message:\n\n"
    "From: Example Utilities <billing@example.com>\n"
    "Subject: Your invoice\n"
    "Date: March 3, 2026 at 10:15:00 AM GMT+1\n"
    "To: me@example.com\n\n"
    "Hello, your invoice for 10 EUR is attached.\n"
)


def forward_inline(body: str, attachments: tuple[tuple[bytes, str, str], ...] = ()) -> bytes:
    """Normal forward (iPhone Mail default): quoted block in the body, files on the outer mail."""
    outer = EmailMessage()
    outer["From"], outer["To"] = "owner@example.com", "ingest@example.com"
    outer["Subject"] = "Fwd: Ihre Rechnung"
    outer["Date"] = "Wed, 04 Mar 2026 08:00:00 +0100"
    outer.set_content(body)
    for data, subtype, name in attachments:
        outer.add_attachment(data, maintype="application", subtype=subtype, filename=name)
    return outer.as_bytes()

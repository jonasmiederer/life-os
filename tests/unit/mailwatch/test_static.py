"""Static checks: no SMTP, no delete, no TLS switch-off, compose limits."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "core" / "mailwatch"


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in PKG.glob("*.py")}


def test_no_smtp_anywhere() -> None:
    banned = re.compile(
        r"smtplib|aiosmtplib|sendmail|\bsmtp\b(?!\.mailfrom)|\bsmtpd\b", re.IGNORECASE
    )
    ports = re.compile(r"\b(?:25|465|587)\b")
    for name, text in _sources().items():
        assert not banned.search(text), name
        assert not ports.search(text), name
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert not [d for d in deps if re.search(r"smtp|mail", d, re.IGNORECASE)]


def test_no_delete_or_expunge() -> None:
    banned = re.compile(
        r"expunge|\\\\Deleted|\"STORE\"|'STORE'|\.delete\(|\"DELETE\"", re.IGNORECASE
    )
    for name, text in _sources().items():
        assert not banned.search(text), name


def test_tls_cannot_be_disabled() -> None:
    banned = re.compile(r"CERT_NONE|check_hostname\s*=\s*False|_create_unverified|starttls|IMAP4\(")
    for name, text in _sources().items():
        assert not banned.search(text), name


def test_password_only_from_file() -> None:
    for name, text in _sources().items():
        assert not re.search(r"environ.*PASSWORD|PASSWORD\"\)|_PASSWORD\b", text), name


def _service_block() -> str:
    text = (ROOT / "compose.yaml").read_text()
    m = re.search(r"^  ingest-mail:\n(.*?)(?=^  \S|^\S)", text, re.MULTILINE | re.DOTALL)
    assert m, "ingest-mail service missing"
    return m.group(1)


def test_compose_ingest_mail_is_locked_down() -> None:
    block = _service_block()
    for needle in (
        'user: "10001:10001"',
        "read_only: true",
        "cap_drop: [ALL]",
        "no-new-privileges:true",
        "mem_limit:",
        "pids_limit:",
        "secrets: [mail_password]",
        "/inbox:/data/inbox",
    ):
        assert needle in block, needle
    assert "ports:" not in block
    assert not re.search(r"\b(?:25|465|587)\b", block)
    volumes = re.findall(r"^\s+- (\S+:/\S+)", block, re.MULTILINE)
    assert volumes == ["${LIFEOS_DATA_DIR:-./data}/inbox:/data/inbox"]
    assert not re.search(r"environment:.*PASSWORD=", block, re.DOTALL)

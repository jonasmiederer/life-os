"""Watcher settings from environment variables. The password comes from a secret file only."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TAGS = frozenset({"tax", "contract", "local"})
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_AUTHSERV = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
_ADDR = re.compile(r"^[^@\s]+@[A-Za-z0-9.-]+$")
_FOLDER = re.compile(r"^[A-Za-z0-9 ._/-]{1,64}$")


class ConfigError(ValueError):
    """Bad or missing setting. The message names the setting, never its value."""


@dataclass(frozen=True)
class MailConfig:
    host: str
    user: str
    password_file: Path
    authserv_id: str
    allowed_from: frozenset[str]
    allowed_domains: frozenset[str]
    ingest_address: str
    data_dir: Path = Path("/data")
    folder: str = "INBOX"
    processed: str = "Processed"
    rejected: str = "Rejected"
    port: int = 993  # TLS only. No plain-text port is supported.
    tag_header: str = "Delivered-To"
    max_bytes: int = 10 * 1024 * 1024
    pass_seconds: int = 120
    max_parts: int = 50
    max_depth: int = 8
    daily_cap: int = 30
    poll_seconds: int = 300
    backoff_floor_seconds: int = 300
    backoff_max_seconds: int = 21600
    ntfy_url: str = ""
    ntfy_topic: str = "lifeos"

    @property
    def inbox(self) -> Path:
        return self.data_dir / "inbox"


def _int(env: Mapping[str, str], key: str, default: int, low: int, high: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None
    if not low <= value <= high:
        raise ConfigError(f"{key} out of range")
    return value


def _list(env: Mapping[str, str], key: str) -> frozenset[str]:
    return frozenset(p.strip().lower() for p in env.get(key, "").split(",") if p.strip())


def load(env: Mapping[str, str]) -> MailConfig:
    host = env.get("LIFEOS_MAIL_IMAP_HOST", "")
    if not _HOST.match(host):
        raise ConfigError("LIFEOS_MAIL_IMAP_HOST missing or invalid")
    user = env.get("LIFEOS_MAIL_USER", "")
    if not user:
        raise ConfigError("LIFEOS_MAIL_USER missing")
    authserv = env.get("LIFEOS_MAIL_AUTHSERV_ID", "").lower()
    if not _AUTHSERV.match(authserv):
        raise ConfigError("LIFEOS_MAIL_AUTHSERV_ID missing or invalid")
    senders = _list(env, "LIFEOS_MAIL_ALLOWED_FROM")
    domains = _list(env, "LIFEOS_MAIL_ALLOWED_DOMAINS")
    if not senders or not all(_ADDR.match(a) for a in senders):
        raise ConfigError("LIFEOS_MAIL_ALLOWED_FROM missing or invalid")
    if not domains:
        raise ConfigError("LIFEOS_MAIL_ALLOWED_DOMAINS missing")
    ingest = env.get("LIFEOS_MAIL_INGEST_ADDRESS", "").strip().lower()
    if not _ADDR.match(ingest) or "+" in ingest:
        raise ConfigError("LIFEOS_MAIL_INGEST_ADDRESS missing or invalid")
    names = {
        k: env.get(f"LIFEOS_MAIL_{k.upper()}", d)
        for k, d in (("folder", "INBOX"), ("processed", "Processed"), ("rejected", "Rejected"))
    }
    if not all(_FOLDER.match(n) for n in names.values()) or len(set(names.values())) != 3:
        raise ConfigError("LIFEOS_MAIL_FOLDER/PROCESSED/REJECTED invalid or not distinct")
    tag_header = env.get("LIFEOS_MAIL_TAG_HEADER", "Delivered-To")
    if not _HEADER.match(tag_header):
        raise ConfigError("LIFEOS_MAIL_TAG_HEADER invalid")
    return MailConfig(
        host=host,
        user=user,
        password_file=Path(env.get("LIFEOS_MAIL_PASSWORD_FILE", "/run/secrets/mail_password")),
        authserv_id=authserv,
        allowed_from=senders,
        allowed_domains=domains,
        ingest_address=ingest,
        data_dir=Path(env.get("LIFEOS_DATA_DIR", "/data")),
        folder=names["folder"],
        processed=names["processed"],
        rejected=names["rejected"],
        tag_header=tag_header,
        max_bytes=_int(env, "LIFEOS_MAIL_MAX_BYTES", 10 * 1024 * 1024, 1024, 200 * 1024 * 1024),
        pass_seconds=_int(env, "LIFEOS_MAIL_PASS_SECONDS", 120, 5, 3600),
        max_parts=_int(env, "LIFEOS_MAIL_MAX_PARTS", 50, 1, 1000),
        max_depth=_int(env, "LIFEOS_MAIL_MAX_DEPTH", 8, 1, 50),
        daily_cap=_int(env, "LIFEOS_MAIL_DAILY_CAP", 30, 1, 1000),
        poll_seconds=_int(env, "LIFEOS_MAIL_POLL_SECONDS", 300, 60, 86400),
        ntfy_url=env.get("LIFEOS_NTFY_URL", ""),
        ntfy_topic=env.get("LIFEOS_NTFY_TOPIC", "lifeos"),
    )


def read_password(path: Path) -> str:
    """Read the secret file. Errors never carry the content."""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError(f"cannot read password file: {type(exc).__name__}") from None
    if not value:
        raise ConfigError("password file is empty")
    if not value.isascii():
        raise ConfigError("password is not ASCII")
    return value

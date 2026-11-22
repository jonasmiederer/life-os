"""Owner login: scrypt password hash, in-memory sessions with idle timeout, failure lock."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

_N, _R, _P = 2**14, 8, 1
FAIL_LIMIT = 5
FAIL_WINDOW = timedelta(minutes=5)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(got, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


@dataclass
class Session:
    csrf: str
    last_seen: datetime


class Sessions:
    """Sessions live in memory: a restart signs the owner out. Idle timeout slides."""

    def __init__(self, clock: Any, idle: timedelta) -> None:
        self._clock = clock
        self._idle = idle
        self._items: dict[str, Session] = {}

    def create(self) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        session = Session(secrets.token_urlsafe(24), self._clock.now())
        self._items[token] = session
        return token, session

    def get(self, token: str | None) -> Session | None:
        session = self._items.get(token or "")
        if session is None:
            return None
        now = self._clock.now()
        if now - session.last_seen > self._idle:
            del self._items[token or ""]
            return None
        session.last_seen = now
        return session

    def drop(self, token: str | None) -> None:
        self._items.pop(token or "", None)


class LoginLimiter:
    """One owner, one global counter: 5 wrong passwords in 5 minutes lock login."""

    def __init__(self, clock: Any) -> None:
        self._clock = clock
        self._fails: list[datetime] = []

    def locked(self) -> bool:
        cutoff = self._clock.now() - FAIL_WINDOW
        self._fails = [t for t in self._fails if t > cutoff]
        return len(self._fails) >= FAIL_LIMIT

    def fail(self) -> None:
        self._fails.append(self._clock.now())

    def reset(self) -> None:
        self._fails.clear()

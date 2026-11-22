from __future__ import annotations

import ssl
import subprocess
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.mailwatch.config import MailConfig
from core.mailwatch.watcher import Watcher
from tests.unit.mailwatch.fake_imap import FakeImap

PASSWORD = "-".join(["planted", "secret", "value"])
SUBJECT = "planted subject 4711"
AUTHSERV = "mx.example.net"
GOOD_AR = (
    f"{AUTHSERV}; dkim=pass header.d=example.com header.s=s1;"
    " spf=pass smtp.mailfrom=owner@example.com; dmarc=pass header.from=example.com"
)


def build(
    *,
    ar: list[str] | None = None,
    sender: str = "owner@example.com",
    to: str = "ingest@example.com",
    subject: str = SUBJECT,
    extra: list[str] | None = None,
    body: str = "forwarded",
    multipart: str | None = None,
) -> bytes:
    heads = [f"Authentication-Results: {a}" for a in (ar if ar is not None else [GOOD_AR])]
    heads += [
        "Received: from somewhere by mx.example.net",
        f"From: Owner <{sender}>",
        f"To: {to}",
        f"Subject: {subject}",
        "Message-ID: <abc@example.com>",
        "Date: Sun, 22 Nov 2026 10:00:00 +0000",
        "MIME-Version: 1.0",
    ]
    heads += extra or []
    if multipart is not None:
        return ("\r\n".join(heads) + "\r\n" + multipart).encode()
    heads.append("Content-Type: text/plain")
    return ("\r\n".join(heads) + "\r\n\r\n" + body + "\r\n").encode()


@pytest.fixture(scope="session")
def certs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    d = tmp_path_factory.mktemp("tls")
    cert, key = d / "c.pem", d / "k.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-subj", "/CN=localhost", "-days", "2",
         "-addext", "subjectAltName=DNS:localhost"],
        check=True, capture_output=True,
    )  # fmt: skip
    return cert, key


@pytest.fixture
def server(certs: tuple[Path, Path]) -> Iterator[FakeImap]:
    s = FakeImap(*certs)
    yield s
    s.stop()


@pytest.fixture
def cfg(tmp_path: Path, server: FakeImap) -> MailConfig:
    pw = tmp_path / "pw"
    pw.write_text(PASSWORD + "\n")
    return MailConfig(
        host="localhost",
        port=server.port,
        user="ingest",
        password_file=pw,
        authserv_id=AUTHSERV,
        allowed_from=frozenset({"owner@example.com"}),
        allowed_domains=frozenset({"example.com"}),
        ingest_address="ingest@example.com",
        folder="Ingest",
        data_dir=tmp_path / "data",
        max_bytes=100_000,
        max_parts=10,
        max_depth=4,
        daily_cap=3,
    )


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def pushes() -> list[str]:
    return []


@pytest.fixture
def make_watcher(
    cfg: MailConfig, certs: tuple[Path, Path], clock: Clock, pushes: list[str]
) -> Callable[[], Watcher]:
    ctx = ssl.create_default_context(cafile=str(certs[0]))
    return lambda: Watcher(cfg, notify=pushes.append, now=clock, ssl_context=ctx)

"""synthetic: true

Upload end to end through the WSGI app: login, class box, nur lokal, files/raw/notes, commit.
OCR is a test-local stub so these tests run without tesseract. Real OCR tests skip if missing.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from pytest import fixture

from core.clock import FakeClock
from core.datadir import init_data_dir
from core.gateway.interface import (
    BackendUnavailable,
    GatewayRequest,
    GatewayResult,
    PrivacyClass,
)
from core.ingest import UnsupportedFile, detect_ext, ingest_upload, slugify
from core.ocr import OcrResult, PageText, TesseractMissing, ocr_file
from core.schema import read_note, validate_note
from core.web.app import WebApp, parse_multipart
from core.web.auth import hash_password, verify_password

# Alias: a dotted decorator at column 0 reads as an email to the push scanner.
parametrize = pytest.mark.parametrize

LETTERS = Path(__file__).parents[2] / "fixtures" / "letters"
PNG = (LETTERS / "invoice-clean-1.png").read_bytes()
PASSWORD = "correct horse"  # noqa: S105
BOUNDARY = "xxBOUNDARYxx"
FIELDS = ("sender", "date", "amount", "currency", "deadline", "doc_type")
EXTRACTED: dict[str, object] = {
    "sender": "Beispielwerke AG",
    "date": "2030-05-18",
    "amount": "592.97",
    "currency": "EUR",
    "deadline": "2030-06-01",
    "doc_type": "rechnung",
    "confidence": {k: 0.9 for k in FIELDS},
}


class FakeBackend:
    """Test-local stand-in for the Backend protocol. Counts calls."""

    name = "fake"

    def __init__(self, data: dict[str, object] | None = None, fail: bool = False) -> None:
        self.calls: list[GatewayRequest] = []
        self._data = EXTRACTED if data is None else data
        self._fail = fail

    def run(self, request: GatewayRequest) -> GatewayResult:
        self.calls.append(request)
        if self._fail:
            raise BackendUnavailable("down")
        return GatewayResult(self._data, "fake", "fake-1")


def fake_ocr(path: Path) -> OcrResult:
    return OcrResult([PageText(1, "Rechnung Beispielwerke AG 592,97 EUR")])


@fixture()
def root(tmp_path: Path) -> Path:
    r = tmp_path / "data"
    init_data_dir(r)
    return r


class Client:
    def __init__(self, app: WebApp, clock: FakeClock) -> None:
        self.app = app
        self.clock = clock
        self.cookie = ""

    def request(
        self, method: str, path: str, body: bytes = b"", ctype: str = ""
    ) -> tuple[str, dict[str, str], bytes]:
        env: dict[str, Any] = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_TYPE": ctype,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        if self.cookie:
            env["HTTP_COOKIE"] = self.cookie
        out: dict[str, Any] = {}

        def start(status: str, headers: list[tuple[str, str]]) -> None:
            out["status"], out["headers"] = status, dict(headers)

        data = b"".join(self.app(env, start))
        if "Set-Cookie" in out["headers"]:
            self.cookie = out["headers"]["Set-Cookie"].split(";")[0]
        return out["status"], out["headers"], data

    def anonymous(self) -> Client:
        return Client(self.app, self.clock)

    def login(self, password: str = PASSWORD) -> str:
        body = urlencode({"password": password}).encode()
        return self.request("POST", "/login", body, "application/x-www-form-urlencoded")[0]

    def csrf(self) -> str:
        page = self.request("GET", "/")[2].decode()
        return page.split('name="csrf" value="')[1].split('"')[0]

    def upload(
        self,
        file: bytes = PNG,
        klass: str | None = "allow",
        local: bool = False,
        csrf: str | None = None,
    ) -> tuple[str, bytes]:
        fields: dict[str, bytes] = {"csrf": (csrf or self.csrf()).encode(), "file": file}
        if klass is not None:
            fields["class"] = klass.encode()
        if local:
            fields["local_only"] = b"1"
        parts = b""
        for name, value in fields.items():
            disp = f'form-data; name="{name}"' + ('; filename="a.png"' if name == "file" else "")
            parts += f"--{BOUNDARY}\r\nContent-Disposition: {disp}\r\n\r\n".encode() + value
            parts += b"\r\n"
        parts += f"--{BOUNDARY}--\r\n".encode()
        status, _, body = self.request(
            "POST", "/upload", parts, f"multipart/form-data; boundary={BOUNDARY}"
        )
        return status, body


def make(root: Path, backend: FakeBackend | None = None, idle_minutes: int = 30) -> Client:
    clock = FakeClock()
    app = WebApp(
        root,
        hash_password(PASSWORD),
        backend=backend,
        ocr=fake_ocr,
        clock=clock,
        idle_minutes=idle_minutes,
        secure_cookie=False,
    )
    return Client(app, clock)


def git(root: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return res.stdout


def notes(root: Path) -> list[Path]:
    return [n for n in (root / "notes").glob("*.md")]


def test_upload_end_to_end(root: Path) -> None:
    backend = FakeBackend()
    c = make(root, backend)
    assert c.login().startswith("303")
    before = int(git(root, "rev-list", "--count", "HEAD"))
    status, body = c.upload()
    assert status.startswith("200"), body
    assert int(git(root, "rev-list", "--count", "HEAD")) == before + 1
    (note,) = notes(root)
    assert note.stem.startswith("2030-05-18-beispielwerke-ag-rechnung-")
    assert validate_note(note, root) == []
    text = note.read_text()
    assert "status: draft" in text and "deadline: 2030-06-01" in text
    assert "deadline_kind: zahlung" in text and "amount: '592.97'" in text
    raw = (root / "raw" / f"{note.stem}.md").read_text()
    assert "extractor: tesseract" in raw and "pages: 1" in raw and "Seite 1" in raw
    assert len(list((root / "files").glob("*.png"))) == 1
    assert len(backend.calls) == 1 and backend.calls[0].privacy_class is PrivacyClass.ALLOW
    assert git(root, "status", "--porcelain").strip() == ""


def test_duplicate_upload_is_not_written_twice(root: Path) -> None:
    c = make(root, FakeBackend())
    c.login()
    c.upload()
    before = git(root, "rev-list", "--count", "HEAD")
    status, body = c.upload()
    assert status.startswith("200") and "schon vorhanden" in body.decode()
    assert git(root, "rev-list", "--count", "HEAD") == before


def test_login_required_for_upload_and_images(root: Path) -> None:
    c = make(root, FakeBackend())
    c.login()
    c.upload()
    name = next((root / "files").glob("*.png")).name
    anon = c.anonymous()
    assert anon.request("GET", "/")[0].startswith("303")
    assert anon.request("GET", f"/files/{name}")[0].startswith("303")
    ctype = "multipart/form-data; boundary=x"
    assert anon.request("POST", "/upload", b"", ctype)[0].startswith("303")
    status, headers, data = c.request("GET", f"/files/{name}")
    assert (
        status.startswith("200")
        and data == (root / "files" / name).read_bytes()
        and headers["Content-Type"] == "image/png"
    )
    assert c.request("GET", "/files/../../etc/passwd")[0].startswith("404")
    c.request("POST", "/logout")
    assert c.request("GET", f"/files/{name}")[0].startswith("303")


def test_wrong_password_and_lockout(root: Path) -> None:
    c = make(root)
    for _ in range(5):
        assert c.login("nope").startswith("401")
    assert c.login(PASSWORD).startswith("429")
    c.clock.advance(minutes=6)
    assert c.login(PASSWORD).startswith("303")


def test_session_idle_timeout(root: Path) -> None:
    c = make(root, idle_minutes=30)
    c.login()
    assert c.request("GET", "/")[0].startswith("200")
    c.clock.advance(minutes=31)
    assert c.request("GET", "/")[0].startswith("303")


def test_class_box_required_and_csrf(root: Path) -> None:
    backend = FakeBackend()
    c = make(root, backend)
    c.login()
    assert c.upload(klass=None)[0].startswith("400")
    assert c.upload(klass="")[0].startswith("400")
    assert c.upload(klass="redacted")[0].startswith("400")
    assert c.upload(csrf="wrong")[0].startswith("403")
    assert list((root / "files").iterdir()) == []
    assert backend.calls == []


@parametrize(("klass", "local"), [("local", False), ("block", False), ("allow", True)])
def test_local_and_block_make_zero_backend_calls(root: Path, klass: str, local: bool) -> None:
    backend = FakeBackend()
    c = make(root, backend)
    c.login()
    assert c.upload(klass=klass, local=local)[0].startswith("200")
    assert backend.calls == []
    text = notes(root)[0].read_text()
    assert "type: sonstiges" in text and "from: unbekannt" in text
    audit = "".join(p.read_text() for p in (root / "audit").glob("*.jsonl"))
    assert '"count": 0' in audit and '"code": "skipped"' in audit


def test_backend_failure_gives_empty_draft(root: Path) -> None:
    backend = FakeBackend(fail=True)
    c = make(root, backend)
    c.login()
    assert c.upload()[0].startswith("200")
    assert len(backend.calls) == 1
    assert "type: sonstiges" in notes(root)[0].read_text()


def test_hostile_model_output_is_sanitised(root: Path) -> None:
    bad = {**EXTRACTED, "sender": "<b>Evil</b>\n---\nstatus: confirmed", "amount": "NaN"}
    c = make(root, FakeBackend(bad))
    c.login()
    assert c.upload()[0].startswith("200")
    (note,) = notes(root)
    assert validate_note(note, root) == []
    meta, _ = read_note(note)
    assert "amount" not in meta and meta["status"] == "draft"


def test_unsupported_and_oversize_files(root: Path) -> None:
    c = make(root, FakeBackend())
    c.login()
    assert c.upload(file=b"GIF89a....")[0].startswith("400")
    assert c.upload(file=b"")[0].startswith("400")
    with pytest.raises(UnsupportedFile):
        detect_ext(b"%PDF-" + b"0" * (25 * 1024 * 1024))


def test_ingest_rejects_redacted(root: Path) -> None:
    with pytest.raises(ValueError, match="redacted"):
        ingest_upload(root, PNG, PrivacyClass.REDACTED, ocr=fake_ocr)


def test_password_hash_roundtrip() -> None:
    h = hash_password("pw")
    assert verify_password("pw", h) and not verify_password("px", h)
    assert not verify_password("pw", "garbage")
    assert "pw" not in h


def test_parse_multipart_keeps_binary() -> None:
    blob = bytes(range(256)) + b"\r\n--\r\n"
    head = b'--b\r\nContent-Disposition: form-data; name="file"; filename="x"\r\n\r\n'
    body = head + blob + b"\r\n--b--\r\n"
    assert parse_multipart("multipart/form-data; boundary=b", body)["file"] == blob


def test_slugify() -> None:
    assert slugify("Müller & Söhne GmbH") == "muller-sohne-gmbh"
    assert slugify("???") == "unbekannt"


def test_ocr_missing_tesseract_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(TesseractMissing):
        ocr_file(LETTERS / "invoice-clean-1.png")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_real_ocr_reads_fixture_png() -> None:
    res = ocr_file(LETTERS / "invoice-clean-1.png")
    assert len(res.pages) == 1 and "Beispielwerke" in res.text


@pytest.mark.skipif(
    shutil.which("tesseract") is None or shutil.which("pdftoppm") is None,
    reason="tesseract or pdftoppm not installed",
)
def test_real_ocr_reads_fixture_pdf() -> None:
    res = ocr_file(LETTERS / "invoice-clean-1.pdf")
    assert len(res.pages) >= 1 and "Beispielwerke" in res.text

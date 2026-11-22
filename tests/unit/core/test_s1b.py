"""synthetic: true

S1b: review page and confirm, gateway wiring and audit, ntfy reminders on a fake clock,
HEIC and EXIF/GPS stripping. OCR and backend are test doubles. No real data.
"""

from __future__ import annotations

import io
import json
import subprocess
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pillow_heif
import pytest
from PIL import Image
from pytest import fixture

from core.clock import FakeClock
from core.datadir import init_data_dir
from core.gateway.fake import FakeBackend
from core.gateway.interface import PrivacyClass
from core.images import clean_image
from core.ingest import UnsupportedFile, detect_ext, ingest_upload
from core.notify import NotifyError, ntfy_sender, run_due
from core.ocr import OcrResult, PageText
from core.schema import read_note
from core.web.app import WebApp
from core.web.auth import hash_password

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
TEXT = "Rechnung Beispielwerke AG 592,97 EUR"


def ocr_stub(text: str = TEXT) -> Any:
    return lambda path: OcrResult([PageText(1, text)])


def doc_id(data: bytes = PNG, ext: str = "png") -> str:
    import hashlib

    return "doc-" + hashlib.sha256(clean_image(data, ext)[0]).hexdigest()[:8]


@fixture()
def root(tmp_path: Path) -> Path:
    r = tmp_path / "data"
    init_data_dir(r)
    return r


def gateway_lines(root: Path) -> list[dict[str, Any]]:
    path = root / "audit" / "gateway.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def commits(root: Path) -> int:
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "rev-list", "--count", "HEAD"],  # noqa: S607
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return int(out.stdout)


class Client:
    def __init__(self, app: WebApp) -> None:
        self.app, self.cookie = app, ""

    def request(
        self, method: str, path: str, form: dict[str, str] | None = None
    ) -> tuple[str, str]:
        body = urlencode(form or {}).encode()
        env: dict[str, Any] = {
            "REQUEST_METHOD": method, "PATH_INFO": path,
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body),
        }  # fmt: skip
        if self.cookie:
            env["HTTP_COOKIE"] = self.cookie
        out: dict[str, Any] = {}

        def start(status: str, headers: list[tuple[str, str]]) -> None:
            out["status"], out["headers"] = status, dict(headers)

        data = b"".join(self.app(env, start)).decode()
        if "Set-Cookie" in out["headers"]:
            self.cookie = out["headers"]["Set-Cookie"].split(";")[0]
        return out["status"], data

    def login(self) -> None:
        assert self.request("POST", "/login", {"password": PASSWORD})[0].startswith("303")

    def csrf(self) -> str:
        return self.request("GET", "/")[1].split('name="csrf" value="')[1].split('"')[0]


def make(
    root: Path, backend: Any = None, send: Any = None, clock: FakeClock | None = None
) -> Client:
    app = WebApp(
        root, hash_password(PASSWORD), backend=backend, ocr=ocr_stub(),
        clock=clock or FakeClock(datetime(2030, 5, 1, 12, 0, tzinfo=UTC)),
        secure_cookie=False, send=send,
    )  # fmt: skip
    return Client(app)


def ingest(root: Path, klass: PrivacyClass, backend: Any, text: str = TEXT) -> str:
    res = ingest_upload(root, PNG, klass, backend=backend, ocr=ocr_stub(text),
                        clock=FakeClock(datetime(2030, 5, 1, 12, 0, tzinfo=UTC)))  # fmt: skip
    return res.slug


# --- gateway wiring ---------------------------------------------------------------------


def test_allow_makes_one_call_and_one_audit_line_without_content(root: Path) -> None:
    backend = FakeBackend({doc_id(): EXTRACTED})
    slug = ingest(root, PrivacyClass.ALLOW, backend)
    assert backend.calls == 1
    (line,) = gateway_lines(root)
    assert line["doc_id"] == doc_id() and line["outcome"] == "ok" and line["class"] == "allow"
    assert "Beispielwerke" not in json.dumps(line) and "592" not in json.dumps(line)
    assert read_note(root / "notes" / f"{slug}.md")[0]["from"] == "Beispielwerke AG"


@pytest.mark.parametrize("klass", [PrivacyClass.LOCAL, PrivacyClass.BLOCK])
def test_local_and_block_make_zero_calls_and_no_audit_line(root: Path, klass: PrivacyClass) -> None:
    backend = FakeBackend({doc_id(): EXTRACTED})
    ingest(root, klass, backend)
    assert backend.calls == 0 and gateway_lines(root) == []


def test_health_keyword_downgrades_allow_to_zero_calls(root: Path) -> None:
    backend = FakeBackend({doc_id(): EXTRACTED})
    ingest(root, PrivacyClass.ALLOW, backend, "Befund vom Arzt")
    assert backend.calls == 0 and gateway_lines(root) == []


def test_nur_lokal_box_over_web_makes_zero_calls(root: Path) -> None:
    backend = FakeBackend({doc_id(): EXTRACTED})
    c = make(root, backend)
    c.login()
    parts = b""
    for name, value in {"csrf": c.csrf().encode(), "file": PNG, "class": b"allow",
                        "local_only": b"1"}.items():  # fmt: skip
        parts += f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        parts += value + b"\r\n"
    parts += f"--{BOUNDARY}--\r\n".encode()
    env: dict[str, Any] = {
        "REQUEST_METHOD": "POST", "PATH_INFO": "/upload", "CONTENT_LENGTH": str(len(parts)),
        "CONTENT_TYPE": f"multipart/form-data; boundary={BOUNDARY}",
        "wsgi.input": io.BytesIO(parts), "HTTP_COOKIE": c.cookie,
    }  # fmt: skip
    got: list[str] = []
    b"".join(c.app(env, lambda status, headers: got.append(status)))
    assert got[0].startswith("200")
    assert backend.calls == 0 and gateway_lines(root) == []


# --- review and confirm -----------------------------------------------------------------


def test_review_requires_login(root: Path) -> None:
    slug = ingest(root, PrivacyClass.LOCAL, None)
    c = make(root)
    assert c.request("GET", "/review")[0].startswith("303")
    assert c.request("GET", f"/review/{slug}")[0].startswith("303")


def test_review_shows_image_and_confirm_writes_note_and_one_commit(root: Path) -> None:
    slug = ingest(root, PrivacyClass.ALLOW, FakeBackend({doc_id(): EXTRACTED}))
    sent: list[str] = []
    c = make(root, send=sent.append)
    c.login()
    status, page = c.request("GET", f"/review/{slug}")
    assert status.startswith("200") and '<img src="/files/' in page and "Beispielwerke AG" in page
    csrf = page.split('name="csrf" value="')[1].split('"')[0]
    before = commits(root)
    form = {"csrf": csrf, "doc_type": "rechnung", "sender": "Beispielwerke AG",
            "doc_date": "2030-05-18", "amount": "592,97", "deadline": "2030-06-03"}  # fmt: skip
    assert c.request("POST", f"/review/{slug}/confirm", form)[0].startswith("200")
    meta = read_note(root / "notes" / f"{slug}.md")[0]
    assert meta["status"] == "confirmed" and str(meta["deadline"]) == "2030-06-03"
    assert meta["deadline_kind"] == "zahlung" and meta["amount"] == "592.97"
    assert commits(root) == before + 1
    assert c.request("POST", f"/review/{slug}/confirm", form)[0].startswith("400")  # twice
    assert commits(root) == before + 1
    assert sent == []  # 33 days before the deadline: no lead has come yet


def test_confirm_rejects_bad_input_and_wrong_csrf(root: Path) -> None:
    slug = ingest(root, PrivacyClass.LOCAL, None)
    c = make(root)
    c.login()
    csrf = c.csrf()
    base = {"csrf": csrf, "doc_type": "rechnung", "sender": "Beispielwerke AG",
            "doc_date": "2030-05-18", "amount": "", "deadline": ""}  # fmt: skip
    before = commits(root)
    for bad in ({"deadline": "morgen"}, {"doc_type": "x"}, {"amount": "abc"}, {"sender": "<b>"}):
        assert c.request("POST", f"/review/{slug}/confirm", {**base, **bad})[0].startswith("400")
    assert c.request("POST", f"/review/{slug}/confirm", {**base, "csrf": "no"})[0].startswith("403")
    assert read_note(root / "notes" / f"{slug}.md")[0]["status"] == "draft"
    assert commits(root) == before


def test_confirm_inside_lead_time_pushes_once(root: Path) -> None:
    slug = ingest(root, PrivacyClass.LOCAL, None)
    sent: list[str] = []
    c = make(root, send=sent.append)  # clock: 2030-05-01
    c.login()
    form = {"csrf": c.csrf(), "doc_type": "rechnung", "sender": "Beispielwerke AG",
            "doc_date": "2030-04-20", "amount": "", "deadline": "2030-05-05"}  # fmt: skip
    c.request("POST", f"/review/{slug}/confirm", form)
    assert sent == ["1 Frist wartet"]


# --- reminders --------------------------------------------------------------------------


def confirmed_note(root: Path, deadline: str = "2030-06-01") -> str:
    slug = ingest(root, PrivacyClass.LOCAL, None)
    c = make(root)
    c.login()
    form = {"csrf": c.csrf(), "doc_type": "rechnung", "sender": "Beispielwerke AG",
            "doc_date": "2030-05-18", "amount": "", "deadline": deadline}  # fmt: skip
    c.request("POST", f"/review/{slug}/confirm", form)
    return slug


def test_push_fires_at_lead_time_once(root: Path) -> None:
    confirmed_note(root)  # zahlung: leads 7, 3, 1, 0 days
    clock = FakeClock(datetime(2030, 5, 25, 8, 59, tzinfo=UTC))
    sent: list[str] = []
    assert run_due(root, clock, sent.append) == 0  # 7 days before, one minute early
    clock.advance(minutes=1)
    assert run_due(root, clock, sent.append) == 1
    assert run_due(root, clock, sent.append) == 0  # already in the audit log
    clock.advance(days=4)  # 29 May 09:00: lead 3 came
    assert run_due(root, clock, sent.append) == 1
    assert sent == ["1 Frist wartet"] * 2


def test_catch_up_sends_one_push_and_missed_deadline_none(root: Path) -> None:
    confirmed_note(root)
    clock = FakeClock(datetime(2030, 6, 1, 10, 0, tzinfo=UTC))  # host was down, all leads due
    sent: list[str] = []
    assert run_due(root, clock, sent.append) == 1
    assert run_due(root, clock, sent.append) == 0
    clock.advance(days=2)
    assert run_due(root, clock, sent.append) == 0  # deadline missed: never pushed


def test_failed_push_is_retried(root: Path) -> None:
    confirmed_note(root)
    clock = FakeClock(datetime(2030, 5, 25, 10, 0, tzinfo=UTC))

    def down(text: str) -> None:
        raise NotifyError("down")

    assert run_due(root, clock, down) == 0
    sent: list[str] = []
    assert run_due(root, clock, sent.append) == 1


def test_draft_note_never_pushes(root: Path) -> None:
    ingest(root, PrivacyClass.ALLOW, FakeBackend({doc_id(): EXTRACTED}))  # draft with deadline
    sent: list[str] = []
    assert run_due(root, FakeClock(datetime(2030, 6, 1, 10, 0, tzinfo=UTC)), sent.append) == 0


def test_ntfy_sender_posts_to_topic() -> None:
    seen: dict[str, Any] = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            seen["path"] = self.path
            seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    ntfy_sender(f"http://127.0.0.1:{srv.server_port}", "lifeos")("1 Frist wartet")
    srv.server_close()
    assert seen == {"path": "/lifeos", "body": b"1 Frist wartet"}
    with pytest.raises(NotifyError):
        ntfy_sender("http://127.0.0.1:1", "lifeos", timeout=1)("x")
    with pytest.raises(ValueError):
        ntfy_sender("file:///etc", "lifeos")


# --- images -----------------------------------------------------------------------------


def photo_with_gps(fmt: str) -> bytes:
    img = Image.new("RGB", (64, 48), (200, 180, 160))
    exif = Image.Exif()
    exif[0x010F] = "FakeCam"
    exif[0x8825] = {1: "N", 2: (52.0, 31.0, 12.0), 3: "E", 4: (13.0, 24.0, 36.0)}
    out = io.BytesIO()
    if fmt == "HEIF":
        pillow_heif.register_heif_opener()
    img.save(out, fmt, exif=exif)
    return out.getvalue()


@pytest.mark.parametrize(
    ("fmt", "ext", "stored"), [("JPEG", "jpg", "jpg"), ("HEIF", "heic", "png")]
)
def test_exif_gps_is_stripped_and_heic_becomes_png(
    root: Path, fmt: str, ext: str, stored: str
) -> None:
    data = photo_with_gps(fmt)
    assert detect_ext(data) == ext
    with Image.open(io.BytesIO(data)) as src:  # the input really carries GPS
        assert src.getexif().get_ifd(0x8825)
    res = ingest_upload(root, data, PrivacyClass.LOCAL, ocr=ocr_stub(), clock=FakeClock())
    assert res.ext == stored
    (path,) = (root / "files").glob("*")
    assert path.suffix == f".{stored}"
    blob = path.read_bytes()
    assert b"FakeCam" not in blob and b"Exif" not in blob
    with Image.open(path) as out:
        assert not out.getexif() and not out.getexif().get_ifd(0x8825)
        assert out.size == (64, 48)


def test_garbage_image_is_rejected(root: Path) -> None:
    with pytest.raises(UnsupportedFile):
        ingest_upload(root, b"\xff\xd8\xff" + b"not a jpeg", PrivacyClass.LOCAL, ocr=ocr_stub())

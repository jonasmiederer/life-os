"""WSGI app: login, upload form, review and confirm, image serving. stdlib only.

Shortcut: wsgiref server is single threaded and has no TLS. HTTPS and the VPN sit in front
(D2). Upgrade to a real server when more than one user or a public path is needed.
"""

from __future__ import annotations

import email.policy
import os
import re
from collections.abc import Callable, Iterable
from datetime import timedelta
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from core.clock import SystemClock
from core.gateway.interface import Backend, PrivacyClass
from core.ingest import MAX_UPLOAD_BYTES, OcrFn, UnsupportedFile, ingest_upload
from core.log import log_event
from core.notify import Sender, run_due
from core.ocr import OcrError, TesseractMissing, ocr_file
from core.review import ReviewError, confirm, list_drafts, load_draft
from core.web import pages
from core.web.auth import LoginLimiter, Sessions, verify_password

COOKIE = "lifeos_session"
_FILE_RE = re.compile(r"^/files/([0-9a-f]{64})\.(png|jpg|pdf)$")
_TYPES = {"png": "image/png", "jpg": "image/jpeg", "pdf": "application/pdf"}
_CLASSES = {"allow": PrivacyClass.ALLOW, "block": PrivacyClass.BLOCK, "local": PrivacyClass.LOCAL}
_HEADERS = [
    ("Content-Security-Policy", "default-src 'self'; form-action 'self'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
]
_REVIEW_RE = re.compile(r"^/review/([0-9a-z_-]+)(/confirm)?$")
_Response = tuple[str, list[tuple[str, str]], bytes]


def parse_multipart(content_type: str, body: bytes) -> dict[str, bytes]:
    """Return name -> bytes for every part. Raises ValueError on a malformed body."""
    if not content_type.startswith("multipart/form-data"):
        raise ValueError("not multipart")
    msg = BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body
    )
    if not msg.is_multipart():
        raise ValueError("not multipart")
    out: dict[str, bytes] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        if isinstance(name, str) and isinstance(payload, bytes):
            out[name] = payload
    return out


class WebApp:
    def __init__(
        self,
        root: Path,
        password_hash: str,
        *,
        backend: Backend | None = None,
        ocr: OcrFn = ocr_file,
        clock: Any = None,
        idle_minutes: int = 30,
        secure_cookie: bool = True,
        send: Sender | None = None,
    ) -> None:
        self.root = root
        self._hash = password_hash
        self._backend = backend
        self._ocr = ocr
        self._clock = clock or SystemClock()
        self._sessions = Sessions(self._clock, timedelta(minutes=idle_minutes))
        self._limiter = LoginLimiter(self._clock)
        self._secure = secure_cookie
        self._send = send

    # --- plumbing -------------------------------------------------------------------------
    def __call__(
        self, environ: dict[str, Any], start_response: Callable[..., Any]
    ) -> Iterable[bytes]:
        try:
            status, headers, body = self._route(environ)
        except Exception as exc:  # noqa: BLE001 - last resort: fixed message, class name only
            log_event("web.error", code=type(exc).__name__[:40])
            status, headers, body = self._html(
                "500 Internal Server Error", pages.error_page("Interner Fehler.")
            )
        start_response(status, [*_HEADERS, *headers, ("Content-Length", str(len(body)))])
        return [body]

    @staticmethod
    def _html(status: str, body: bytes, extra: list[tuple[str, str]] | None = None) -> _Response:
        return status, [("Content-Type", "text/html; charset=utf-8"), *(extra or [])], body

    @staticmethod
    def _redirect(where: str, extra: list[tuple[str, str]] | None = None) -> _Response:
        return "303 See Other", [("Location", where), *(extra or [])], b""

    def _token(self, environ: dict[str, Any]) -> str | None:
        for chunk in str(environ.get("HTTP_COOKIE", "")).split(";"):
            name, _, value = chunk.strip().partition("=")
            if name == COOKIE:
                return value
        return None

    def _cookie(self, value: str, max_age: int | None = None) -> tuple[str, str]:
        attrs = f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict"
        attrs += "; Secure" if self._secure else ""
        attrs += f"; Max-Age={max_age}" if max_age is not None else ""
        return ("Set-Cookie", attrs)

    def _body(self, environ: dict[str, Any]) -> bytes:
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_UPLOAD_BYTES + 4096:
            raise UnsupportedFile("body too large")
        return environ["wsgi.input"].read(length)  # type: ignore[no-any-return]

    # --- routes ---------------------------------------------------------------------------
    def _route(self, environ: dict[str, Any]) -> _Response:
        method, path = environ["REQUEST_METHOD"], environ["PATH_INFO"]
        if path == "/style.css" and method == "GET":
            return "200 OK", [("Content-Type", "text/css")], pages.STYLE_CSS
        if path == "/login":
            return (
                self._login(environ)
                if method == "POST"
                else self._html("200 OK", pages.login_page())
            )
        token = self._token(environ)
        session = self._sessions.get(token)
        if session is None:
            return self._redirect("/login")
        if method == "GET" and path == "/":
            return self._html("200 OK", pages.upload_page(session.csrf))
        if path == "/review" and method == "GET":
            return self._html("200 OK", pages.review_list_page(list_drafts(self.root)))
        rm = _REVIEW_RE.match(path)
        if rm and method == "GET" and not rm.group(2):
            return self._review_form(rm.group(1), session.csrf)
        if rm and method == "POST" and rm.group(2):
            return self._confirm(environ, rm.group(1), session.csrf)
        if method == "GET":
            m = _FILE_RE.match(path)
            if m:
                return self._serve_file(*m.groups())
        if method == "POST" and path == "/logout":
            self._sessions.drop(token)
            return self._redirect("/login", [self._cookie("", 0)])
        if method == "POST" and path == "/upload":
            return self._upload(environ, session.csrf)
        return self._html("404 Not Found", pages.error_page("Nicht gefunden."))

    def _login(self, environ: dict[str, Any]) -> _Response:
        if self._limiter.locked():
            return self._html(
                "429 Too Many Requests", pages.login_page("Zu viele Versuche. Bitte warten.")
            )
        form = parse_qs(self._body(environ).decode("utf-8", "replace"))
        password = form.get("password", [""])[0]
        if not verify_password(password, self._hash):
            self._limiter.fail()
            log_event("web.login", ok=False)
            return self._html("401 Unauthorized", pages.login_page("Falsches Passwort."))
        self._limiter.reset()
        token, _ = self._sessions.create()
        log_event("web.login", ok=True)
        return self._redirect("/", [self._cookie(token)])

    def _serve_file(self, sha: str, ext: str) -> _Response:
        path = self.root / "files" / f"{sha}.{ext}"
        if not path.is_file():
            return self._html("404 Not Found", pages.error_page("Nicht gefunden."))
        return (
            "200 OK",
            [("Content-Type", _TYPES[ext]), ("Content-Disposition", "inline")],
            path.read_bytes(),
        )

    def _review_form(
        self, slug: str, csrf: str, error: str = "", status: str = "200 OK"
    ) -> _Response:
        try:
            draft = load_draft(self.root, slug)
        except ReviewError:
            return self._html("404 Not Found", pages.error_page("Nicht gefunden."))
        return self._html(
            status, pages.review_page(csrf, slug, draft.meta, draft.file, error, draft.text)
        )

    def _confirm(self, environ: dict[str, Any], slug: str, csrf: str) -> _Response:
        raw = parse_qs(self._body(environ).decode("utf-8", "replace"))
        form = {k: v[0] for k, v in raw.items()}
        if form.get("csrf", "") != csrf:
            return self._html(
                "403 Forbidden", pages.error_page("Sitzung ungültig. Bitte neu laden.")
            )
        try:
            confirm(
                self.root, slug,
                doc_type=form.get("doc_type", ""), sender=form.get("sender", ""),
                doc_date=form.get("doc_date", ""), amount=form.get("amount", ""),
                deadline=form.get("deadline", ""), clock=self._clock,
            )  # fmt: skip
        except ReviewError as exc:
            return self._review_form(slug, csrf, str(exc), "400 Bad Request")
        if self._send is not None:
            run_due(self.root, self._clock, self._send)
        return self._html("200 OK", pages.confirmed_page(bool(form.get("deadline", "").strip())))

    def _upload(self, environ: dict[str, Any], csrf: str) -> _Response:
        try:
            form = parse_multipart(environ.get("CONTENT_TYPE", ""), self._body(environ))
        except (ValueError, UnsupportedFile):
            return self._html("400 Bad Request", pages.error_page("Ungültige Anfrage."))
        if form.get("csrf", b"").decode("utf-8", "replace") != csrf:
            return self._html(
                "403 Forbidden", pages.error_page("Sitzung ungültig. Bitte neu laden.")
            )
        choice = form.get("class", b"").decode("utf-8", "replace")
        if choice not in _CLASSES:
            return self._html(
                "400 Bad Request", pages.upload_page(csrf, "Bitte die Datenklasse wählen.")
            )
        # "nur lokal" always wins over the class (D21).
        klass = PrivacyClass.LOCAL if form.get("local_only") else _CLASSES[choice]
        try:
            res = ingest_upload(
                self.root, form.get("file", b""), klass,
                backend=self._backend, ocr=self._ocr, clock=self._clock,
            )  # fmt: skip
        except UnsupportedFile:
            return self._html(
                "400 Bad Request", pages.upload_page(csrf, "Nur PNG, JPEG oder PDF bis 25 MB.")
            )
        except TesseractMissing:
            return self._html(
                "503 Service Unavailable", pages.error_page("Texterkennung ist nicht installiert.")
            )
        except OcrError:
            return self._html(
                "422 Unprocessable Entity", pages.error_page("Texterkennung fehlgeschlagen.")
            )
        return self._html(
            "200 OK", pages.done_page(res.slug, res.sha256, res.ext, res.duplicate, res.quarantined)
        )


def password_hash_from_env(env: dict[str, str] | None = None) -> str:
    """Hash from LIFEOS_PASSWORD_HASH_FILE (a secret file) or LIFEOS_PASSWORD_HASH. Fails closed."""
    env = dict(os.environ) if env is None else env
    if env.get("LIFEOS_PASSWORD_HASH_FILE"):
        return Path(env["LIFEOS_PASSWORD_HASH_FILE"]).read_text(encoding="utf-8").strip()
    if env.get("LIFEOS_PASSWORD_HASH"):
        return env["LIFEOS_PASSWORD_HASH"].strip()
    raise RuntimeError("no password hash: set LIFEOS_PASSWORD_HASH_FILE")

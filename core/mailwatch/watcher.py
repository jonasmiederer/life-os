"""One watcher pass: fetch from INBOX, decide, write, move. Logs carry counts and codes only."""

from __future__ import annotations

import hashlib
import imaplib
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.log import log_event
from core.mailwatch import auth, inbox, mime
from core.mailwatch.config import MailConfig, read_password

MAX_PER_RUN = 100
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")

Notifier = Callable[[str], None]


class OpsError(Exception):
    """Needs the owner. `code` is a short reason code, never mail content or credentials."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class RunResult:
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    left: int = 0
    status: str = "ok"


class Watcher:
    def __init__(
        self,
        cfg: MailConfig,
        *,
        notify: Notifier | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.cfg = cfg
        self._notify = notify
        self._now = now
        # Default context verifies the certificate chain and the host name. No way to turn it off.
        self._ctx = ssl_context or ssl.create_default_context()
        self.state = inbox.State(cfg.inbox)

    # ---- notifications -------------------------------------------------
    def _push(self, text: str) -> bool:
        if self._notify is None:
            return False
        try:
            self._notify(text)
        except Exception:  # noqa: BLE001 - ntfy trouble must not stop the watcher
            log_event("mailwatch.notify", code="ntfy_failed")
            return False
        return True

    def _alert_once_a_day(self, key: str, text: str, today: str) -> None:
        if self.state.data[key] != today and self._push(text):
            self.state.data[key] = today

    def _flush_reject_notice(self, today: str) -> None:
        counts: dict[str, int] = self.state.data["reject_counts"]
        past = [d for d in counts if d < today]
        total = sum(counts[d] for d in past)
        if total and self._push(f"{total} Mail abgelehnt"):
            for d in past:
                del counts[d]
        elif not total:
            for d in past:
                counts.pop(d, None)

    # ---- one pass ------------------------------------------------------
    def run_once(self) -> RunResult:
        now = self._now()
        today = now.strftime("%Y-%m-%d")
        st = self.state.data
        if st["accept_day"] != today:
            st["accept_day"], st["accepted"] = today, 0
        self._flush_reject_notice(today)
        if st["next_try"] and now < datetime.fromisoformat(st["next_try"]):
            self.state.save()
            return RunResult(status="backoff")
        try:
            result = self._session(now, today)
        except OpsError as exc:
            self._on_ops_error(exc, now, today)
            self.state.save()
            if exc.code == "no_move":
                raise
            return RunResult(status=exc.code)
        st["login_failures"], st["next_try"] = 0, ""
        self.state.save()
        log_event(
            "mailwatch.run",
            count=result.accepted,
            status=result.status,
            kind="accepted",
        )
        return result

    def _on_ops_error(self, exc: OpsError, now: datetime, today: str) -> None:
        log_event("mailwatch.ops", code=exc.code)
        st = self.state.data
        if exc.code == "no_move":
            self._alert_once_a_day("login_alert_day", "Mail-Watcher: IMAP MOVE fehlt", today)
            return
        st["login_failures"] += 1
        wait = min(
            self.cfg.backoff_floor_seconds * 2 ** (st["login_failures"] - 1),
            self.cfg.backoff_max_seconds,
        )
        st["next_try"] = (now + timedelta(seconds=wait)).isoformat()
        self._alert_once_a_day("login_alert_day", "Mail-Watcher: Verbindung fehlgeschlagen", today)

    def _session(self, now: datetime, today: str) -> RunResult:
        password = read_password(self.cfg.password_file)
        try:
            conn = imaplib.IMAP4_SSL(
                self.cfg.host, self.cfg.port, ssl_context=self._ctx, timeout=30
            )
        except ssl.SSLError:
            raise OpsError("tls") from None
        except OSError:
            raise OpsError("connect") from None
        try:
            return self._talk(conn, password, now, today)
        except (imaplib.IMAP4.error, OSError):
            raise OpsError("imap") from None
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001, S110 - connection may already be gone
                pass

    def _talk(self, conn: imaplib.IMAP4_SSL, password: str, now: datetime, today: str) -> RunResult:
        try:
            conn.login(self.cfg.user, password)
        except imaplib.IMAP4.error:
            raise OpsError("login") from None
        typ, caps = conn.capability()
        tokens = b" ".join(c for c in caps if isinstance(c, bytes)).upper().split()
        if typ != "OK" or b"MOVE" not in tokens:
            raise OpsError("no_move")
        typ, _ = conn.select(f'"{self.cfg.folder}"')
        if typ != "OK":
            raise OpsError("select")
        typ, found = conn.uid("SEARCH", "ALL")
        uids = found[0].split() if typ == "OK" and found and isinstance(found[0], bytes) else []
        result = RunResult()
        for i, uid in enumerate(uids):
            if i >= MAX_PER_RUN or self.state.data["accepted"] >= self.cfg.daily_cap:
                result.left = len(uids) - i
                if self.state.data["accepted"] >= self.cfg.daily_cap:
                    self._alert_once_a_day("cap_alert_day", "Mail-Tageslimit erreicht", today)
                    result.status = "cap"
                break
            self._one(conn, uid.decode("ascii"), now, today, result)
        return result

    def _one(
        self, conn: imaplib.IMAP4_SSL, uid: str, now: datetime, today: str, result: RunResult
    ) -> None:
        folder, code = self._decide(conn, uid, now, result)
        if folder == self.cfg.rejected:
            counts = self.state.data["reject_counts"]
            counts[today] = counts.get(today, 0) + 1
            result.rejected += 1
            log_event("mailwatch.reject", code=code)
        typ, _ = conn.uid("MOVE", uid, f'"{folder}"')
        if typ != "OK":
            raise OpsError("move_failed")
        self.state.save()

    def _decide(
        self, conn: imaplib.IMAP4_SSL, uid: str, now: datetime, result: RunResult
    ) -> tuple[str, str]:
        typ, data = conn.uid("FETCH", uid, "(RFC822.SIZE)")
        m = (
            _SIZE.search(b" ".join(d for d in data if isinstance(d, bytes)))
            if typ == "OK"
            else None
        )
        if m is None or int(m.group(1)) > self.cfg.max_bytes:
            return self.cfg.rejected, "size"
        typ, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        raw = data[0][1] if typ == "OK" and data and isinstance(data[0], tuple) else None
        if not isinstance(raw, bytes) or len(raw) > self.cfg.max_bytes:
            return self.cfg.rejected, "size"
        mail_id = hashlib.sha256(raw).hexdigest()
        if self.state.seen(mail_id):
            result.duplicates += 1
            log_event("mailwatch.duplicate", sha256=mail_id)
            return self.cfg.processed, ""
        try:
            msg = mime.parse(raw)
            struct = mime.structure(msg, max_parts=self.cfg.max_parts, max_depth=self.cfg.max_depth)
        except mime.MimeReject as exc:
            return self.cfg.rejected, exc.code
        if not mime.addressed_to(msg, self.cfg.ingest_address):
            return self.cfg.rejected, "to_not_ingest"
        verdict = auth.check(
            msg,
            authserv_id=self.cfg.authserv_id,
            allowed_from=self.cfg.allowed_from,
            allowed_domains=self.cfg.allowed_domains,
        )
        if isinstance(verdict, auth.AuthReject):
            return self.cfg.rejected, verdict.code
        inbox.write_pair(
            self.cfg.inbox,
            mail_id,
            raw,
            {
                "v": inbox.SIDECAR_VERSION,
                "id": mail_id,
                "sha256": mail_id,
                "size": len(raw),
                "received_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "plus_tag": mime.plus_tag(msg, self.cfg.tag_header),
                "auth": {
                    "dkim": verdict.dkim,
                    "dmarc": verdict.dmarc,
                    "spf": verdict.spf,
                    "from_domain": verdict.from_domain,
                },
                "message_id": struct.message_id,
                "attachments_dropped": struct.attachments_dropped,
            },
        )
        self.state.add_seen(mail_id)
        self.state.data["accepted"] += 1
        result.accepted += 1
        log_event("mailwatch.accept", sha256=mail_id)
        return self.cfg.processed, ""

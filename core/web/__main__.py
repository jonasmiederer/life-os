"""`python -m core.web serve` runs the UI. `python -m core.web hash-password` prints a hash."""

from __future__ import annotations

import getpass
import os
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

from core.clock import SystemClock
from core.config import load_config
from core.datadir import init_data_dir
from core.gateway.interface import Backend
from core.gateway.kiro import KiroBackend, KiroConfig
from core.log import log_event
from core.notify import Sender, ntfy_sender, run_due
from core.web.app import WebApp, password_hash_from_env
from core.web.auth import hash_password


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """No access log: paths and client addresses stay out of logs."""


DEFAULT_KEY_FILE = "~/.config/life-os/kiro_api_key"


def build_backend(env: Mapping[str, str] | None = None) -> Backend | None:
    """Kiro backend when a key and a pinned model exist, else None (fail closed).

    The key comes from KIRO_API_KEY or the file named by LIFEOS_KIRO_KEY_FILE (default
    ~/.config/life-os/kiro_api_key). KiroBackend reads the key from the process env, so a
    file key is placed there. The key is never logged. The model must be pinned:
    LIFEOS_KIRO_MODEL.
    """
    env = dict(os.environ) if env is None else env
    key = env.get("KIRO_API_KEY", "").strip()
    if not key:
        path = Path(env.get("LIFEOS_KIRO_KEY_FILE") or DEFAULT_KEY_FILE).expanduser()
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
    model = env.get("LIFEOS_KIRO_MODEL", "").strip()
    if not key or not model or model.lower() == "auto":
        log_event("backend.none", code="no_key" if not key else "no_model")
        return None
    os.environ["KIRO_API_KEY"] = key
    log_event("backend.selected", kind="kiro")
    return KiroBackend(KiroConfig(model=model))


def _reminder_loop(root: Path, send: Sender, every: int = 300) -> None:
    clock = SystemClock()
    while True:
        try:
            run_due(root, clock, send)
        except Exception as exc:  # noqa: BLE001 - the loop must survive; class name only
            log_event("notify.loop", code=type(exc).__name__[:40])
        time.sleep(every)


def main(argv: list[str]) -> int:
    if argv[:1] == ["hash-password"]:
        print(hash_password(getpass.getpass("Password: ")))
        return 0
    if argv[:1] != ["serve"]:
        print("usage: python -m core.web serve|hash-password", file=sys.stderr)
        return 2
    cfg = load_config()
    root = cfg.data_dir
    init_data_dir(root)
    send = ntfy_sender(cfg.ntfy_url, os.environ.get("LIFEOS_NTFY_TOPIC", "lifeos"))
    threading.Thread(target=_reminder_loop, args=(root, send), daemon=True).start()
    backend = build_backend()
    app = WebApp(
        root,
        password_hash_from_env(),
        backend=backend,
        idle_minutes=int(os.environ.get("LIFEOS_SESSION_MINUTES", "30")),
        secure_cookie=os.environ.get("LIFEOS_INSECURE_COOKIE") != "1",
        send=send,
    )
    port = int(os.environ.get("LIFEOS_WEB_PORT", "8080"))
    with make_server("0.0.0.0", port, app, handler_class=_Quiet) as server:  # noqa: S104
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

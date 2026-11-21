"""`python -m core.web serve` runs the UI. `python -m core.web hash-password` prints a hash."""

from __future__ import annotations

import getpass
import os
import sys
from wsgiref.simple_server import WSGIRequestHandler, make_server

from core.config import load_config
from core.datadir import init_data_dir
from core.web.app import WebApp, password_hash_from_env
from core.web.auth import hash_password


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """No access log: paths and client addresses stay out of logs."""


def main(argv: list[str]) -> int:
    if argv[:1] == ["hash-password"]:
        print(hash_password(getpass.getpass("Password: ")))
        return 0
    if argv[:1] != ["serve"]:
        print("usage: python -m core.web serve|hash-password", file=sys.stderr)
        return 2
    root = load_config().data_dir
    init_data_dir(root)
    # Backend stays None until the gateway work item wires one in: no cloud call is possible.
    app = WebApp(
        root,
        password_hash_from_env(),
        idle_minutes=int(os.environ.get("LIFEOS_SESSION_MINUTES", "30")),
        secure_cookie=os.environ.get("LIFEOS_INSECURE_COOKIE") != "1",
    )
    port = int(os.environ.get("LIFEOS_WEB_PORT", "8080"))
    with make_server("0.0.0.0", port, app, handler_class=_Quiet) as server:  # noqa: S104
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

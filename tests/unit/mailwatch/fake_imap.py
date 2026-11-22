"""Tiny in-test IMAP server over TLS. Subset: CAPABILITY, LOGIN, SELECT, UID SEARCH/FETCH/MOVE."""

from __future__ import annotations

import socket
import socketserver
import ssl
import threading
from pathlib import Path


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        srv = self.server
        self._send("* OK fake ready")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            tag, _, rest = line.decode("ascii", "replace").strip().partition(" ")
            cmd, _, args = rest.partition(" ")
            cmd = cmd.upper()
            srv.commands.append(cmd)
            if cmd == "CAPABILITY":
                move = " MOVE" if srv.move else ""
                self._send(f"* CAPABILITY IMAP4rev1{move}")
                self._send(f"{tag} OK done")
            elif cmd == "LOGIN":
                srv.logins += 1
                if srv.login_ok:
                    self._send(f"{tag} OK logged in")
                else:
                    self._send(f"{tag} NO [AUTHENTICATIONFAILED] bad")
            elif cmd == "SELECT":
                srv.selects.append(args.strip('"'))
                srv.selected = args.strip('"')
                self._send(f"* {len(srv.boxes[srv.selected])} EXISTS")
                self._send(f"{tag} OK [READ-WRITE] selected")
            elif cmd == "UID":
                self._uid(tag, args)
            elif cmd == "LOGOUT":
                self._send("* BYE")
                self._send(f"{tag} OK bye")
                return
            else:
                self._send(f"{tag} BAD unknown")

    def _uid(self, tag: str, args: str) -> None:
        srv = self.server
        sub, _, rest = args.partition(" ")
        sub = sub.upper()
        inbox = srv.boxes[srv.selected]
        if sub == "SEARCH":
            self._send("* SEARCH " + " ".join(str(u) for u, _ in inbox))
            self._send(f"{tag} OK done")
        elif sub == "FETCH":
            uid_s, _, items = rest.partition(" ")
            raw = dict(inbox).get(int(uid_s))
            if raw is None:
                self._send(f"{tag} OK done")
            elif "RFC822.SIZE" in items:
                self._send(f"* 1 FETCH (UID {uid_s} RFC822.SIZE {len(raw)})")
                self._send(f"{tag} OK done")
            else:
                srv.body_fetches += 1
                self.wfile.write(f"* 1 FETCH (UID {uid_s} BODY[] {{{len(raw)}}}\r\n".encode())
                self.wfile.write(raw + b")\r\n")
                self._send(f"{tag} OK done")
        elif sub == "MOVE":
            uid_s, _, folder = rest.partition(" ")
            folder = folder.strip('"')
            srv.moves.append((srv.selected, folder))
            raw = dict(inbox).get(int(uid_s))
            if raw is None or folder not in srv.boxes:
                self._send(f"{tag} NO [TRYCREATE] no such folder")
                return
            srv.boxes[srv.selected] = [(u, r) for u, r in inbox if u != int(uid_s)]
            srv.boxes[folder].append((int(uid_s), raw))
            self._send(f"{tag} OK moved")
        else:
            self._send(f"{tag} BAD unknown")

    def _send(self, text: str) -> None:
        self.wfile.write(text.encode() + b"\r\n")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, ctx: ssl.SSLContext) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.ctx = ctx
        self.boxes: dict[str, list[tuple[int, bytes]]] = {
            "INBOX": [(1, b"private mail, never touched")],
            "Ingest": [],
            "Processed": [],
            "Rejected": [],
        }
        self.commands: list[str] = []
        self.selects: list[str] = []
        self.moves: list[tuple[str, str]] = []
        self.selected = ""
        self.logins = 0
        self.body_fetches = 0
        self.move = True
        self.login_ok = True

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        sock, addr = super().get_request()
        try:
            return self.ctx.wrap_socket(sock, server_side=True), addr
        except ssl.SSLError:
            sock.close()
            raise OSError("handshake failed") from None


class FakeImap:
    def __init__(self, cert: Path, key: Path) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.srv = _Server(ctx)
        self.port: int = self.srv.server_address[1]
        self._t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self._t.start()

    def add(self, raw: bytes) -> int:
        uid = max([u for u, _ in self.srv.boxes["Ingest"]] + [0]) + 1
        self.srv.boxes["Ingest"].append((uid, raw))
        return uid

    def box(self, name: str) -> list[bytes]:
        return [r for _, r in self.srv.boxes[name]]

    def stop(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()

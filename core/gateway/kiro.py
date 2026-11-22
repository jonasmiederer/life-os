"""Kiro backend: kiro-cli headless as a tool-free reader (design 2.13, K0 rules 1-9).

Text only, via stdin in a marked data block. Every call runs in an empty scratch cwd
and a scratch HOME that holds only the reader agent. Nothing from stdout or stderr is
logged or put in an exception: only the exit code and the byte count.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.extract import schema
from core.gateway.interface import (
    AuthExpired,
    BackendUnavailable,
    GatewayRequest,
    GatewayResult,
    InvalidOutput,
    NotSupported,
)

READER_AGENT = Path(__file__).parent / "agents" / "reader.json"
_TOOL_EVENTS = frozenset({"tool_call", "tool_call_update"})


class ToolCallDetected(InvalidOutput):
    """The stream held a tool event. The reader must have none. Never retried."""


@dataclass(frozen=True)
class KiroConfig:
    model: str  # pinned model id; "auto" is refused
    timeout_s: float = 60.0
    kiro_bin: str = "kiro-cli"
    engine_flag: str = "--v2"

    def __post_init__(self) -> None:
        if not self.model or self.model.strip().lower() == "auto":
            raise ValueError("pin a model id, not auto")


def _fence_strip(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _is_tool_event(event: object) -> bool:
    """True if any dict inside the event names a tool call."""
    if isinstance(event, dict):
        if event.get("sessionUpdate") in _TOOL_EVENTS or event.get("type") in _TOOL_EVENTS:
            return True
        return any(_is_tool_event(v) for v in event.values())
    if isinstance(event, list):
        return any(_is_tool_event(v) for v in event)
    return False


def parse_stream(stdout: bytes, exit_code: int) -> dict[str, object]:
    """Return the validated answer from stream-json stdout, or raise a typed error."""
    final: str | None = None
    for raw in stdout.splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if _is_tool_event(event):
            raise ToolCallDetected("tool event in reader stream")
        data = event.get("data")
        if event.get("type") == "runError" and isinstance(data, dict):
            if data.get("stage") == "auth":
                raise AuthExpired("kiro sign-in or key not valid")
        if event.get("type") == "runFinished" and isinstance(data, dict):
            ft = data.get("finalText")
            final = ft if isinstance(ft, str) else None
    if exit_code == 1 and final is None and b'"stage":"auth"' in stdout.replace(b" ", b""):
        raise AuthExpired("kiro sign-in or key not valid")
    if exit_code != 0:
        raise BackendUnavailable(f"kiro-cli exit {exit_code}, {len(stdout)} bytes")
    if final is None:
        raise InvalidOutput("no runFinished text")
    try:
        parsed = json.loads(_fence_strip(final))
    except ValueError:
        raise InvalidOutput("answer is not JSON") from None
    if not isinstance(parsed, dict):
        raise InvalidOutput("answer is not an object")
    try:
        schema.validate(parsed)
    except schema.SchemaError:
        raise InvalidOutput("answer does not match schema") from None
    return parsed


class KiroBackend:
    name = "kiro"

    def __init__(self, config: KiroConfig) -> None:
        self._cfg = config
        self.model_id = config.model

    def run(self, request: GatewayRequest) -> GatewayResult:
        if request.image is not None:
            raise NotSupported("kiro reader is text only")
        try:
            data = self._once(request.text)
        except InvalidOutput as exc:
            if isinstance(exc, ToolCallDetected):
                raise
            data = self._once(request.text)  # one retry
        return GatewayResult(data=data, backend=self.name, model_id=self._cfg.model)

    def _once(self, text: str) -> dict[str, object]:
        # A closing tag inside the text must not end the data block early.
        safe = text.replace("</document>", "<\\/document>")
        stdin = f"<document>\n{safe}\n</document>\n".encode()
        scratch = Path(tempfile.mkdtemp(prefix="lifeos-kiro-"))
        try:
            home, cwd = scratch / "home", scratch / "cwd"
            (home / ".kiro" / "agents").mkdir(parents=True)
            cwd.mkdir()
            shutil.copyfile(READER_AGENT, home / ".kiro" / "agents" / "reader.json")
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
            if "KIRO_API_KEY" in os.environ:
                env["KIRO_API_KEY"] = os.environ["KIRO_API_KEY"]
            cmd = [
                self._cfg.kiro_bin, "chat", "--agent", "reader", self._cfg.engine_flag,
                "--model", self._cfg.model, "--no-interactive", "--output-format", "stream-json",
            ]  # fmt: skip
            try:
                proc = subprocess.Popen(  # noqa: S603
                    cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, start_new_session=True,
                )  # fmt: skip
            except OSError:
                raise BackendUnavailable("kiro-cli cannot start") from None
            try:
                out, err = proc.communicate(stdin, timeout=self._cfg.timeout_s)
            except subprocess.TimeoutExpired:
                _kill(proc)
                raise BackendUnavailable("kiro-cli timeout") from None
            del err  # never read, never logged
            return parse_stream(out, proc.returncode)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)  # holds sessions and logs


def _kill(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, 9)
    except OSError:
        proc.kill()
    proc.communicate()


__all__ = ["KiroBackend", "KiroConfig", "ToolCallDetected", "parse_stream"]

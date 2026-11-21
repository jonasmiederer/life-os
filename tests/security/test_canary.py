"""Canary test: a secret token placed in a document must never reach the logs."""

from __future__ import annotations

import secrets

import pytest

from core.log import LogError, LogSink
from scripts.check_canary import find_canaries

pytestmark = pytest.mark.security


def process_document(doc_id: str, text: str, log: LogSink) -> None:
    """Toy pipeline. It logs ids and sizes only, never content."""
    log.info("document.processed", doc_id=doc_id, chars=len(text))


def test_canary_not_in_logs(log_sink: LogSink) -> None:
    canary = f"CANARY-{secrets.token_hex(8)}"
    process_document("doc-1", f"Brief mit {canary}", log_sink)
    assert not find_canaries(log_sink.text())


def test_log_api_refuses_document_text(log_sink: LogSink) -> None:
    canary = f"CANARY-{secrets.token_hex(8)}"
    with pytest.raises(LogError):
        log_sink.info("oops", content=f"Brief mit {canary}")
    with pytest.raises(LogError):
        log_sink.info("oops", doc_id=f"Brief mit {canary}")
    assert not find_canaries(log_sink.text())


def test_canary_planted_in_log_is_caught(log_sink: LogSink) -> None:
    # The real API refuses free text, so plant the line past it to test the detector.
    canary = f"CANARY-{secrets.token_hex(8)}"
    log_sink.lines.append(f'{{"event": "oops", "content": "Brief mit {canary}"}}')
    assert find_canaries(log_sink.text()) == [canary]

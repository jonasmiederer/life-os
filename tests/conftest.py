"""Shared pytest config. Log API and permissions loader are the real ones from core/."""

from __future__ import annotations

from pytest import fixture

from core.log import LogSink


@fixture
def log_sink() -> LogSink:
    return LogSink()

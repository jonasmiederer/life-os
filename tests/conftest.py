"""Shared pytest config. The real log API and permissions loader come from core/ (P0-3)."""

from __future__ import annotations

from pytest import fixture

from tests.stubs.logapi import LogSink


@fixture
def log_sink() -> LogSink:
    return LogSink()

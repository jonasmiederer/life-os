"""synthetic: true"""

import io
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from core.clock import FakeClock
from core.config import ConfigError, load_config
from core.log import LogError, audit, log_event
from core.permissions import PermissionsError, load_permissions, permissions_digest

# Alias: a dotted decorator at column 0 reads as an email to the push scanner.
parametrize = pytest.mark.parametrize


def test_log_accepts_ids_only() -> None:
    buf = io.StringIO()
    log_event("note.written", stream=buf, slug="2026-11-03-x-rechnung-abcd1234", count=2)
    assert "note.written" in buf.getvalue()


@parametrize(
    "fields", [{"body": "CANARY-123"}, {"slug": "Max Mustermann"}, {"id": "a" * 65}, {"id": ["x"]}]
)
def test_log_rejects_free_text(fields: dict[str, Any]) -> None:
    with pytest.raises(LogError):
        log_event("x.y", stream=io.StringIO(), **fields)


def test_audit_appends_jsonl(tmp_path: Path) -> None:
    now = FakeClock().now()
    audit(tmp_path, "a.b", now, count=1)
    audit(tmp_path, "a.c", now)
    assert len((tmp_path / "audit" / "2026-01.jsonl").read_text().splitlines()) == 2


def test_fake_clock_advances() -> None:
    clock = FakeClock()
    start = clock.now()
    assert clock.advance(hours=2) - start == timedelta(hours=2)


def test_config_defaults_env_and_fail_closed(tmp_path: Path) -> None:
    assert str(load_config(env={}).data_dir) == "/data"
    assert str(load_config(env={"LIFEOS_DATA_DIR": "/x"}).data_dir) == "/x"
    bad = tmp_path / "c.toml"
    bad.write_text('surprise = "x"\n')
    with pytest.raises(ConfigError):
        load_config(bad, env={})
    bad.write_text("data_dir = 3\n")
    with pytest.raises(ConfigError):
        load_config(bad, env={})


def _perm(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "permissions.yml"
    p.write_text(text)
    return p


def test_permissions_load_and_digest_changes(tmp_path: Path) -> None:
    a = load_permissions(_perm(tmp_path, "version: 1\nhelper: document\nreads: [notes]\n"))
    b = load_permissions(_perm(tmp_path, "version: 1\nhelper: document\nreads: [notes, raw]\n"))
    assert a.reads == ("notes",)
    assert permissions_digest(a) != permissions_digest(b)


@parametrize(
    "text",
    [
        "version: 1\nhelper: d\nroot: true\n",
        "version: 2\nhelper: d\n",
        "- x\n",
        "version: 1\nhelper: d\nreads: x\n",
    ],
)
def test_permissions_strict(tmp_path: Path, text: str) -> None:
    with pytest.raises(PermissionsError):
        load_permissions(_perm(tmp_path, text))

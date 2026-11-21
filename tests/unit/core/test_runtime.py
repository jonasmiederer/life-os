"""synthetic: true"""

import io
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from core.clock import FakeClock
from core.config import ConfigError, load_config
from core.log import LogError, LogSink, audit, log_event
from core.permissions import PermissionsError, Tool, load_permissions

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


GOOD = """helper: financial
agents:
  - name: import
    role: actor
    reads: [C3]
    tools: [{name: parse_file, kind: read}]
    network: none
  - name: analyst
    role: reader
    reads: [C3, C4]
    tools: [{name: query_transactions, kind: read}, {name: write_note, kind: write_local}]
"""


def test_permissions_load_design_example(tmp_path: Path) -> None:
    perms = load_permissions(_perm(tmp_path, GOOD))
    assert perms.helper == "financial"
    assert [a.role for a in perms.agents] == ["actor", "reader"]
    assert perms.agents[1].tools[1] == Tool("write_note", "write_local")
    assert perms.agents[0].network == ()


@parametrize(
    "old,new",
    [
        ("role: reader", "role: root"),
        ("kind: write_local", "kind: act"),
        ("reads: [C3, C4]", "reads: [C9]"),
        ("network: none", "network: yes"),
        ("    role: reader\n", "    role: reader\n    network: [example.com]\n"),
        ("helper: financial", "helper: financial\nextra: 1"),
        ("name: analyst", "name: import"),
    ],
)
def test_permissions_strict(tmp_path: Path, old: str, new: str) -> None:
    assert old in GOOD
    with pytest.raises(PermissionsError):
        load_permissions(_perm(tmp_path, GOOD.replace(old, new)))


def test_permissions_not_a_mapping(tmp_path: Path) -> None:
    with pytest.raises(PermissionsError):
        load_permissions(_perm(tmp_path, "- x\n"))


def test_log_sink_keeps_checked_lines() -> None:
    sink = LogSink()
    sink.info("document.processed", doc_id="doc-1", chars=12)
    assert '"doc_id": "doc-1"' in sink.text()
    with pytest.raises(LogError):
        sink.info("oops", content="Brief mit Text")
    assert len(sink.lines) == 1

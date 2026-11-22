from __future__ import annotations

import json
import ssl
import stat
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from core.mailwatch import inbox as inbox_mod
from core.mailwatch.config import ConfigError, MailConfig
from core.mailwatch.watcher import OpsError, Watcher
from tests.unit.mailwatch.conftest import (
    AUTHSERV,
    GOOD_AR,
    PASSWORD,
    SUBJECT,
    Clock,
    build,
)
from tests.unit.mailwatch.fake_imap import FakeImap

Make = Callable[[], Watcher]


def files(cfg: MailConfig) -> list[str]:
    if not cfg.inbox.exists():
        return []
    return sorted(p.name for p in cfg.inbox.iterdir() if not p.name.startswith(".state"))


def test_accept_writes_pair_and_moves(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    raw = build(extra=["Delivered-To: ingest+Tax@example.com"])
    server.add(raw)
    res = make_watcher().run_once()
    assert (res.accepted, res.rejected) == (1, 0)
    import hashlib

    mid = hashlib.sha256(raw).hexdigest()
    assert files(cfg) == [f"{mid}.eml", f"{mid}.json"]
    assert (cfg.inbox / f"{mid}.eml").read_bytes() == raw
    side = json.loads((cfg.inbox / f"{mid}.json").read_text())
    assert set(side) == {
        "v", "id", "sha256", "size", "received_at", "plus_tag", "auth", "message_id",
        "attachments_dropped",
    }  # fmt: skip
    assert side["v"] == 1 and side["id"] == side["sha256"] == mid and side["size"] == len(raw)
    assert side["plus_tag"] == "tax"
    assert side["received_at"] == "2026-11-22T10:00:00Z"
    assert side["auth"] == {
        "dkim": "pass", "dmarc": "pass", "spf": "pass", "from_domain": "example.com",
    }  # fmt: skip
    assert side["message_id"] == "<abc@example.com>" and side["attachments_dropped"] == 0
    for name in files(cfg):
        assert stat.S_IMODE((cfg.inbox / name).stat().st_mode) == 0o600
    assert server.box("Processed") == [raw] and server.box("Ingest") == []
    assert server.box("Rejected") == []


FORGED = "evil.example.org; dkim=pass header.d=example.com; dmarc=pass"
FAIL = f"{AUTHSERV}; dkim=fail header.d=example.com; dmarc=fail"

REJECTS = {
    "no_ar": (dict(ar=[]), "auth_missing"),
    "wrong_authserv_only": (dict(ar=[FORGED]), "auth_missing"),
    "forged_other_id_above_real_fail": (dict(ar=[FORGED, FAIL]), "auth_dkim"),
    "real_fail_on_top_forged_same_id_below": (dict(ar=[FAIL, GOOD_AR]), "auth_dkim"),
    "dkim_domain_not_allowed": (
        dict(ar=[f"{AUTHSERV}; dkim=pass header.d=evil.example.org; dmarc=pass"]),
        "auth_dkim",
    ),
    "dkim_in_comment": (
        dict(ar=[f"{AUTHSERV}; dkim=fail (dkim=pass header.d=example.com); dmarc=pass"]),
        "auth_dkim",
    ),
    "from_not_allowed": (dict(sender="stranger@example.com"), "from_not_allowed"),
    "two_from": (dict(extra=["From: owner@example.com"]), "from_invalid"),
    "no_dkim_method": (dict(ar=[f"{AUTHSERV}; spf=pass smtp.mailfrom=owner@example.com; dmarc=pass"]), "auth_dkim"),  # noqa: E501
    "other_address_of_owner": (dict(to="owner2@example.com"), "to_not_ingest"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(REJECTS))
def test_reject_writes_nothing(
    name: str, server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    kwargs, _code = REJECTS[name]
    raw = build(**kwargs)  # type: ignore[arg-type]
    server.add(raw)
    res = make_watcher().run_once()
    assert (res.accepted, res.rejected) == (0, 1)
    assert files(cfg) == []
    assert server.box("Rejected") == [raw] and server.box("Processed") == []


def test_two_headers_with_our_id_are_rejected_even_if_provider_one_is_on_top(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    server.add(build(ar=[GOOD_AR, FAIL]))
    res = make_watcher().run_once()
    assert (res.accepted, res.rejected) == (0, 1) and files(cfg) == []


def test_dkim_domain_must_align_with_from_or_dmarc_must_pass(
    server: FakeImap, cfg: MailConfig, certs: tuple[Path, Path], clock: Clock
) -> None:
    other = replace(
        cfg,
        allowed_from=frozenset({"owner@example.org"}),
        allowed_domains=frozenset({"example.com"}),
    )
    ctx = ssl.create_default_context(cafile=str(certs[0]))
    ar_no_dmarc = f"{AUTHSERV}; dkim=pass header.d=example.com; dmarc=fail"
    ar_dmarc = f"{AUTHSERV}; dkim=pass header.d=example.com; dmarc=pass"
    server.add(build(sender="owner@example.org", ar=[ar_no_dmarc], body="a"))
    server.add(build(sender="owner@example.org", ar=[ar_dmarc], body="b"))
    res = Watcher(other, now=clock, ssl_context=ctx).run_once()
    assert (res.accepted, res.rejected) == (1, 1)


def test_spf_only_path_is_gone(server: FakeImap, cfg: MailConfig, make_watcher: Make) -> None:
    ar = f"{AUTHSERV}; dkim=fail header.d=example.com; spf=pass smtp.mailfrom=owner@example.com"
    server.add(build(ar=[ar]))
    assert make_watcher().run_once().rejected == 1


def test_boundary_bomb_after_good_auth_stays_small(
    server: FakeImap, cfg: MailConfig, certs: tuple[Path, Path], clock: Clock
) -> None:
    big = replace(cfg, max_bytes=10 * 1024 * 1024)
    mp = 'Content-Type: multipart/mixed; boundary="b"\r\n\r\n' + "--b\n\n" * 1_500_000
    raw = build(multipart=mp)
    assert 7_000_000 < len(raw) < 8_000_000
    server.add(raw)
    ctx = ssl.create_default_context(cafile=str(certs[0]))
    w = Watcher(big, now=clock, ssl_context=ctx)
    tracemalloc.start()
    try:
        res = w.run_once()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert res.rejected == 1 and files(cfg) == []
    assert peak < 100 * 1024 * 1024  # container limit is 256m; the old tree needed ~500m


def test_unauthenticated_bomb_is_rejected_on_headers_alone(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    mp = 'Content-Type: multipart/mixed; boundary="b"\r\n\r\n' + "--b\n\n" * 15_000
    server.add(build(sender="stranger@example.com", multipart=mp))
    assert make_watcher().run_once().rejected == 1
    assert server.srv.body_fetches == 0


def test_partial_fetch_caps_bytes_even_if_size_lies(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    server.srv.size_lie = 10
    server.add(build(body="x" * 150_000))
    assert make_watcher().run_once().rejected == 1
    assert server.srv.max_sent <= cfg.max_bytes + 1


def test_hostile_uid_list_is_filtered(server: FakeImap, make_watcher: Make) -> None:
    server.srv.search_extra = "1:* ) x"
    server.add(build())
    assert make_watcher().run_once().accepted == 1


def test_stalling_server_hits_the_pass_deadline(
    server: FakeImap, cfg: MailConfig, certs: tuple[Path, Path], clock: Clock
) -> None:
    server.srv.stall = 4.0
    ctx = ssl.create_default_context(cafile=str(certs[0]))
    w = Watcher(replace(cfg, pass_seconds=1), now=clock, ssl_context=ctx)
    start = time.monotonic()
    assert w.run_once().status == "deadline"
    assert time.monotonic() - start < 3.5


@pytest.mark.parametrize(
    "bad",
    [
        {"seen": [[1]]},
        {"accepted": "x"},
        {"next_try": "zz"},
        {"next_try": "2026-01-01T00:00:00"},
        {"reject_counts": []},
        {"reject_counts": {"d": "x"}},
        [],
    ],
)
def test_damaged_state_falls_back(
    bad: object, server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    cfg.inbox.mkdir(parents=True)
    (cfg.inbox / ".state").write_text(json.dumps(bad))
    server.add(build())
    assert make_watcher().run_once().accepted == 1


def test_symlinked_tmp_is_not_followed(tmp_path: Path) -> None:
    target = tmp_path / "victim"
    target.write_text("keep")
    (tmp_path / "ab.eml.tmp").symlink_to(target)
    inbox_mod.write_pair(tmp_path, "ab", b"mail", {"v": 1})
    assert target.read_text() == "keep" and (tmp_path / "ab.eml").read_bytes() == b"mail"


def test_non_ascii_password_is_a_config_error(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    cfg.password_file.write_text("p\u00e4ss\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        make_watcher().run_once()


def test_huge_mail_rejected_without_download(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    server.add(build(body="x" * 200_000))
    assert make_watcher().run_once().rejected == 1
    assert server.srv.body_fetches == 0 and files(cfg) == []


def _nested(depth: int) -> bytes:
    inner = "Content-Type: text/plain\r\n\r\nplain\r\n"
    for i in range(depth):
        b = f"b{i}"
        inner = (
            f'Content-Type: multipart/mixed; boundary="{b}"\r\n\r\n--{b}\r\n{inner}\r\n--{b}--\r\n'
        )
    return build(multipart=inner)


def test_depth_bomb_rejected(server: FakeImap, cfg: MailConfig, make_watcher: Make) -> None:
    server.add(_nested(30))
    assert make_watcher().run_once().rejected == 1 and files(cfg) == []


def test_parts_bomb_rejected(server: FakeImap, cfg: MailConfig, make_watcher: Make) -> None:
    parts = "".join(f"--bb\r\nContent-Type: text/plain\r\n\r\np{i}\r\n" for i in range(40))
    mp = 'Content-Type: multipart/mixed; boundary="bb"\r\n\r\n' + parts + "--bb--\r\n"
    server.add(build(multipart=mp))
    assert make_watcher().run_once().rejected == 1 and files(cfg) == []


def test_attachments_counted_not_opened(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    mp = (
        'Content-Type: multipart/mixed; boundary="bb"\r\n\r\n'
        "--bb\r\nContent-Type: text/plain\r\n\r\nhi\r\n"
        "--bb\r\nContent-Type: message/rfc822\r\n\r\nSubject: inner\r\n\r\ninner\r\n"
        "--bb\r\nContent-Type: application/pdf\r\n"
        "Content-Disposition: attachment; filename=a.pdf\r\n\r\n%PDF\r\n"
        "--bb\r\nContent-Type: image/png\r\n\r\nPNG\r\n"
        "--bb--\r\n"
    )
    server.add(build(multipart=mp))
    assert make_watcher().run_once().accepted == 1
    side = json.loads(next(cfg.inbox.glob("*.json")).read_text())
    assert side["attachments_dropped"] == 2


def test_duplicate_bytes_stored_once_even_across_restart(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    raw = build()
    server.add(raw)
    make_watcher().run_once()
    before = files(cfg)
    server.add(raw)
    res = make_watcher().run_once()  # new Watcher: state comes from inbox/.state
    assert res.duplicates == 1 and res.accepted == 0
    assert files(cfg) == before and len(server.box("Processed")) == 2


def test_same_message_id_different_bytes_is_not_a_duplicate(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    server.add(build(body="one"))
    server.add(build(body="two"))
    assert make_watcher().run_once().accepted == 2


@pytest.mark.parametrize(
    ("header", "value", "expected"),
    [
        ("Delivered-To", "ingest+CONTRACT@example.com", "contract"),
        ("Delivered-To", "ingest+local@example.com", "local"),
        ("Delivered-To", "ingest+bank@example.com", None),
        ("Delivered-To", "ingest@example.com", None),
    ],
)
def test_plus_tag(
    header: str,
    value: str,
    expected: str | None,
    server: FakeImap,
    cfg: MailConfig,
    make_watcher: Make,
) -> None:
    server.add(build(extra=[f"{header}: {value}"]))
    make_watcher().run_once()
    assert json.loads(next(cfg.inbox.glob("*.json")).read_text())["plus_tag"] == expected


def test_tag_in_body_or_other_header_is_ignored(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    server.add(build(extra=["Reply-To: ingest+tax@example.com"], body="ingest+tax@example.com"))
    make_watcher().run_once()
    assert json.loads(next(cfg.inbox.glob("*.json")).read_text())["plus_tag"] is None


def test_missing_move_stops_with_ops_error(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    server.srv.move = False
    server.add(build())
    with pytest.raises(OpsError) as exc:
        make_watcher().run_once()
    assert exc.value.code == "no_move"
    assert server.box("Ingest") != [] and files(cfg) == []


def test_login_failure_backs_off(
    server: FakeImap, make_watcher: Make, clock: Clock, pushes: list[str]
) -> None:
    server.srv.login_ok = False
    w = make_watcher()
    assert w.run_once().status == "login"
    assert server.srv.logins == 1 and len(pushes) == 1
    clock.t += timedelta(seconds=299)
    assert w.run_once().status == "backoff"
    assert server.srv.logins == 1  # no tight retry
    clock.t += timedelta(seconds=2)
    assert w.run_once().status == "login" and server.srv.logins == 2
    clock.t += timedelta(seconds=599)  # second wait doubled to 600
    assert w.run_once().status == "backoff"
    assert make_watcher().run_once().status == "backoff"  # persisted across restart
    assert len(pushes) == 1  # one alert per day


def test_bad_certificate_is_refused_before_login(
    server: FakeImap, cfg: MailConfig, clock: Clock
) -> None:
    w = Watcher(cfg, now=clock)  # default context: self-signed cert is not trusted
    assert w.run_once().status == "tls"
    assert server.srv.logins == 0 and server.srv.commands == []


def test_no_log_or_push_contains_subject_or_password(
    server: FakeImap, make_watcher: Make, capsys: pytest.CaptureFixture[str], pushes: list[str]
) -> None:
    server.add(build())
    server.add(build(sender="stranger@example.com"))
    make_watcher().run_once()
    server.srv.login_ok = False
    w = make_watcher()
    w.state.data["next_try"] = ""
    w.run_once()
    out = capsys.readouterr()
    for text in (out.out, out.err, *pushes):
        assert SUBJECT not in text and PASSWORD not in text
        assert "example.com" not in text and "owner" not in text
    assert out.err.strip()  # something was logged


def test_daily_cap_leaves_rest_in_inbox_and_alerts_once(
    server: FakeImap, make_watcher: Make, pushes: list[str]
) -> None:
    for i in range(5):
        server.add(build(body=f"m{i}"))
    res = make_watcher().run_once()
    assert res.accepted == 3 and res.left == 2 and res.status == "cap"
    assert len(server.box("Ingest")) == 2
    make_watcher().run_once()
    assert len([p for p in pushes if "Tageslimit" in p]) == 1


def test_rejects_are_one_push_per_day(
    server: FakeImap, make_watcher: Make, clock: Clock, pushes: list[str]
) -> None:
    for i in range(4):
        server.add(build(sender="stranger@example.com", body=f"r{i}"))
    make_watcher().run_once()
    assert pushes == []  # the day is not over
    clock.t += timedelta(days=1)
    make_watcher().run_once()
    make_watcher().run_once()
    assert pushes == ["4 Mail abgelehnt"]


def test_sidecar_is_written_last(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = inbox_mod._write_atomic

    def boom(path: Path, data: bytes) -> None:
        if path.suffix == ".json":
            raise OSError("disk")
        real(path, data)

    monkeypatch.setattr(inbox_mod, "_write_atomic", boom)
    with pytest.raises(OSError, match="disk"):
        inbox_mod.write_pair(tmp_path, "ab", b"x", {"v": 1})
    assert (tmp_path / "ab.eml").exists() and not (tmp_path / "ab.json").exists()


def test_only_configured_folders_are_touched(
    server: FakeImap, cfg: MailConfig, make_watcher: Make
) -> None:
    server.add(build())
    server.add(build(sender="stranger@example.com"))
    make_watcher().run_once()
    assert server.srv.selects == ["Ingest"]
    assert {m for m in server.srv.moves} == {("Ingest", "Processed"), ("Ingest", "Rejected")}
    assert server.box("INBOX") == [b"private mail, never touched"]
    assert not {"LIST", "LSUB", "EXAMINE", "STATUS"} & set(server.srv.commands)


def test_plus_tag_address_is_accepted_and_tag_is_optional(
    server: FakeImap, make_watcher: Make
) -> None:
    server.add(build(to="Ingest+Tax@example.com", body="a"))
    server.add(build(to="ingest@example.com", body="b"))
    assert make_watcher().run_once().accepted == 2


def test_delivered_to_names_ingest_address_when_to_is_a_list(
    server: FakeImap, make_watcher: Make
) -> None:
    raw = build(to="list@example.org", extra=["Delivered-To: ingest@example.com"])
    server.add(raw)
    assert make_watcher().run_once().accepted == 1

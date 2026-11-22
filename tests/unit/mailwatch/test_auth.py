from __future__ import annotations

import email

import pytest

from core.mailwatch import auth

ID = "mx.example.net"
KW = {
    "authserv_id": ID,
    "allowed_from": frozenset({"owner@example.com"}),
    "allowed_domains": frozenset({"example.com"}),
}


def msg(*ars: str, sender: str = "owner@example.com") -> email.message.Message:
    heads = [f"Authentication-Results: {a}" for a in ars] + [f"From: {sender}"]
    return email.message_from_string("\n".join(heads) + "\n\n")


def code(m: email.message.Message) -> str:
    v = auth.check(m, **KW)  # type: ignore[arg-type]
    return v.code if isinstance(v, auth.AuthReject) else "ok"


def test_review_probe_quoted_semicolon_is_rejected() -> None:
    probe = (
        f'{ID}; spf=fail smtp.mailfrom="a; dkim=pass header.d=example.com; dmarc=pass; x"@evil.com;'
        " dkim=fail header.d=evil.com"
    )
    assert code(msg(probe)) == "auth_parse"


@pytest.mark.parametrize(
    "value",
    [
        f'{ID}; dkim=pass header.d=example.com header.i="@example.com"; dmarc=pass',
        f"{ID}; dkim=pass header.d=example.com\\; dmarc=pass",
        f"{ID}; dkim=pass header.d=example.com (unclosed; dmarc=pass",
    ],
)
def test_odd_values_fail_closed(value: str) -> None:
    assert code(msg(value)) == "auth_parse"


def test_two_headers_with_our_id() -> None:
    good = f"{ID}; dkim=pass header.d=example.com; dmarc=pass"
    assert code(msg(good, good)) == "auth_multi"
    assert code(msg(good)) == "ok"


def test_comment_with_semicolon_is_fine() -> None:
    v = f"{ID}; dkim=pass (2048-bit key; unprotected) header.d=example.com; dmarc=pass"
    assert code(msg(v)) == "ok"


def test_forged_only_header_cannot_be_told_apart() -> None:
    # Documented limit: if the provider adds no header, one forged header with our id passes.
    # The owner test in docs/mail-watcher.md checks that the provider always adds its own.
    forged = f"{ID}; dkim=pass header.d=example.com; dmarc=pass"
    assert code(msg(forged)) == "ok"

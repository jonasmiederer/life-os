"""Decide whether a mail may enter (design 2.14, D20).

Only the topmost Authentication-Results header whose authserv-id equals the configured one
counts. Every other Authentication-Results header is ignored, so a header forged by the
sender (above or beside the provider's) has no effect.

shortcut: "aligned" is a suffix match, not the public-suffix organizational domain.
Upgrade when the allowlisted domains are not the owner's own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.message import Message
from email.utils import getaddresses

_COMMENT = re.compile(r"\([^()]*\)")


@dataclass(frozen=True)
class AuthOk:
    dkim: str
    dmarc: str
    spf: str
    from_domain: str


@dataclass(frozen=True)
class AuthReject:
    code: str


def _strip_comments(value: str) -> str:
    prev = None
    while prev != value:
        prev = value
        value = _COMMENT.sub(" ", value)
    return value


def parse_results(value: str, authserv_id: str) -> list[tuple[str, str, dict[str, str]]] | None:
    """Return (method, result, props) triples, or None if the authserv-id differs."""
    parts = _strip_comments(" ".join(value.split())).split(";")
    head = parts[0].split()
    if not head or head[0].lower() != authserv_id:
        return None
    out: list[tuple[str, str, dict[str, str]]] = []
    for seg in parts[1:]:
        tokens = seg.split()
        if not tokens or "=" not in tokens[0]:
            continue
        method, _, result = tokens[0].partition("=")
        props: dict[str, str] = {}
        for tok in tokens[1:]:
            key, eq, val = tok.partition("=")
            if eq:
                props.setdefault(key.lower(), val.strip("\"'").lower())
        out.append((method.lower(), result.lower(), props))
    return out


def _aligned(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def from_address(msg: Message) -> str | None:
    """The single From address, lowercased. None if there is not exactly one."""
    values = [str(v) for v in msg.get_all("From", [])]
    if len(values) != 1:
        return None
    addrs = [a for _, a in getaddresses(values) if a]
    if len(addrs) != 1 or addrs[0].count("@") != 1:
        return None
    return addrs[0].lower()


def check(
    msg: Message,
    *,
    authserv_id: str,
    allowed_from: frozenset[str],
    allowed_domains: frozenset[str],
) -> AuthOk | AuthReject:
    sender = from_address(msg)
    if sender is None:
        return AuthReject("from_invalid")
    if sender not in allowed_from:
        return AuthReject("from_not_allowed")
    from_domain = sender.rsplit("@", 1)[1]

    results = None
    for name, value in msg.items():
        if name.lower() != "authentication-results":
            continue
        results = parse_results(str(value), authserv_id)
        if results is not None:
            break  # topmost match wins
    if results is None:
        return AuthReject("auth_missing")

    dkim_ok = any(
        m == "dkim" and r == "pass" and p.get("header.d", "") in allowed_domains
        for m, r, p in results
    )
    if not dkim_ok:
        return AuthReject("auth_dkim")
    dmarc = next((r for m, r, _ in results if m == "dmarc" and r == "pass"), "")
    spf_aligned = any(
        m == "spf"
        and r == "pass"
        and _aligned(p.get("smtp.mailfrom", "").rsplit("@", 1)[-1], from_domain)
        for m, r, p in results
    )
    if not dmarc and not spf_aligned:
        return AuthReject("auth_align")
    spf = next((r for m, r, _ in results if m == "spf"), "none")
    return AuthOk(dkim="pass", dmarc=dmarc or "none", spf=spf, from_domain=from_domain)

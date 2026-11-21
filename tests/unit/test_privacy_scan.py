"""Privacy scanner: false positives pass, real leaks still fail. Synthetic values only.

Values that look like leaks are built at run time so this file stays clean for the scanner.
"""
# synthetic: true
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("privacy_scan", ROOT / "scripts" / "privacy_scan.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

AT = "@"


def scan(text, deny=None):
    found = []
    ps.scan_text("t", text, deny, found)
    return [rule for _, _, rule in found]


def test_decorators_are_not_emails() -> None:
    for line in ("+" + AT + "pytest.fixture", AT + "pytest.fixture", "-" + AT + "app.route", AT + "x.y.z"):
        assert "email" not in scan(line), line


def test_real_emails_still_fail() -> None:
    for addr in ("alice" + AT + "corp-test.de", "a.b+c" + AT + "mail.corp-test.co.uk"):
        assert "email" in scan(addr)
        assert "email" in scan("+" + addr)  # added line in a diff
        assert "email" in scan("From: <" + addr + ">")


def test_public_placeholder_emails_stay_allowed() -> None:
    assert "email" not in scan("me" + AT + "example.com")
    assert "email" not in scan("x" + AT + "host.invalid")


def test_home_path_and_deny_hit_still_fail() -> None:
    assert "home-path" in scan("/" + "Users/zed/notes")
    assert "deny-list" in scan("has zzsecretzz inside", (["zzsecretzz"], []))


def test_dependabot_trailer_exact_line_only() -> None:
    trailer = "Signed-off-by: dependabot[bot] <support" + AT + "github.com>"
    assert scan(trailer) == []
    assert "email" in scan(trailer + " extra")
    assert "email" in scan("Signed-off-by: someone <support" + AT + "github.com> ")


def identity_findings(monkeypatch, ae, ce, want="owner" + AT + "corp-test.de"):
    monkeypatch.setattr(ps, "expected_identity", lambda: want)
    monkeypatch.setattr(ps, "git", lambda *a, **k: f"abc123 {ae} {ce}\n".encode())
    found = []
    ps.check_identity(["HEAD"], found)
    return [rule for _, _, rule in found]


def test_github_identities_allowed(monkeypatch) -> None:
    web = "noreply" + AT + "github.com"
    bot = "49699333+dependabot[bot]" + AT + "users.noreply.github.com"
    mine = "123+someone" + AT + "users.noreply.github.com"
    assert identity_findings(monkeypatch, bot, web) == []
    assert identity_findings(monkeypatch, mine, web) == []
    assert identity_findings(monkeypatch, "owner" + AT + "corp-test.de", "owner" + AT + "corp-test.de") == []


def test_other_identities_rejected(monkeypatch) -> None:
    for bad in ("stranger" + AT + "corp-test.de", "noreply" + AT + "github.com.evil.de",
                "x" + AT + "users.noreply.github.com.evil.de", "bot" + AT + "github.com"):
        assert identity_findings(monkeypatch, bad, "noreply" + AT + "github.com") == ["author-email-mismatch"]
        assert identity_findings(monkeypatch, "noreply" + AT + "github.com", bad) == ["committer-email-mismatch"]

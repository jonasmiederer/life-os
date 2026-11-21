#!/usr/bin/env python3
"""Privacy scanner for a public repo. Standard library only.

Modes (combine freely):
  --tree      scan every tracked file
  --staged    scan staged changes (pre-commit)
  --history   scan every commit message and patch (git log -p --all)
  --push      read pre-push stdin; scan outgoing commits and check identity
Options:
  --no-denylist   skip the private deny list (CI has no access to it)

Deny list: ~/.config/life-os/denylist.txt (outside the repo, mode 600).
Plain lines are case-insensitive substrings, "re:" lines are regexes.
Expected commit identity: ~/.config/life-os/author-email, else `git config user.email`.
The address is never stored in the repo. It is checked only in commit
metadata (author and committer fields), never in content.
Exit code 1 on any finding. Output never prints the matched text.
"""
import fnmatch
import os
import re
import subprocess
import sys

HOME_CFG = os.path.expanduser("~/.config/life-os")
DENYLIST = os.path.join(HOME_CFG, "denylist.txt")
AUTHOR_FILE = os.path.join(HOME_CFG, "author-email")
ALLOW_FILE = ".privacy-allow"
ZERO = "0" * 40
STRIP = []  # public literals (the GitHub handle) removed before deny-list matching only

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
EMAIL_OK = re.compile(
    r"(@(example\.(com|org|net)|[A-Za-z0-9.-]*\.invalid|localhost|users\.noreply\.github\.com|noreply\.github\.com)$"
    r"|^noreply@|^git@github\.com$)", re.I)
RULES = {
    "iban": re.compile(r"\b[A-Z]{2}(?!00)\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b"),
    "tax-id-or-11-digits": re.compile(r"(?<![\w.-])[1-9]\d{10}(?![\w-])"),
    "phone": re.compile(r"(?<![\w.])(?:\+|00)\d{1,3}[ /-]?\(?\d{2,5}\)?[ /-]?\d{3,}(?:[ /-]?\d+)*"
                        r"|(?<![\w.])0\d{2,5}[ /-]\d{4,}"),
    "home-path": re.compile(r"/(?:Users|home)/(?!(?:<|\$|\{|user\b|name\b|runner\b|example\b|you\b|me\b))[^\s/'\"`]+"),
}
BINARY_EXT = (".png", ".jpg", ".jpeg", ".gif", ".heic", ".pdf", ".webp", ".tif", ".tiff", ".zip", ".gz")


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True)
    if check and r.returncode:
        sys.exit("git failed: " + " ".join(args))
    return r.stdout


def load_allow():
    skip, synth = [], []
    STRIP.clear()
    if os.path.exists(ALLOW_FILE):
        for ln in open(ALLOW_FILE, encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith("path:"):
                skip.append(ln[5:].strip())
            elif ln.startswith("strip:"):
                STRIP.append(ln[6:].strip())
            elif ln.startswith("synthetic:"):
                synth.append(ln[10:].strip())
    return skip, synth


def load_deny():
    if not os.path.exists(DENYLIST):
        sys.exit("deny list missing: create it or pass --no-denylist")
    if os.stat(DENYLIST).st_mode & 0o077:
        sys.exit("deny list must be mode 600")
    subs, regs = [], []
    for ln in open(DENYLIST, encoding="utf-8"):
        ln = ln.rstrip("\n")
        if not ln.strip() or ln.startswith("#"):
            continue
        if ln.startswith("re:"):
            regs.append(re.compile(ln[3:], re.I))
        else:
            subs.append(ln.lower())
    return subs, regs


def matches(globs, path):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def scan_text(label, text, deny, findings):
    load_allow()
    """Record findings as (label, line number, rule). Never the text itself."""
    for n, line in enumerate(text.split("\n"), 1):
        if "privacy-allow" in line:
            continue
        for name, rx in RULES.items():
            if rx.search(line):
                findings.append((label, n, name))
        for m in EMAIL.finditer(line):
            if not EMAIL_OK.search(m.group(0)):
                findings.append((label, n, "email"))
        if deny:
            low = line.lower()
            for lit in STRIP:
                low = low.replace(lit.lower(), "")
                line = re.sub(re.escape(lit), "", line, flags=re.I)
            subs, regs = deny
            if any(s in low for s in subs) or any(r.search(line) for r in regs):
                findings.append((label, n, "deny-list"))


def scan_files(paths, read, deny, findings):
    skip, synth = load_allow()
    for p in paths:
        if matches(skip, p):
            continue
        data = read(p)
        needs_marker = p.startswith(("docs/", "tests/fixtures/")) and not matches(synth, p)
        if p.lower().endswith(BINARY_EXT) or b"\0" in data[:4096]:
            if not matches(synth, p):
                findings.append((p, 0, "binary-needs-allowlist"))
            continue
        text = data.decode("utf-8", "replace")
        if needs_marker and not re.search(r"synthetic:\s*true", text):
            findings.append((p, 0, "missing-synthetic-marker"))
        scan_text(p, text, deny, findings)


def tracked():
    return [p for p in git("ls-files", "-z").decode().split("\0") if p]


def scan_tree(deny, findings):
    scan_files(tracked(), lambda p: open(p, "rb").read(), deny, findings)


def scan_staged(deny, findings):
    names = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0") if p]
    scan_files(names, lambda p: git("show", ":" + p), deny, findings)


def scan_log(log_args, deny, findings):
    """Scan messages and full patches. --format omits author and committer."""
    out = git("log", "-p", "--all" if not log_args else "--no-walk=unsorted", "--format=%x01%H%n%B",
              *log_args, "--", ".", check=True).decode("utf-8", "replace")
    skip, _ = load_allow()
    for chunk in out.split("\x01")[1:]:
        sha, _, body = chunk.partition("\n")
        # drop patch sections of allowlisted paths
        parts = re.split(r"(?m)^(?=diff --git )", body)
        kept = [parts[0]] + [s for s in parts[1:]
                             if not matches(skip, (re.match(r"diff --git a/(\S+)", s) or [None, ""])[1])]
        scan_text("commit " + sha[:10], "".join(kept), deny, findings)


def expected_identity():
    if os.path.exists(AUTHOR_FILE):
        return open(AUTHOR_FILE).read().strip()
    return git("config", "user.email").decode().strip()


def check_identity(revs, findings):
    want = expected_identity()
    if not want:
        sys.exit("no expected identity: set `git config user.email` or ~/.config/life-os/author-email")
    out = git("log", "--format=%H %ae %ce", *revs).decode()
    for ln in out.splitlines():
        sha, ae, ce = ln.split(" ")
        if ae != want:
            findings.append(("commit " + sha[:10], 0, "author-email-mismatch"))
        if ce != want:
            findings.append(("commit " + sha[:10], 0, "committer-email-mismatch"))


def scan_push(deny, findings):
    for ln in sys.stdin.read().splitlines():
        parts = ln.split()
        if len(parts) != 4:
            continue
        _, local_sha, _, remote_sha = parts
        if local_sha == ZERO:
            continue
        revs = [local_sha] if remote_sha == ZERO else [f"{remote_sha}..{local_sha}"]
        if remote_sha == ZERO:
            revs = [local_sha, "--not", "--remotes"]
        shas = git("rev-list", *revs).decode().split()
        for s in shas:
            scan_log([s], deny, findings)
        check_identity(revs, findings)


def main():
    a = sys.argv[1:]
    if not any(x in a for x in ("--tree", "--staged", "--history", "--push")):
        sys.exit(__doc__)
    os.chdir(git("rev-parse", "--show-toplevel").decode().strip())
    deny = None if "--no-denylist" in a else load_deny()
    findings = []
    if "--tree" in a:
        scan_tree(deny, findings)
    if "--staged" in a:
        scan_staged(deny, findings)
    if "--history" in a:
        scan_log([], deny, findings)
        check_identity(["--all"], findings)
    if "--push" in a:
        scan_push(deny, findings)
    for label, n, rule in sorted(set(findings)):
        print(f"PRIVACY {rule}: {label}" + (f":{n}" if n else ""))
    print(f"privacy-scan: {len(set(findings))} finding(s), deny list {'off' if deny is None else 'on'}")
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()

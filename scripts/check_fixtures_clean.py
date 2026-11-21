"""fixtures-clean: fail if any file under a directory holds a real-looking value.

Allowed: reserved example domains, IBANs with check digits 00, no home paths,
and the `synthetic: true` marker in every text file. A PNG or PDF is allowed only with
a `<name>.json` sidecar that carries the marker and the file's sha256 (the sidecar is
itself a text file and gets all text checks).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
IBAN = re.compile(r"\b[A-Z]{2}(\d{2})(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
HOME = re.compile(r"/(?:Users|home)/[^/\s]+")
OK_DOMAINS = {"example.com", "example.org", "example.net"}
SKIP = {".gitkeep"}
BINARY_EXT = {".png", ".pdf"}


def check_binary(p: Path) -> list[str]:
    """A binary is allowed only with a `<name>.json` sidecar: marker plus matching sha256."""
    if p.suffix.lower() not in BINARY_EXT:
        return [f"{p}: binary file, not allowed in fixtures"]
    side = p.with_name(p.name + ".json")
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{p}: binary without readable sidecar {side.name}"]
    if not isinstance(meta, dict) or "synthetic: true" not in str(meta.get("marker", "")):
        return [f"{p}: sidecar missing synthetic marker"]
    if meta.get("sha256") != hashlib.sha256(p.read_bytes()).hexdigest():
        return [f"{p}: sidecar sha256 does not match file"]
    return []


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name in SKIP:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.extend(check_binary(p))
            continue
        if "synthetic: true" not in text:
            findings.append(f"{p}: missing synthetic marker")
        for m in EMAIL.finditer(text):
            if m.group(1).lower() not in OK_DOMAINS:
                findings.append(f"{p}: email domain not reserved")
        for m in IBAN.finditer(text):
            if m.group(1) != "00":
                findings.append(f"{p}: IBAN with real check digits")
        if HOME.search(text):
            findings.append(f"{p}: home path")
    return findings


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("tests/fixtures")
    found = scan(root)
    for f in found:
        print(f"FIXTURE {f}")
    print(f"fixtures-clean: {len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

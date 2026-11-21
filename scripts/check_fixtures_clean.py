"""fixtures-clean: fail if any file under a directory holds a real-looking value.

Allowed: reserved example domains, IBANs with check digits 00, no home paths,
and the `synthetic: true` marker in every text file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
IBAN = re.compile(r"\b[A-Z]{2}(\d{2})(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
HOME = re.compile(r"/(?:Users|home)/[^/\s]+")
OK_DOMAINS = {"example.com", "example.org", "example.net"}
SKIP = {".gitkeep"}


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name in SKIP:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{p}: binary file, not allowed in fixtures")
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

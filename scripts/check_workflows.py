"""workflow-lint SHA check: every `uses:` is pinned to a full SHA, each workflow starts with
`permissions: {}` and none uses pull_request_target."""

from __future__ import annotations

import re
import sys
from pathlib import Path

USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.M)
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out = []
    for ref in USES.findall(text):
        if not ref.startswith("./") and not PINNED.match(ref):
            out.append(f"{path}: action not pinned by SHA: {ref}")
    if not re.search(r"^permissions:\s*\{\}\s*$", text, re.M):
        out.append(f"{path}: missing top-level `permissions: {{}}`")
    if "pull_request_target" in text:
        out.append(f"{path}: pull_request_target is not allowed")
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(".github/workflows")
    found = [f for p in sorted(root.glob("*.yml")) for f in check(p)]
    for f in found:
        print(f"WORKFLOW {f}")
    print(f"workflow-check: {len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

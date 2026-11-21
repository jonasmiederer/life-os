"""canary check: fail if a canary token shows up in a log or any output file."""

from __future__ import annotations

import re
import sys
from pathlib import Path

CANARY = re.compile(r"CANARY-[0-9a-f]{16}")


def find_canaries(text: str) -> list[str]:
    return CANARY.findall(text)


def main(argv: list[str]) -> int:
    hits = 0
    for name in argv[1:]:
        hits += len(find_canaries(Path(name).read_text(encoding="utf-8", errors="replace")))
    print(f"canary: {hits} hit(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

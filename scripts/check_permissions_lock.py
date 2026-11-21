"""Compare helpers/*/permissions.yml with tests/security/permissions.lock.

Exit 1 on any difference. Only a high-risk PR may change the lock (design 2.6).
Usage: check_permissions_lock.py [--root DIR] [--update]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

LOCK = "tests/security/permissions.lock"


def current(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.glob("helpers/*/permissions.yml"))
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--update", action="store_true")
    args = ap.parse_args(argv[1:])
    lock = args.root / LOCK
    now = current(args.root)
    if args.update:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    locked = json.loads(lock.read_text(encoding="utf-8")) if lock.exists() else {}
    bad = [k for k in sorted(set(now) | set(locked)) if now.get(k) != locked.get(k)]
    for k in bad:
        print(f"PERMISSIONS differs from lock: {k}")
    print(f"permissions-lock: {len(bad)} difference(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""`lifeos report --dry-run`: a bug report that is safe to paste. Counts and codes only."""

from __future__ import annotations

import json
import platform
from collections import Counter
from pathlib import Path

from core import __version__
from core.datadir import check_layout, check_no_remote
from core.schema import SCHEMA_VERSION
from core.store import scan


def build_report(root: Path) -> dict[str, object]:
    report: dict[str, object] = {
        "lifeos": __version__,
        "python": platform.python_version(),
        "schema_version": SCHEMA_VERSION,
        "data_dir_present": root.is_dir(),
    }
    if root.is_dir():
        bad = scan(root, move=False)
        codes = Counter(c.split(":")[0] for v in bad.values() for c in v)
        report.update(
            layout_missing=len(check_layout(root)),
            notes=len(list((root / "notes").glob("*.md"))),
            in_review=len(list((root / "review").glob("*.reason.json"))),
            invalid_now=len(bad),
            reason_codes=dict(sorted(codes.items())),
        )
        try:
            check_no_remote(root)
            report["no_remote_guard"] = "ok"
        except Exception:
            report["no_remote_guard"] = "fail"
    return report


def format_report(root: Path) -> str:
    return json.dumps(build_report(root), indent=2, sort_keys=True)

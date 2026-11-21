"""`lifeos smoke`: one synthetic letter and one .eml through the validate path. No OCR."""

from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path

from core.datadir import check_layout, check_no_remote
from core.store import scan
from core.synthetic import populate, populate_invalid


def run_smoke(ntfy_url: str | None = None) -> list[str]:
    """Return failure messages. Empty list means pass. Uses a scratch dir, never the real data."""
    fails: list[str] = []
    with tempfile.TemporaryDirectory(prefix="lifeos-smoke-") as tmp:
        root = Path(tmp) / "data"
        made = populate(root)
        for name in ("letter", "eml"):
            if made[name][1]:
                fails.append(f"{name} rejected: {made[name][1]}")
        if scan(root, move=False):
            fails.append("valid fixtures failed validate")
        if not populate_invalid(root):
            fails.append("invalid note was accepted")
        elif not list((root / "review").glob("*.reason.json")):
            fails.append("invalid note not in review/")
        if check_layout(root):
            fails.append("layout incomplete")
        try:
            check_no_remote(root)
        except Exception:
            fails.append("no-remote guard failed")
    if ntfy_url and not ntfy_url.startswith(("http://", "https://")):
        fails.append("ntfy url must be http(s)")
    elif ntfy_url:
        try:
            url = ntfy_url.rstrip("/") + "/v1/health"
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310  # nosec B310
                if resp.status != 200:
                    fails.append("ntfy unhealthy")
        except OSError:
            fails.append("ntfy unreachable")
    return fails

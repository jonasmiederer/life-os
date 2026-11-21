"""`lifeos reindex`: delete and rebuild the qmd cache. A thin wrapper, no search features.

The cache lives in <data dir>/.lifeos/qmd and is excluded from backups.
qmd's CLI and cache location are NOT verified (design 2.12). The calls below follow its
README and must be checked in the Phase 1 spike. If qmd is missing, a plain file listing
is written instead (shortcut: grep-grade, slow but correct).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from core.log import log_event

QMD_VERSION = "0.0.0-unverified"  # pin the real version after the spike (review-p0 point 37)
INDEXED = ("notes", "raw", "own")


class ReindexError(RuntimeError):
    pass


def cache_dir(root: Path) -> Path:
    return root / ".lifeos" / "qmd"


def reindex(root: Path) -> str:
    """Returns "qmd" or "listing". Raises ReindexError if qmd is installed but fails."""
    cache = cache_dir(root)
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True)
    qmd = shutil.which("qmd")
    if qmd is None:
        files = sorted(
            p.relative_to(root).as_posix()
            for sub in INDEXED
            for p in (root / sub).rglob("*.md")
            if (root / sub).is_dir()
        )
        (cache / "listing.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
        log_event("reindex.fallback", kind="listing", count=len(files))
        return "listing"
    env = {**os.environ, "XDG_CACHE_HOME": str(cache)}
    steps = [[qmd, "collection", "add", str(root / sub), "--name", sub] for sub in INDEXED]
    steps.append([qmd, "update"])
    for cmd in steps:
        res = subprocess.run(cmd, env=env, capture_output=True, check=False)  # noqa: S603
        if res.returncode != 0:
            log_event("reindex.failed", kind="qmd", code=str(res.returncode))
            raise ReindexError("qmd failed")
    log_event("reindex.done", kind="qmd", ok=True)
    return "qmd"

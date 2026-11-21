"""`lifeos backup` and `lifeos restore --verify` (design 2.11).

restic backs up the whole data dir. The qmd cache is excluded because `reindex` rebuilds it.
The restic repo and password file come from config. There is no default target.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.datadir import DataRepoError, _git, check_layout, check_no_remote
from core.log import log_event
from core.reindex import ReindexError, cache_dir, reindex
from core.store import scan


class BackupError(RuntimeError):
    pass


def _restic(repo: str, pw_file: str, *args: str) -> str:
    if not repo or not pw_file:
        raise BackupError("restic_repo and restic_password_file must be set")
    if not Path(pw_file).is_file():
        raise BackupError("password file not found")
    try:
        res = subprocess.run(  # noqa: S603
            ["restic", "-r", repo, "--password-file", pw_file, *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BackupError("restic is not installed") from exc
    if res.returncode != 0:
        # restic stderr can name paths, so it is not echoed
        raise BackupError(f"restic {args[0]} failed (exit {res.returncode})")
    return res.stdout


def backup(root: Path, repo: str, pw_file: str) -> None:
    if not root.is_dir():
        raise BackupError("data dir not found")
    root = root.resolve()
    _restic(
        repo,
        pw_file,
        "backup",
        "--tag",
        "lifeos",
        "--exclude",
        str(cache_dir(root)),
        "--quiet",
        str(root),
    )
    log_event("backup.done", ok=True)


def restore_verify(repo: str, pw_file: str) -> list[str]:
    """Restore the latest snapshot to a scratch dir, reindex there, validate every note.

    Returns a list of failure codes. Empty means ok. The scratch dir is always removed.
    """
    fails: list[str] = []
    snaps = json.loads(_restic(repo, pw_file, "snapshots", "latest", "--tag", "lifeos", "--json"))
    if not snaps:
        raise BackupError("no snapshot found")
    source = snaps[-1]["paths"][0]
    scratch = Path(tempfile.mkdtemp(prefix="lifeos-restore-"))
    try:
        _restic(repo, pw_file, "restore", f"latest:{source}", "--tag", "lifeos",
                "--target", str(scratch))  # fmt: skip
        fails += [f"layout:{m}" for m in check_layout(scratch)]
        try:
            check_no_remote(scratch)
            _git(scratch, "fsck", "--no-progress")
        except DataRepoError as exc:
            fails.append(f"data-repo:{exc}")
        try:
            reindex(scratch)
        except ReindexError:
            fails.append("reindex:failed")
        for name, codes in scan(scratch, move=False).items():
            fails.append(f"{name}:{','.join(codes)}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    log_event("restore.verify", ok=not fails, count=len(fails))
    return fails

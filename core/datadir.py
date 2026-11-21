"""Data dir layout, data git repo and the no-remote guard (design 2.11, 2.12)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from core.schema import SCHEMA_VERSION

DIRS = ("files", "raw", "notes", "own", "review", "inbox", "candidates", "audit", ".lifeos")
GITIGNORE = "/files/\n/audit/\n/review/\n/inbox/\n/candidates/\n"
IDENTITY = ("lifeos", "lifeos@localhost.invalid")


class DataRepoError(RuntimeError):
    pass


def _git(root: Path, *args: str) -> str:
    # safe.directory: a bind mount can show the data dir root as owned by another uid
    # (seen with podman on macOS). Repo config and hooks are still checked by the guard.
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    res = subprocess.run(  # noqa: S603
        ["git", "-c", f"safe.directory={root}", "-C", str(root), *args],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if res.returncode != 0:
        raise DataRepoError(f"git {args[0]} failed")
    return res.stdout


def check_no_remote(root: Path) -> None:
    """Raise if the data repo can reach any remote. Runs on every commit and in `health`."""
    if not (root / ".git").exists():
        raise DataRepoError("data repo missing")
    if _git(root, "remote").strip():
        raise DataRepoError("data repo has a remote")
    for line in _git(root, "config", "--local", "--list").splitlines():
        key = line.split("=", 1)[0].lower()
        if key.startswith(("remote.", "url.", "branch.", "includeif.", "include.")) or key in {
            "core.hookspath",
            "core.sshcommand",
            "core.fsmonitor",
            "core.gitproxy",
        }:
            raise DataRepoError(f"forbidden git config: {key.split('.')[0]}")
    hooks = root / ".git" / "hooks"
    if hooks.is_dir() and any(not p.name.endswith(".sample") for p in hooks.iterdir()):
        raise DataRepoError("data repo has hooks")


def init_data_dir(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in DIRS:
        (root / name).mkdir(exist_ok=True)
    schema = root / ".lifeos" / "schema.json"
    if not schema.exists():
        schema.write_text(json.dumps({"schema_version": SCHEMA_VERSION}) + "\n")
    if not (root / ".git").exists():
        tmpl = root / ".lifeos" / "empty-template"
        tmpl.mkdir(exist_ok=True)
        _git(root, "init", "-q", "-b", "main", f"--template={tmpl}")
        _git(root, "config", "user.name", IDENTITY[0])
        _git(root, "config", "user.email", IDENTITY[1])
        _git(root, "config", "commit.gpgsign", "false")
        (root / ".gitignore").write_text(GITIGNORE + "/.lifeos/\n")
        for d in ("raw", "notes", "own"):
            (root / d / ".gitkeep").touch()
        commit_data(root, "init data repo")
    check_no_remote(root)


def commit_data(root: Path, message: str) -> bool:
    """Commit raw/, notes/, own/. Message must carry ids only. Returns True if a commit was made."""
    check_no_remote(root)
    _git(root, "add", "-A", "--", ".gitignore", "raw", "notes", "own")
    if not _git(root, "status", "--porcelain").strip():
        return False
    _git(root, "commit", "-q", "-m", message)
    return True


def check_layout(root: Path) -> list[str]:
    missing = [d for d in DIRS if not (root / d).is_dir()]
    try:
        json.loads((root / ".lifeos" / "schema.json").read_text())
    except (OSError, ValueError):
        missing.append(".lifeos/schema.json")
    return missing

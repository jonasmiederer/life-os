"""lifeos command line."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from core.backup import BackupError, backup, restore_verify
from core.config import ConfigError, load_config
from core.datadir import DataRepoError, check_layout, check_no_remote, init_data_dir
from core.log import log_event
from core.reindex import reindex
from core.report import format_report
from core.smoke import run_smoke
from core.store import scan
from core.synthetic import populate, populate_invalid


def _health(root: Path) -> list[str]:
    problems = [f"missing:{m}" for m in check_layout(root)]
    try:
        check_no_remote(root)
    except DataRepoError as exc:
        problems.append(str(exc))
    return problems


def _serve(root: Path) -> int:
    """Phase 0 service loop: validate the data dir once a minute. UI and scheduler come later."""
    init_data_dir(root)
    log_event("core.started", ok=True)
    while True:
        bad = scan(root)
        if bad:
            log_event("core.scan", count=len(bad))
        time.sleep(60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lifeos")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-dir", type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create data dir layout and data git repo")
    v = sub.add_parser("validate", help="validate notes, move invalid ones to review/")
    v.add_argument("--check", action="store_true", help="report only, do not move")
    sub.add_parser("health", help="layout and no-remote guard")
    s = sub.add_parser("smoke", help="synthetic letter and .eml through validate")
    s.add_argument("--ntfy-url")
    r = sub.add_parser("report", help="paste-safe status report")
    r.add_argument("--dry-run", action="store_true", required=True)
    d = sub.add_parser("synthetic-datadir", help="build a synthetic data dir")
    d.add_argument("--out", type=Path, required=True)
    sub.add_parser("backup", help="restic backup of the whole data dir")
    rs = sub.add_parser("restore", help="restore the latest snapshot to a scratch dir")
    rs.add_argument("--verify", action="store_true", required=True)
    sub.add_parser("reindex", help="delete and rebuild the qmd cache")
    sub.add_parser("serve", help="run the core service")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    root = args.data_dir or cfg.data_dir

    try:
        if args.cmd == "init":
            init_data_dir(root)
        elif args.cmd == "validate":
            bad = scan(root, move=not args.check)
            for name, codes in bad.items():
                print(f"{name}: {','.join(codes)}")
            return 1 if bad else 0
        elif args.cmd == "health":
            problems = _health(root)
            print("\n".join(problems) or "ok")
            return 1 if problems else 0
        elif args.cmd == "smoke":
            fails = run_smoke(args.ntfy_url)
            print("\n".join(fails) or "smoke ok")
            return 1 if fails else 0
        elif args.cmd == "report":
            print(format_report(root))
        elif args.cmd == "synthetic-datadir":
            populate(args.out)
            populate_invalid(args.out)
        elif args.cmd == "backup":
            backup(root, cfg.restic_repo, cfg.restic_password_file)
        elif args.cmd == "restore":
            fails = restore_verify(cfg.restic_repo, cfg.restic_password_file)
            print("\n".join(fails) or "restore verify ok")
            return 1 if fails else 0
        elif args.cmd == "reindex":
            reindex(root)
        elif args.cmd == "serve":
            return _serve(root)
    except DataRepoError as exc:
        print(f"data repo error: {exc}", file=sys.stderr)
        return 1
    except BackupError as exc:
        print(f"backup error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

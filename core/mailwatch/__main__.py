"""Entry point: `python -m core.mailwatch [--once]`."""

from __future__ import annotations

import os
import sys
import time

from core.log import log_event
from core.mailwatch.config import ConfigError, load
from core.mailwatch.watcher import OpsError, Watcher
from core.notify import ntfy_sender


def main(argv: list[str]) -> int:
    try:
        cfg = load(os.environ)
        notify = ntfy_sender(cfg.ntfy_url, cfg.ntfy_topic) if cfg.ntfy_url else None
    except (ConfigError, ValueError) as exc:
        log_event("mailwatch.config", code="bad_config")
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    watcher = Watcher(cfg, notify=notify)
    while True:
        try:
            watcher.run_once()
        except OpsError:
            return 3  # MOVE missing: stop, the owner must fix the provider or the folder setup
        except ConfigError:
            log_event("mailwatch.config", code="bad_secret")
            return 2
        if "--once" in argv:
            return 0
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

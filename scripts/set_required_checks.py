"""Set the required status checks of the `main-protect` ruleset (design 8, review-p0 27).

Run only after the checks have run green once and the CI PRs are merged, because a
required check that no workflow produces blocks every PR.
Default is a dry run. `--apply` sends the update with `gh api` (needs repo admin).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

REPO = "jonasmiederer/life-os"
RULESET = "main-protect"
CHECKS = [
    "lint",
    "types",
    "unit",
    "security-tests",
    "fixtures-clean",
    "secrets-scan",
    "sast",
    "deps",
    "workflow-lint",
    "evals-det",
]
KEYS = ("name", "target", "enforcement", "conditions", "bypass_actors", "rules")


def with_checks(ruleset: dict[str, Any], checks: list[str]) -> dict[str, Any]:
    """Return an update body with the required checks replaced. Other rules stay as they are."""
    body = {k: ruleset[k] for k in KEYS}
    for rule in body["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["required_status_checks"] = [{"context": c} for c in checks]
            return body
    raise ValueError("ruleset has no required_status_checks rule")


def gh(*args: str, stdin: str | None = None) -> str:
    res = subprocess.run(
        ["gh", "api", *args], input=stdin, capture_output=True, text=True, check=True
    )
    return res.stdout


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv[1:])
    listing = json.loads(gh(f"repos/{REPO}/rulesets"))
    ids = [r["id"] for r in listing if r["name"] == RULESET]
    if len(ids) != 1:
        print(f"expected one ruleset named {RULESET}, found {len(ids)}")
        return 1
    url = f"repos/{REPO}/rulesets/{ids[0]}"
    body = with_checks(json.loads(gh(url)), CHECKS)
    print(json.dumps(body["rules"], indent=2))
    if not args.apply:
        print("dry run: nothing changed. Use --apply.")
        return 0
    gh("--method", "PUT", url, "--input", "-", stdin=json.dumps(body))
    print("ruleset updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

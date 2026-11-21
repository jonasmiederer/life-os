"""Stub permissions loader (review-p0 29). Checks only the shape from design 2.6."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROLES = {"actor", "reader"}


def load_permissions(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "helper" not in data or "agents" not in data:
        raise ValueError(f"{path}: needs `helper` and `agents`")
    for agent in data["agents"]:
        if agent.get("role") not in ROLES:
            raise ValueError(f"{path}: agent {agent.get('name')!r} has an unknown role")
    return data

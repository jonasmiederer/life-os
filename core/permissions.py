"""permissions.yml loader. One file per helper. Strict schema, unknown keys rejected."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class PermissionsError(ValueError):
    pass


_LISTS = ("reads", "writes", "network", "cloud_classes")
_KEYS = {"helper", "version", *_LISTS}


@dataclass(frozen=True)
class Permissions:
    helper: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    network: tuple[str, ...]
    cloud_classes: tuple[str, ...]


def load_permissions(path: Path) -> Permissions:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PermissionsError(f"cannot read permissions: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise PermissionsError("permissions must be a mapping")
    unknown = set(data) - _KEYS
    if unknown:
        raise PermissionsError(f"unknown keys: {sorted(map(str, unknown))}")
    if data.get("version") != 1:
        raise PermissionsError("version must be 1")
    helper = data.get("helper")
    if not isinstance(helper, str) or not helper.isidentifier():
        raise PermissionsError("helper must be an identifier")
    lists: dict[str, tuple[str, ...]] = {}
    for key in _LISTS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise PermissionsError(f"{key} must be a list of strings")
        lists[key] = tuple(value)
    return Permissions(helper=helper, **lists)


def permissions_digest(perms: Permissions) -> str:
    """Stable sha256 of the parsed content. A lock file stores this value."""
    parts = [perms.helper] + [f"{k}={','.join(sorted(getattr(perms, k)))}" for k in _LISTS]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()

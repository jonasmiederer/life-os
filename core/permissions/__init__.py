"""permissions.yml loader (design 2.6). One file per helper. Strict schema, fails closed.

A reader agent sees untrusted text, so it may hold only read and write_local tools.
The lock file (tests/security/permissions.lock) is checked by scripts/check_permissions_lock.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class PermissionsError(ValueError):
    pass


ROLES = {"actor", "reader"}
TOOL_KINDS = {"read", "write_local", "act"}
READER_KINDS = {"read", "write_local"}
CLASSES = {"C0", "C1", "C2", "C3", "C4"}
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_HOST = re.compile(r"^[a-z0-9.-]{1,253}(:[0-9]{1,5})?$")
_FILE_KEYS = {"helper", "agents"}
_AGENT_KEYS = {"name", "role", "reads", "tools", "network"}
_TOOL_KEYS = {"name", "kind"}


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str


@dataclass(frozen=True)
class Agent:
    name: str
    role: str
    reads: tuple[str, ...]
    tools: tuple[Tool, ...]
    network: tuple[str, ...]  # empty means "none"


@dataclass(frozen=True)
class Permissions:
    helper: str
    agents: tuple[Agent, ...]


def _keys(where: str, data: Any, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PermissionsError(f"{where}: must be a mapping")
    unknown = set(data) - allowed
    if unknown:
        raise PermissionsError(f"{where}: unknown keys {sorted(map(str, unknown))}")
    missing = required - set(data)
    if missing:
        raise PermissionsError(f"{where}: missing keys {sorted(missing)}")
    return data


def _name(where: str, value: Any) -> str:
    if not isinstance(value, str) or not _NAME.match(value):
        raise PermissionsError(f"{where}: bad name")
    return value


def _agent(where: str, raw: Any) -> Agent:
    data = _keys(where, raw, _AGENT_KEYS, {"name", "role"})
    name = _name(where, data["name"])
    where = f"{where} {name}"
    role = data["role"]
    if role not in ROLES:
        raise PermissionsError(f"{where}: unknown role")
    reads = data.get("reads", [])
    if not isinstance(reads, list) or not all(r in CLASSES for r in reads):
        raise PermissionsError(f"{where}: reads must list classes C0 to C4")
    tools: list[Tool] = []
    for t in data.get("tools", []) or []:
        td = _keys(f"{where} tool", t, _TOOL_KEYS, _TOOL_KEYS)
        if td["kind"] not in TOOL_KINDS:
            raise PermissionsError(f"{where}: unknown tool kind")
        if role == "reader" and td["kind"] not in READER_KINDS:
            raise PermissionsError(f"{where}: a reader may not hold an act tool")
        tools.append(Tool(_name(f"{where} tool", td["name"]), td["kind"]))
    network = data.get("network", "none")
    if network == "none":
        hosts: tuple[str, ...] = ()
    elif (
        isinstance(network, list)
        and network
        and all(isinstance(h, str) and _HOST.match(h) for h in network)
    ):
        if role == "reader":
            raise PermissionsError(f"{where}: a reader may not have network")
        hosts = tuple(network)
    else:
        raise PermissionsError(f"{where}: network must be none or a list of hosts")
    return Agent(name, role, tuple(reads), tuple(tools), hosts)


def load_permissions(path: Path) -> Permissions:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PermissionsError(f"{path.name}: cannot read ({type(exc).__name__})") from exc
    data = _keys(path.name, raw, _FILE_KEYS, _FILE_KEYS)
    helper = _name(path.name, data["helper"])
    agents_raw = data["agents"]
    if not isinstance(agents_raw, list) or not agents_raw:
        raise PermissionsError(f"{path.name}: agents must be a non-empty list")
    agents = tuple(_agent(f"{path.name} agent", a) for a in agents_raw)
    if len({a.name for a in agents}) != len(agents):
        raise PermissionsError(f"{path.name}: duplicate agent name")
    return Permissions(helper, agents)

"""config.toml loader. Schema-validated, unknown keys rejected, fails closed."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    data_dir: Path = Path("/data")
    ntfy_url: str = "http://ntfy:8080"


_KEYS = {"data_dir": str, "ntfy_url": str}


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    values: dict[str, str] = {}
    if path is not None:
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read config: {type(exc).__name__}") from exc
        for key, value in raw.items():
            if key not in _KEYS:
                raise ConfigError(f"unknown config key: {key}")
            if not isinstance(value, _KEYS[key]):
                raise ConfigError(f"wrong type for config key: {key}")
            values[key] = value
    if env.get("LIFEOS_DATA_DIR"):
        values["data_dir"] = env["LIFEOS_DATA_DIR"]
    if env.get("LIFEOS_NTFY_URL"):
        values["ntfy_url"] = env["LIFEOS_NTFY_URL"]
    if "data_dir" in values:
        values["data_dir"] = Path(values["data_dir"])  # type: ignore[assignment]
    return Config(**values)  # type: ignore[arg-type]

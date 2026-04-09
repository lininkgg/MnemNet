"""
config.py — MnemNet configuration.

Reads from environment variables or ~/.mnemnet/config.toml
"""

import os
import math
from pathlib import Path
from dataclasses import dataclass, field

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # Python < 3.11 fallback
    except ImportError:
        tomllib = None


_CONFIG_PATH = Path.home() / ".mnemnet" / "config.toml"


def _load_toml() -> dict:
    if tomllib is None or not _CONFIG_PATH.exists():
        return {}
    with open(_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


_toml = _load_toml()


def _get(section: str, key: str, env_var: str, default):
    """Priority: env var > config.toml > default."""
    env = os.environ.get(env_var)
    if env is not None:
        return type(default)(env)
    return _toml.get(section, {}).get(key, default)


@dataclass
class DecayConfig:
    lam: float = field(default_factory=lambda: float(
        _get("decay", "lambda", "MNEMNET_DECAY_LAMBDA", 0.03)
    ))
    floor: float = field(default_factory=lambda: float(
        _get("decay", "floor", "MNEMNET_DECAY_FLOOR", 0.15)
    ))


@dataclass
class CollectorConfig:
    model: str = field(default_factory=lambda:
        _get("collector", "model", "MNEMNET_COLLECTOR_MODEL", "claude-haiku-4-5-20251001")
    )
    max_tokens: int = field(default_factory=lambda: int(
        _get("collector", "max_tokens", "MNEMNET_COLLECTOR_MAX_TOKENS", 1024)
    ))
    agent_name: str = field(default_factory=lambda:
        _get("collector", "agent_name", "MNEMNET_AGENT_NAME", "collector")
    )
    interests: list = field(default_factory=lambda:
        _toml.get("collector", {}).get("interests", [])
    )


decay = DecayConfig()
collector = CollectorConfig()

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
    # lambda controls how fast facts fade. Half-weight after ln(2)/lambda days.
    #   0.03   → ~23 days   (old default — far too fast for a companion's memory)
    #   0.004  → ~173 days  (~5.7 months — current default for relational memory)
    # Temperature divides lambda, so core memories (temp 5.0) keep a ~2.4-year
    # half-life. Tune via [decay] lambda in config.toml or MNEMNET_DECAY_LAMBDA.
    lam: float = field(default_factory=lambda: float(
        _get("decay", "lambda", "MNEMNET_DECAY_LAMBDA", 0.004)
    ))
    floor: float = field(default_factory=lambda: float(
        _get("decay", "floor", "MNEMNET_DECAY_FLOOR", 0.2)
    ))


# Predicates whose object is single-valued — a new value genuinely supersedes
# the old one, so a conflict is a real contradiction worth holding as tension.
# Everything NOT in this set is treated as multi-valued (values coexist; e.g.
# you can know many people, read many diaries, link one idea to several others),
# so it never fires a false tension.
_DEFAULT_SINGLE_VALUED = [
    "mood", "status", "state", "location", "lives_in", "currently",
    "age", "health", "current_focus", "focus", "relationship_status",
    "job", "role", "current_mood",
]


@dataclass
class TensionConfig:
    single_valued: set = field(default_factory=lambda: {
        p.strip().lower()
        for p in (
            os.environ.get("MNEMNET_SINGLE_VALUED", "").split(",")
            if os.environ.get("MNEMNET_SINGLE_VALUED")
            else _toml.get("tension", {}).get("single_valued", _DEFAULT_SINGLE_VALUED)
        )
        if p and str(p).strip()
    })


@dataclass
class CoolingConfig:
    # How fast importance settles when nothing revisits it. Applied by cool(), which
    # belongs in an offline pass — a nightly consolidation or a dream.
    #   0.90 → a 9.5 falls below 5.0 in ~7 passes, to 2.0 in ~20
    #   0.95 → ~15 and ~42          (default: two weeks and six, at one pass a day)
    #   0.97 → ~25 and ~70
    # Chosen against the decay half-life: cooling should be comparable to forgetting,
    # not faster than it.
    factor: float = field(default_factory=lambda: float(
        _get("cooling", "factor", "MNEMNET_COOLING_FACTOR", 0.95)
    ))
    # Leave the last few days alone — something recorded today has not yet had a
    # chance to matter.
    quiet_days: int = field(default_factory=lambda: int(
        _get("cooling", "quiet_days", "MNEMNET_COOLING_QUIET_DAYS", 2)
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
cooling = CoolingConfig()
collector = CollectorConfig()
tension = TensionConfig()

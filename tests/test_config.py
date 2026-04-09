"""
Tests for mnemnet.config — configuration loading.
"""

import os
import pytest
from unittest.mock import patch


class TestDecayConfig:
    def test_defaults(self):
        from mnemnet.config import DecayConfig
        cfg = DecayConfig()
        assert cfg.lam == 0.03
        assert cfg.floor == 0.15

    def test_env_override(self):
        with patch.dict(os.environ, {"MNEMNET_DECAY_LAMBDA": "0.05", "MNEMNET_DECAY_FLOOR": "0.2"}):
            # Force re-evaluation by creating new instance
            from mnemnet.config import _get
            lam = float(_get("decay", "lambda", "MNEMNET_DECAY_LAMBDA", 0.03))
            floor = float(_get("decay", "floor", "MNEMNET_DECAY_FLOOR", 0.15))
            assert lam == 0.05
            assert floor == 0.2


class TestCollectorConfig:
    def test_defaults(self):
        from mnemnet.config import CollectorConfig
        cfg = CollectorConfig()
        assert cfg.model == "claude-haiku-4-5-20251001"
        assert cfg.agent_name == "collector"
        assert cfg.max_tokens == 1024

    def test_env_override_agent_name(self):
        with patch.dict(os.environ, {"MNEMNET_AGENT_NAME": "kairos"}):
            from mnemnet.config import _get
            name = _get("collector", "agent_name", "MNEMNET_AGENT_NAME", "collector")
            assert name == "kairos"

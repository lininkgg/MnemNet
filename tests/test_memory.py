"""
Tests for mnemnet.memory — core mechanisms.

Uses a temporary KG database so nothing touches the real palace.
"""

import math
import pytest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from mnemnet.memory import (
    _decay_weight,
    kg_query_weighted,
    kg_query_summary,
    kg_add_smart,
    get_tensions,
    add_expectation,
    add_surprise,
    get_expectations,
    living_context,
)


# ---------------------------------------------------------------------------
# _decay_weight — pure function, no mocking needed
# ---------------------------------------------------------------------------

class TestDecayWeight:
    def test_none_returns_half(self):
        assert _decay_weight(None) == 0.5

    def test_today_returns_one(self):
        today = date.today().isoformat()
        assert _decay_weight(today) == 1.0

    def test_old_date_reaches_floor(self):
        old = (date.today() - timedelta(days=365)).isoformat()
        w = _decay_weight(old)
        assert w == 0.15  # floor

    def test_recent_date_between_floor_and_one(self):
        recent = (date.today() - timedelta(days=10)).isoformat()
        w = _decay_weight(recent)
        assert 0.15 < w < 1.0

    def test_garbage_string_returns_half(self):
        assert _decay_weight("not-a-date") == 0.5

    def test_decay_is_monotonic(self):
        """Newer facts always weigh more than older facts."""
        dates = [(date.today() - timedelta(days=d)).isoformat() for d in range(0, 100, 10)]
        weights = [_decay_weight(d) for d in dates]
        for i in range(len(weights) - 1):
            assert weights[i] >= weights[i + 1]

    def test_floor_config_respected(self):
        """Floor should never let weight go below configured minimum."""
        from mnemnet import config
        ancient = (date.today() - timedelta(days=10000)).isoformat()
        w = _decay_weight(ancient)
        assert w == config.decay.floor


# ---------------------------------------------------------------------------
# Mock KG for testing write/read operations
# ---------------------------------------------------------------------------

def _make_mock_kg():
    """Create a mock KG that stores triples in memory."""
    store = []

    kg = MagicMock()

    def add_triple(subject, predicate, obj, valid_from=None, **kwargs):
        store.append({
            "direction": "outgoing",
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "valid_from": valid_from,
            "valid_to": None,
            "confidence": 1.0,
            "source_closet": None,
            "current": True,
        })

    def query_entity(name=None, direction="outgoing", **kwargs):
        results = []
        for t in store:
            if direction in ("outgoing", "both") and t["subject"] == name:
                results.append(t)
            if direction in ("incoming", "both") and t["object"] == name:
                results.append({**t, "direction": "incoming"})
        return results if results else []

    kg.add_triple = add_triple
    kg.query_entity = query_entity
    kg._store = store

    return kg


@pytest.fixture
def mock_kg():
    """Patch _kg() to return an in-memory mock."""
    kg = _make_mock_kg()
    with patch("mnemnet.memory._kg", return_value=kg):
        yield kg


# ---------------------------------------------------------------------------
# kg_add_smart
# ---------------------------------------------------------------------------

class TestKgAddSmart:
    def test_add_simple_fact(self, mock_kg):
        result = kg_add_smart("agent", "mood", "happy")
        assert result["added"] is True
        assert result["tension"] is None
        assert len(mock_kg._store) == 1

    def test_add_same_value_no_tension(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        result = kg_add_smart("agent", "mood", "happy")
        assert result["tension"] is None

    def test_add_conflicting_creates_tension(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        result = kg_add_smart("agent", "mood", "sad")
        assert result["tension"] is not None
        assert "happy" in result["tension"]
        assert "sad" in result["tension"]

    def test_tension_stored_as_node(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        kg_add_smart("agent", "mood", "sad")
        tension_nodes = [
            t for t in mock_kg._store
            if "_tension_" in t["predicate"]
        ]
        assert len(tension_nodes) == 1
        assert tension_nodes[0]["predicate"] == "_tension_mood"

    def test_both_facts_kept(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        kg_add_smart("agent", "mood", "sad")
        mood_facts = [t for t in mock_kg._store if t["predicate"] == "mood"]
        assert len(mood_facts) == 2


# ---------------------------------------------------------------------------
# get_tensions
# ---------------------------------------------------------------------------

class TestGetTensions:
    def test_no_tensions(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        assert get_tensions("agent") == []

    def test_tensions_after_conflict(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        kg_add_smart("agent", "mood", "sad")
        t = get_tensions("agent")
        assert len(t) == 1
        assert "mood" in t[0]


# ---------------------------------------------------------------------------
# Predictive layer
# ---------------------------------------------------------------------------

class TestPredictiveLayer:
    def test_add_expectation(self, mock_kg):
        add_expectation("user", "will finish project")
        expectations = get_expectations("user")
        assert "will finish project" in expectations

    def test_add_surprise_creates_question(self, mock_kg):
        add_surprise("user", "tired", "energized")
        surprise_nodes = [
            t for t in mock_kg._store
            if t["predicate"] == "_surprise"
        ]
        question_nodes = [
            t for t in mock_kg._store
            if t["predicate"] == "pulls_question"
        ]
        assert len(surprise_nodes) == 1
        assert len(question_nodes) == 1
        assert "tired" in surprise_nodes[0]["object"]
        assert "energized" in surprise_nodes[0]["object"]


# ---------------------------------------------------------------------------
# kg_query_weighted
# ---------------------------------------------------------------------------

class TestKgQueryWeighted:
    def test_returns_weighted_facts(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        facts = kg_query_weighted("agent")
        assert len(facts) == 1
        assert "weight" in facts[0]
        assert 0 < facts[0]["weight"] <= 1.0

    def test_sorted_by_weight_desc(self, mock_kg):
        # Add facts with different dates
        mock_kg._store.append({
            "direction": "outgoing", "subject": "agent",
            "predicate": "old_fact", "object": "ancient",
            "valid_from": "2020-01-01", "valid_to": None,
            "confidence": 1.0, "source_closet": None, "current": True,
        })
        kg_add_smart("agent", "mood", "happy")
        facts = kg_query_weighted("agent")
        assert facts[0]["weight"] >= facts[-1]["weight"]


# ---------------------------------------------------------------------------
# kg_query_summary
# ---------------------------------------------------------------------------

class TestKgQuerySummary:
    def test_empty_entity(self, mock_kg):
        s = kg_query_summary("nobody")
        assert "nothing found" in s

    def test_has_entity_name(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        s = kg_query_summary("agent")
        assert "[agent]" in s
        assert "mood" in s


# ---------------------------------------------------------------------------
# living_context
# ---------------------------------------------------------------------------

class TestLivingContext:
    def test_empty_returns_placeholder(self, mock_kg):
        ctx = living_context(["nobody"])
        assert ctx == "(context empty)"

    def test_includes_entity_header(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        ctx = living_context(["agent"])
        assert "◈ agent" in ctx

    def test_includes_tension(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        kg_add_smart("agent", "mood", "sad")
        ctx = living_context(["agent"])
        assert "tension" in ctx

    def test_includes_expectation(self, mock_kg):
        add_expectation("agent", "will succeed")
        ctx = living_context(["agent"])
        assert "expecting" in ctx

    def test_multiple_entities(self, mock_kg):
        kg_add_smart("agent", "mood", "happy")
        kg_add_smart("user", "status", "active")
        ctx = living_context(["agent", "user"])
        assert "◈ agent" in ctx
        assert "◈ user" in ctx

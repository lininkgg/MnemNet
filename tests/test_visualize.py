"""
Tests for mnemnet.visualize — graph generation.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from mnemnet.visualize import _collect_triples, generate


def _mock_kg_for_viz():
    """Mock KG that returns predictable data for visualization tests."""
    kg = MagicMock()

    kg.stats.return_value = {
        "entities": 3,
        "triples": 4,
        "current_facts": 4,
        "expired_facts": 0,
        "relationship_types": ["works_on", "_tension_mood", "_expectation"],
    }

    def query_relationship(predicate, as_of=None):
        data = {
            "works_on": [
                {"subject": "agent", "predicate": "works_on", "object": "project",
                 "valid_from": "2026-04-09", "valid_to": None, "current": True},
                {"subject": "user", "predicate": "works_on", "object": "project",
                 "valid_from": "2026-04-08", "valid_to": None, "current": True},
            ],
            "_tension_mood": [
                {"subject": "agent", "predicate": "_tension_mood",
                 "object": "before: calm / now: anxious",
                 "valid_from": "2026-04-09", "valid_to": None, "current": True},
            ],
            "_expectation": [
                {"subject": "user", "predicate": "_expectation",
                 "object": "will finish by Friday",
                 "valid_from": "2026-04-09", "valid_to": None, "current": True},
            ],
        }
        return data.get(predicate, [])

    kg.query_relationship = query_relationship
    return kg


@pytest.fixture
def mock_viz_kg():
    kg = _mock_kg_for_viz()
    with patch("mnemnet.visualize.KnowledgeGraph", return_value=kg):
        yield kg


class TestCollectTriples:
    def test_collects_all_triples(self, mock_viz_kg):
        triples = _collect_triples()
        assert len(triples) == 4

    def test_triples_have_required_keys(self, mock_viz_kg):
        triples = _collect_triples()
        for t in triples:
            assert "s" in t
            assert "p" in t
            assert "o" in t
            assert "w" in t

    def test_weights_are_valid(self, mock_viz_kg):
        triples = _collect_triples()
        for t in triples:
            assert 0.15 <= t["w"] <= 1.0

    def test_no_duplicates(self, mock_viz_kg):
        triples = _collect_triples()
        keys = [(t["s"], t["p"], t["o"]) for t in triples]
        assert len(keys) == len(set(keys))


class TestGenerate:
    def test_generates_html_file(self, mock_viz_kg, tmp_path):
        output = tmp_path / "test_graph.html"
        result = generate(output_path=output, open_browser=False)
        assert result == output
        assert output.exists()

    def test_html_contains_d3(self, mock_viz_kg, tmp_path):
        output = tmp_path / "test_graph.html"
        generate(output_path=output, open_browser=False)
        html = output.read_text()
        assert "d3.min.js" in html
        assert "<svg" in html

    def test_html_contains_triples_data(self, mock_viz_kg, tmp_path):
        output = tmp_path / "test_graph.html"
        generate(output_path=output, open_browser=False)
        html = output.read_text()
        assert "agent" in html
        assert "works_on" in html

    def test_empty_kg(self, tmp_path):
        kg = MagicMock()
        kg.stats.return_value = {"relationship_types": []}
        kg.query_relationship.return_value = []
        with patch("mnemnet.visualize.KnowledgeGraph", return_value=kg):
            output = tmp_path / "empty.html"
            generate(output_path=output, open_browser=False)
            # Should still return path but file may be empty/minimal
            assert output.parent.exists()

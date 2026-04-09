"""
Tests for mnemnet.collector — source fetching and analysis.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from mnemnet.collector import fetch_source, analyze_and_store, _fetch_file


# ---------------------------------------------------------------------------
# Source fetching
# ---------------------------------------------------------------------------

class TestFetchSource:
    def test_unknown_type_returns_empty(self):
        result = fetch_source({"name": "bad", "type": "ftp"})
        assert result == ""

    def test_file_source_reads_content(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello from file")
        result = fetch_source({"name": "test", "type": "file", "path": str(f)})
        assert result == "hello from file"

    def test_file_source_missing_returns_empty(self):
        result = fetch_source({
            "name": "missing",
            "type": "file",
            "path": "/nonexistent/path/file.md",
        })
        assert result == ""

    def test_command_source(self):
        result = fetch_source({
            "name": "echo",
            "type": "command",
            "command": "echo 'hello from command'",
        })
        assert "hello from command" in result

    def test_command_source_empty_command(self):
        result = fetch_source({"name": "empty", "type": "command", "command": ""})
        assert result == ""


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

class TestAnalyzeAndStore:
    def test_empty_content_returns_zero(self):
        count = analyze_and_store("fake-key", "test", "")
        assert count == 0

    def test_whitespace_content_returns_zero(self):
        count = analyze_and_store("fake-key", "test", "   \n\n  ")
        assert count == 0

    def test_successful_analysis(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {"subject": "AI_paper", "predicate": "published_on_arxiv", "object": "new memory architecture"}
        ]))]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        mock_kg = MagicMock()

        with patch("mnemnet.collector.anthropic.Anthropic", return_value=mock_client), \
             patch("mnemnet.collector.KnowledgeGraph", return_value=mock_kg):
            count = analyze_and_store("fake-key", "arxiv", "Some paper about memory...")
            assert count == 1
            mock_kg.add_triple.assert_called_once()

    def test_empty_response_from_claude(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="[]")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("mnemnet.collector.anthropic.Anthropic", return_value=mock_client):
            count = analyze_and_store("fake-key", "test", "Some content here")
            assert count == 0

    def test_api_error_returns_zero(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        with patch("mnemnet.collector.anthropic.Anthropic", return_value=mock_client):
            count = analyze_and_store("fake-key", "test", "Some content here")
            assert count == 0

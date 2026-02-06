"""Tests for parse_transcript() -- file I/O mocking.

Target: hooks/db_logger.py:368-391
"""

import pytest
from unittest.mock import patch, mock_open
import json

from hooks.db_logger import parse_transcript


pytestmark = pytest.mark.unit


class TestParseTranscript:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert parse_transcript(str(f)) == []

    def test_single_user_message(self, tmp_path):
        line = json.dumps({'type': 'user', 'uuid': 'u1',
                           'message': {'content': 'hello'}})
        f = tmp_path / "one.jsonl"
        f.write_text(line + "\n")
        result = parse_transcript(str(f))
        assert len(result) == 1
        assert result[0]['role'] == 'user'

    def test_multiple_messages(self, tmp_path):
        lines = [
            json.dumps({'type': 'user', 'message': {'content': 'q'}}),
            json.dumps({'type': 'assistant', 'message': {
                'content': [{'type': 'text', 'text': 'a'}]}}),
        ]
        f = tmp_path / "multi.jsonl"
        f.write_text("\n".join(lines) + "\n")
        result = parse_transcript(str(f))
        assert len(result) == 2

    def test_invalid_json_skipped(self, tmp_path):
        lines = [
            json.dumps({'type': 'user', 'message': {'content': 'ok'}}),
            "NOT VALID JSON{{{",
            json.dumps({'type': 'user', 'message': {'content': 'also ok'}}),
        ]
        f = tmp_path / "mixed.jsonl"
        f.write_text("\n".join(lines) + "\n")
        result = parse_transcript(str(f))
        assert len(result) == 2

    def test_blank_lines_skipped(self, tmp_path):
        lines = [
            "",
            json.dumps({'type': 'user', 'message': {'content': 'ok'}}),
            "   ",
            "",
        ]
        f = tmp_path / "blanks.jsonl"
        f.write_text("\n".join(lines) + "\n")
        result = parse_transcript(str(f))
        assert len(result) == 1

    def test_file_not_found(self):
        result = parse_transcript("/nonexistent/path/file.jsonl")
        assert result == []

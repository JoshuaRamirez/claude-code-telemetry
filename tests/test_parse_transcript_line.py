"""Tests for _parse_transcript_line() -- pure function, no mocking needed.

Target: hooks/db_logger.py:310-365
"""

import json
import pytest

from hooks.db_logger import _parse_transcript_line


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# User messages
# ---------------------------------------------------------------------------

class TestUserStringContent:
    def test_simple_string(self):
        obj = {'type': 'user', 'uuid': 'u1', 'parentUuid': 'p1',
               'timestamp': '2026-01-01T00:00:00Z',
               'message': {'content': 'Hello world'}}
        result = _parse_transcript_line(obj)
        assert result['role'] == 'user'
        assert result['content'] == 'Hello world'
        assert result['uuid'] == 'u1'
        assert result['parent_uuid'] == 'p1'
        assert result['model'] is None
        assert result['thinking_content'] is None
        assert result['usage'] is None

    def test_empty_string_content(self):
        obj = {'type': 'user', 'message': {'content': ''}}
        result = _parse_transcript_line(obj)
        assert result['role'] == 'user'
        assert result['content'] == ''


class TestUserListContent:
    def test_list_content_serialized_to_json(self):
        blocks = [{'type': 'text', 'text': 'part1'}, {'type': 'text', 'text': 'part2'}]
        obj = {'type': 'user', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result['content'] == json.dumps(blocks)

    def test_empty_list_content(self):
        obj = {'type': 'user', 'message': {'content': []}}
        result = _parse_transcript_line(obj)
        assert result['content'] == '[]'


class TestUserMissingFields:
    def test_no_message_key(self):
        obj = {'type': 'user'}
        result = _parse_transcript_line(obj)
        # content defaults to '' via .get('content', '')
        assert result['content'] == ''

    def test_no_uuid(self):
        obj = {'type': 'user', 'message': {'content': 'hi'}}
        result = _parse_transcript_line(obj)
        assert result['uuid'] is None


# ---------------------------------------------------------------------------
# Assistant messages
# ---------------------------------------------------------------------------

class TestAssistantTextBlocks:
    def test_single_text_block(self):
        obj = {'type': 'assistant', 'uuid': 'a1',
               'message': {'content': [{'type': 'text', 'text': 'response'}],
                           'model': 'claude-sonnet-4-20250514'}}
        result = _parse_transcript_line(obj)
        assert result['role'] == 'assistant'
        assert result['content'] == 'response'
        assert result['model'] == 'claude-sonnet-4-20250514'

    def test_multiple_text_blocks_joined(self):
        obj = {'type': 'assistant',
               'message': {'content': [
                   {'type': 'text', 'text': 'line1'},
                   {'type': 'text', 'text': 'line2'},
               ]}}
        result = _parse_transcript_line(obj)
        assert result['content'] == 'line1\nline2'


class TestAssistantThinkingBlocks:
    def test_thinking_only(self):
        obj = {'type': 'assistant',
               'message': {'content': [
                   {'type': 'thinking', 'thinking': 'deep thought'},
               ]}}
        result = _parse_transcript_line(obj)
        assert result['thinking_content'] == 'deep thought'
        assert result['content'] is None

    def test_mixed_text_and_thinking(self):
        obj = {'type': 'assistant',
               'message': {'content': [
                   {'type': 'thinking', 'thinking': 'hmm'},
                   {'type': 'text', 'text': 'answer'},
               ]}}
        result = _parse_transcript_line(obj)
        assert result['content'] == 'answer'
        assert result['thinking_content'] == 'hmm'


class TestAssistantUsageData:
    def test_all_usage_fields(self):
        obj = {'type': 'assistant',
               'message': {'content': [{'type': 'text', 'text': 'ok'}],
                           'usage': {
                               'input_tokens': 100,
                               'output_tokens': 50,
                               'cache_creation_input_tokens': 10,
                               'cache_read_input_tokens': 20,
                               'service_tier': 'standard',
                           }}}
        result = _parse_transcript_line(obj)
        assert result['usage']['input_tokens'] == 100
        assert result['usage']['output_tokens'] == 50
        assert result['usage']['cache_creation_tokens'] == 10
        assert result['usage']['cache_read_tokens'] == 20
        assert result['usage']['service_tier'] == 'standard'

    def test_partial_usage_fields(self):
        obj = {'type': 'assistant',
               'message': {'content': [{'type': 'text', 'text': 'ok'}],
                           'usage': {'input_tokens': 42}}}
        result = _parse_transcript_line(obj)
        assert result['usage']['input_tokens'] == 42
        assert result['usage']['output_tokens'] is None

    def test_empty_usage_dict_still_returns_none_usage(self):
        """Empty {} usage dict is falsy, so usage_data stays None."""
        obj = {'type': 'assistant',
               'message': {'content': [{'type': 'text', 'text': 'ok'}],
                           'usage': {}}}
        result = _parse_transcript_line(obj)
        # usage={} is falsy, but content blocks exist so result is returned
        assert result is not None
        assert result['usage'] is None


class TestAssistantEdgeCases:
    def test_empty_content_blocks_no_usage_returns_none(self):
        """Assistant with no text, no thinking, no usage -> None."""
        obj = {'type': 'assistant', 'message': {'content': []}}
        result = _parse_transcript_line(obj)
        assert result is None

    def test_non_dict_blocks_skipped(self):
        """Non-dict items in content blocks are silently skipped."""
        obj = {'type': 'assistant',
               'message': {'content': ['raw string', 42,
                                        {'type': 'text', 'text': 'valid'}]}}
        result = _parse_transcript_line(obj)
        assert result['content'] == 'valid'


# ---------------------------------------------------------------------------
# Unknown / missing type
# ---------------------------------------------------------------------------

class TestUnknownType:
    def test_unknown_type_returns_none(self):
        obj = {'type': 'system', 'message': {'content': 'boot'}}
        result = _parse_transcript_line(obj)
        assert result is None

    def test_missing_type_returns_none(self):
        obj = {'message': {'content': 'no type'}}
        result = _parse_transcript_line(obj)
        assert result is None

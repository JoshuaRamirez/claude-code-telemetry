"""Tests for _parse_transcript_line() -- pure function, no mocking needed.

Target: hooks/db_logger.py — _parse_transcript_line()

v2.1 changes tested:
- User list content: text extraction instead of raw JSON dump
- Assistant tool_use blocks captured
- Assistant content_blocks_json stored
- Thinking block boundary preservation (single=text, multiple=JSON array)
- System, queue-operation, file-history-snapshot line types
- progress and saved_hook_context skipped
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
        assert result['content_blocks_json'] is None

    def test_empty_string_content(self):
        obj = {'type': 'user', 'message': {'content': ''}}
        result = _parse_transcript_line(obj)
        assert result['role'] == 'user'
        assert result['content'] == ''


class TestUserListContent:
    def test_list_text_blocks_extracted(self):
        """Text blocks in user content are extracted and joined."""
        blocks = [{'type': 'text', 'text': 'part1'}, {'type': 'text', 'text': 'part2'}]
        obj = {'type': 'user', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result['content'] == 'part1\npart2'

    def test_list_with_raw_strings(self):
        """Raw strings in user content list are extracted."""
        blocks = ['hello', 'world']
        obj = {'type': 'user', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result['content'] == 'hello\nworld'

    def test_list_mixed_strings_and_text_blocks(self):
        """Mixed raw strings and text blocks are both extracted."""
        blocks = ['raw', {'type': 'text', 'text': 'block'}]
        obj = {'type': 'user', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result['content'] == 'raw\nblock'

    def test_empty_list_content(self):
        """Empty list falls back to JSON dump."""
        obj = {'type': 'user', 'message': {'content': []}}
        result = _parse_transcript_line(obj)
        assert result['content'] == '[]'

    def test_list_with_non_text_blocks_falls_back(self):
        """List with no extractable text falls back to JSON dump."""
        blocks = [{'type': 'image', 'data': 'base64...'}]
        obj = {'type': 'user', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result['content'] == json.dumps(blocks)


class TestUserMissingFields:
    def test_no_message_key(self):
        obj = {'type': 'user'}
        result = _parse_transcript_line(obj)
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


class TestAssistantToolUseBlocks:
    def test_tool_use_block_captured(self):
        """tool_use blocks are captured and appear in content_blocks_json."""
        blocks = [
            {'type': 'text', 'text': 'Let me read that file.'},
            {'type': 'tool_use', 'id': 'tu-1', 'name': 'Read',
             'input': {'file_path': '/test.py'}}
        ]
        obj = {'type': 'assistant', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result['content'] == 'Let me read that file.'
        assert result['content_blocks_json'] is not None
        parsed = json.loads(result['content_blocks_json'])
        assert len(parsed) == 2
        assert parsed[1]['type'] == 'tool_use'
        assert parsed[1]['name'] == 'Read'

    def test_tool_use_only_message(self):
        """Assistant message with only tool_use blocks (no text) is captured."""
        blocks = [
            {'type': 'tool_use', 'id': 'tu-1', 'name': 'Bash',
             'input': {'command': 'ls'}}
        ]
        obj = {'type': 'assistant', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result is not None
        assert result['content'] is None
        assert result['content_blocks_json'] is not None

    def test_multiple_tool_use_blocks(self):
        """Multiple tool_use blocks in same message."""
        blocks = [
            {'type': 'tool_use', 'id': 'tu-1', 'name': 'Read',
             'input': {'file_path': '/a.py'}},
            {'type': 'tool_use', 'id': 'tu-2', 'name': 'Read',
             'input': {'file_path': '/b.py'}}
        ]
        obj = {'type': 'assistant', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        parsed = json.loads(result['content_blocks_json'])
        assert len(parsed) == 2


class TestAssistantContentBlocksJson:
    def test_content_blocks_json_stored(self):
        """content_blocks_json stores full content array as JSON."""
        blocks = [{'type': 'text', 'text': 'hello'}]
        obj = {'type': 'assistant', 'message': {'content': blocks}}
        result = _parse_transcript_line(obj)
        assert result['content_blocks_json'] == json.dumps(blocks)

    def test_empty_content_blocks_json_is_none(self):
        """Empty content blocks list results in None content_blocks_json."""
        obj = {'type': 'assistant', 'message': {'content': [],
                                                  'usage': {'input_tokens': 10}}}
        result = _parse_transcript_line(obj)
        # Returns non-None because usage_data exists
        assert result is not None
        assert result['content_blocks_json'] is None


class TestAssistantThinkingBlocks:
    def test_single_thinking_block(self):
        """Single thinking block stored as plain text."""
        obj = {'type': 'assistant',
               'message': {'content': [
                   {'type': 'thinking', 'thinking': 'deep thought'},
               ]}}
        result = _parse_transcript_line(obj)
        assert result['thinking_content'] == 'deep thought'
        assert result['content'] is None

    def test_multiple_thinking_blocks_stored_as_json_array(self):
        """Multiple thinking blocks stored as JSON array to preserve boundaries."""
        obj = {'type': 'assistant',
               'message': {'content': [
                   {'type': 'thinking', 'thinking': 'first thought'},
                   {'type': 'thinking', 'thinking': 'second thought'},
               ]}}
        result = _parse_transcript_line(obj)
        parsed = json.loads(result['thinking_content'])
        assert isinstance(parsed, list)
        assert parsed == ['first thought', 'second thought']

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
        assert result is not None
        assert result['usage'] is None


class TestAssistantEdgeCases:
    def test_empty_content_blocks_no_usage_returns_none(self):
        """Assistant with no text, no thinking, no tool_use, no usage -> None."""
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
# System messages (C2 fix)
# ---------------------------------------------------------------------------

class TestSystemMessages:
    def test_system_message_captured(self):
        obj = {'type': 'system', 'timestamp': '2026-01-01T00:00:00Z',
               'message': {'content': 'boot'}}
        result = _parse_transcript_line(obj)
        assert result is not None
        assert result['role'] == 'system'
        assert result['uuid'] is None
        assert result['content'] == json.dumps(obj)
        assert result['content_blocks_json'] is None

    def test_system_message_without_timestamp(self):
        obj = {'type': 'system', 'data': 'some system info'}
        result = _parse_transcript_line(obj)
        assert result['role'] == 'system'
        assert result['timestamp'] is None


# ---------------------------------------------------------------------------
# Queue-operation messages (C2 fix)
# ---------------------------------------------------------------------------

class TestQueueOperationMessages:
    def test_queue_operation_with_content(self):
        obj = {'type': 'queue-operation', 'content': 'operation details',
               'timestamp': '2026-01-01T00:00:00Z'}
        result = _parse_transcript_line(obj)
        assert result is not None
        assert result['role'] == 'queue_operation'
        assert result['content'] == 'operation details'
        assert result['uuid'] is None

    def test_queue_operation_without_content(self):
        """Falls back to JSON dump when no 'content' key."""
        obj = {'type': 'queue-operation', 'operation': 'enqueue'}
        result = _parse_transcript_line(obj)
        assert result['role'] == 'queue_operation'
        assert result['content'] == json.dumps(obj)

    def test_queue_operation_with_dict_content(self):
        """Dict content is serialized to JSON, not stored as Python repr."""
        obj = {'type': 'queue-operation',
               'content': {'action': 'push', 'items': [1, 2]}}
        result = _parse_transcript_line(obj)
        assert result['content'] == json.dumps({'action': 'push', 'items': [1, 2]})
        # Must be valid JSON, not Python repr
        parsed = json.loads(result['content'])
        assert parsed['action'] == 'push'

    def test_queue_operation_with_empty_string_content(self):
        """Empty string content is preserved, not replaced with full object dump."""
        obj = {'type': 'queue-operation', 'content': ''}
        result = _parse_transcript_line(obj)
        assert result['content'] == ''

    def test_queue_operation_with_list_content(self):
        """List content is serialized to JSON."""
        obj = {'type': 'queue-operation', 'content': ['item1', 'item2']}
        result = _parse_transcript_line(obj)
        assert result['content'] == json.dumps(['item1', 'item2'])


# ---------------------------------------------------------------------------
# File-history-snapshot messages (C2 fix)
# ---------------------------------------------------------------------------

class TestFileHistorySnapshotMessages:
    def test_file_history_captured(self):
        obj = {'type': 'file-history-snapshot',
               'files': ['/a.py', '/b.py'],
               'timestamp': '2026-01-01T00:00:00Z'}
        result = _parse_transcript_line(obj)
        assert result is not None
        assert result['role'] == 'file_history'
        assert result['content'] == json.dumps(obj)
        assert result['uuid'] is None


# ---------------------------------------------------------------------------
# Skipped / unknown types
# ---------------------------------------------------------------------------

class TestSkippedTypes:
    def test_progress_returns_none(self):
        """Progress lines (streaming noise) are skipped."""
        obj = {'type': 'progress', 'data': 'streaming...'}
        result = _parse_transcript_line(obj)
        assert result is None

    def test_saved_hook_context_returns_none(self):
        obj = {'type': 'saved_hook_context', 'data': {}}
        result = _parse_transcript_line(obj)
        assert result is None

    def test_missing_type_returns_none(self):
        obj = {'message': {'content': 'no type'}}
        result = _parse_transcript_line(obj)
        assert result is None

    def test_unknown_type_returns_none(self):
        obj = {'type': 'some_future_type', 'data': {}}
        result = _parse_transcript_line(obj)
        assert result is None

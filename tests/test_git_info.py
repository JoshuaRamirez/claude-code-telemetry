"""Tests for get_git_info() -- subprocess mocking.

Target: hooks/db_logger.py:239-255
"""

from unittest.mock import patch

import pytest

from hooks.db_logger import get_git_info
from tests.conftest import make_subprocess_result

pytestmark = pytest.mark.unit


class TestGetGitInfo:
    @patch('hooks.db_logger.subprocess.run')
    def test_both_succeed(self, mock_run):
        mock_run.side_effect = [
            make_subprocess_result(stdout='main\n'),
            make_subprocess_result(stdout='abc1234\n'),
        ]
        branch, commit = get_git_info()
        assert branch == 'main'
        assert commit == 'abc1234'

    @patch('hooks.db_logger.subprocess.run')
    def test_branch_fails(self, mock_run):
        mock_run.side_effect = [
            make_subprocess_result(returncode=128, stderr='not a git repo'),
            make_subprocess_result(stdout='abc1234\n'),
        ]
        branch, commit = get_git_info()
        assert branch is None
        assert commit == 'abc1234'

    @patch('hooks.db_logger.subprocess.run')
    def test_commit_fails(self, mock_run):
        mock_run.side_effect = [
            make_subprocess_result(stdout='main\n'),
            make_subprocess_result(returncode=128),
        ]
        branch, commit = get_git_info()
        assert branch == 'main'
        assert commit is None

    @patch('hooks.db_logger.subprocess.run')
    def test_both_fail(self, mock_run):
        mock_run.side_effect = [
            make_subprocess_result(returncode=1),
            make_subprocess_result(returncode=1),
        ]
        branch, commit = get_git_info()
        assert branch is None
        assert commit is None

    @patch('hooks.db_logger.subprocess.run', side_effect=OSError("git not found"))
    def test_exception_returns_none_none(self, mock_run):
        branch, commit = get_git_info()
        assert branch is None
        assert commit is None

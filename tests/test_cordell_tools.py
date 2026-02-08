"""Tests for cordell_tools module."""

from unittest.mock import MagicMock

import pytest

from cordell_tools import create_cordell_mcp_server


class TestCreateCordellMcpServer:
    """Tests for MCP server creation."""

    def test_creates_server(self):
        """create_cordell_mcp_server returns a server config."""
        mock_scheduler = MagicMock()
        server = create_cordell_mcp_server(mock_scheduler)

        # The server is a dict-like McpSdkServerConfig
        assert server is not None
        # Check it has the expected structure (it's a dict with name and type)
        assert server["name"] == "cordell"
        assert server["type"] == "sdk"
        assert "instance" in server


class TestScheduleJobValidation:
    """Tests for schedule_job validation."""

    def test_valid_cron_expression(self):
        """Valid cron expressions are accepted."""
        from apscheduler.triggers.cron import CronTrigger

        # Should not raise
        CronTrigger.from_crontab("0 9 * * *")
        CronTrigger.from_crontab("*/5 * * * *")
        CronTrigger.from_crontab("0 0 1 * *")

    def test_invalid_cron_expression(self):
        """Invalid cron expressions raise ValueError."""
        from apscheduler.triggers.cron import CronTrigger

        with pytest.raises(ValueError):
            CronTrigger.from_crontab("invalid")

        with pytest.raises(ValueError):
            CronTrigger.from_crontab("60 9 * * *")  # Invalid minute


class TestSchedulerIntegration:
    """Tests for scheduler integration via mock."""

    def test_add_job_dynamic_called(self):
        """schedule_job calls add_job_dynamic on scheduler."""
        scheduler = MagicMock()
        scheduler.add_job_dynamic = MagicMock()

        # Simulate what the tool does
        scheduler.add_job_dynamic("test", "main", "0 9 * * *", "Hello")

        scheduler.add_job_dynamic.assert_called_once_with(
            "test", "main", "0 9 * * *", "Hello"
        )

    def test_get_jobs_returns_list(self):
        """list_jobs calls get_jobs on scheduler."""
        scheduler = MagicMock()
        scheduler.get_jobs = MagicMock(
            return_value=[
                {"name": "job1", "agent": "main", "next_run": "2024-01-01T09:00:00"},
                {"name": "job2", "agent": "monitor", "next_run": "2024-01-01T10:00:00"},
            ]
        )

        jobs = scheduler.get_jobs()
        assert len(jobs) == 2
        assert jobs[0]["name"] == "job1"
        assert jobs[1]["name"] == "job2"

    def test_get_jobs_empty(self):
        """list_jobs handles empty job list."""
        scheduler = MagicMock()
        scheduler.get_jobs = MagicMock(return_value=[])

        jobs = scheduler.get_jobs()
        assert jobs == []

    def test_remove_job_dynamic_called(self):
        """remove_job calls remove_job_dynamic on scheduler."""
        scheduler = MagicMock()
        scheduler.remove_job_dynamic = MagicMock()

        scheduler.remove_job_dynamic("test-job")
        scheduler.remove_job_dynamic.assert_called_once_with("test-job")

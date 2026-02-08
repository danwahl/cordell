"""Tests for scheduler module."""

from unittest.mock import MagicMock

import pytest
import yaml

from config import CordellConfig
from scheduler import Scheduler


class TestSchedulerDynamicJobs:
    """Tests for dynamic job management."""

    @pytest.fixture
    def mock_session_manager(self):
        """Create a mock session manager."""
        manager = MagicMock()
        manager.get_or_create_active_session.return_value = MagicMock(
            session_id="test-session"
        )
        return manager

    @pytest.fixture
    def mock_notification_bus(self):
        """Create a mock notification bus."""
        return MagicMock()

    @pytest.fixture
    def scheduler(self, mock_session_manager, mock_notification_bus):
        """Create a scheduler with mocked dependencies."""
        config = CordellConfig()
        sched = Scheduler(config, mock_session_manager, mock_notification_bus)
        # Start the scheduler so jobs have next_run_time
        sched.start()
        yield sched
        sched.stop()

    def test_add_job_dynamic(self, scheduler):
        """add_job_dynamic adds a job to the scheduler."""
        scheduler.add_job_dynamic(
            name="test-job",
            agent="main",
            schedule="0 9 * * *",
            prompt="Hello",
        )

        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "test-job"
        assert jobs[0]["agent"] == "main"

    def test_add_job_dynamic_updates_config(self, scheduler):
        """add_job_dynamic updates the config."""
        scheduler.add_job_dynamic(
            name="test-job",
            agent="main",
            schedule="0 9 * * *",
            prompt="Hello",
        )

        assert "test-job" in scheduler._config.jobs
        assert scheduler._config.jobs["test-job"].agent == "main"
        assert scheduler._config.jobs["test-job"].schedule == "0 9 * * *"
        assert scheduler._config.jobs["test-job"].prompt == "Hello"

    def test_remove_job_dynamic(self, scheduler):
        """remove_job_dynamic removes a job from the scheduler."""
        # First add a job
        scheduler.add_job_dynamic(
            name="test-job",
            agent="main",
            schedule="0 9 * * *",
            prompt="Hello",
        )
        assert len(scheduler.get_jobs()) == 1

        # Then remove it
        scheduler.remove_job_dynamic("test-job")
        assert len(scheduler.get_jobs()) == 0
        assert "test-job" not in scheduler._config.jobs

    def test_remove_job_dynamic_nonexistent(self, scheduler):
        """remove_job_dynamic handles nonexistent jobs gracefully."""
        # Should not raise
        scheduler.remove_job_dynamic("nonexistent")

    def test_persist_config(self, scheduler, tmp_path, monkeypatch):
        """_persist_config writes jobs to config.yaml."""
        # Patch get_cordell_dir in config module (where it's imported from)
        monkeypatch.setattr("config.get_cordell_dir", lambda: tmp_path)

        scheduler.add_job_dynamic(
            name="test-job",
            agent="main",
            schedule="0 9 * * *",
            prompt="Hello",
        )

        # Verify config file was written
        config_path = tmp_path / "config.yaml"
        assert config_path.exists()

        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert "jobs" in data
        assert "test-job" in data["jobs"]
        assert data["jobs"]["test-job"]["agent"] == "main"
        assert data["jobs"]["test-job"]["schedule"] == "0 9 * * *"
        assert data["jobs"]["test-job"]["prompt"] == "Hello"


class TestSchedulerActiveHours:
    """Tests for active hours filtering."""

    @pytest.fixture
    def scheduler(self):
        """Create a scheduler with mocked dependencies."""
        config = CordellConfig()
        return Scheduler(config, MagicMock(), MagicMock())

    def test_no_active_hours(self, scheduler):
        """None active_hours means always active."""
        assert scheduler._is_in_active_hours(None) is True

    def test_in_active_hours_daytime(self, scheduler, monkeypatch):
        """Returns True when current hour is within daytime range."""
        from datetime import datetime

        # Mock datetime.now() to return 10:00
        mock_now = MagicMock(return_value=datetime(2024, 1, 1, 10, 0))
        monkeypatch.setattr("scheduler.datetime", MagicMock(now=mock_now))

        assert scheduler._is_in_active_hours((6, 22)) is True

    def test_outside_active_hours(self, scheduler, monkeypatch):
        """Returns False when current hour is outside range."""
        from datetime import datetime

        # Mock datetime.now() to return 23:00
        mock_now = MagicMock(return_value=datetime(2024, 1, 1, 23, 0))
        monkeypatch.setattr("scheduler.datetime", MagicMock(now=mock_now))

        assert scheduler._is_in_active_hours((6, 22)) is False

    def test_overnight_range_in_hours(self, scheduler, monkeypatch):
        """Handles overnight ranges like (22, 6)."""
        from datetime import datetime

        # Mock datetime.now() to return 23:00
        mock_now = MagicMock(return_value=datetime(2024, 1, 1, 23, 0))
        monkeypatch.setattr("scheduler.datetime", MagicMock(now=mock_now))

        assert scheduler._is_in_active_hours((22, 6)) is True

    def test_overnight_range_out_of_hours(self, scheduler, monkeypatch):
        """Handles overnight ranges - outside hours."""
        from datetime import datetime

        # Mock datetime.now() to return 10:00
        mock_now = MagicMock(return_value=datetime(2024, 1, 1, 10, 0))
        monkeypatch.setattr("scheduler.datetime", MagicMock(now=mock_now))

        assert scheduler._is_in_active_hours((22, 6)) is False

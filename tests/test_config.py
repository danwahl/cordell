"""Tests for config module."""

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from config import (
    AgentConfig,
    JobConfig,
    SessionsState,
    SessionState,
    create_session_state,
    load_agent_config,
    load_all_agents,
    load_cordell_config,
    load_sessions_state,
    save_sessions_state,
)


class TestAgentConfig:
    """Tests for AgentConfig model."""

    def test_minimal_config(self):
        config = AgentConfig(name="test")
        assert config.name == "test"
        assert config.model == "sonnet"
        assert config.permission_mode == "default"
        assert config.allowed_tools == []
        assert config.env == {}

    def test_full_config(self):
        config = AgentConfig(
            name="main",
            model="opus",
            system_prompt_file="CLAUDE.md",
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Write", "Bash"],
            env={"ANTHROPIC_MODEL": "custom"},
        )
        assert config.name == "main"
        assert config.model == "opus"
        assert config.system_prompt_file == "CLAUDE.md"
        assert config.permission_mode == "acceptEdits"
        assert config.allowed_tools == ["Read", "Write", "Bash"]
        assert config.env == {"ANTHROPIC_MODEL": "custom"}


class TestJobConfig:
    """Tests for JobConfig model."""

    def test_minimal_config(self):
        config = JobConfig(
            session="main",
            schedule="0 8 * * *",
            prompt="Hello",
        )
        assert config.session == "main"
        assert config.schedule == "0 8 * * *"
        assert config.prompt == "Hello"
        assert config.active_hours is None
        assert config.suppress_ok is False

    def test_full_config(self):
        config = JobConfig(
            session="monitor",
            schedule="*/30 * * * *",
            prompt="Check status",
            active_hours=(6, 22),
            suppress_ok=True,
        )
        assert config.active_hours == (6, 22)
        assert config.suppress_ok is True


class TestLoadAgentConfig:
    """Tests for loading agent configs from YAML."""

    def test_load_agent_config(self, tmp_path: Path):
        agent_dir = tmp_path / "main"
        agent_dir.mkdir()

        config_data = {
            "name": "main",
            "model": "opus",
            "allowed_tools": ["Read", "Write"],
        }
        with open(agent_dir / "agent.yaml", "w") as f:
            yaml.dump(config_data, f)

        config = load_agent_config(agent_dir)
        assert config.name == "main"
        assert config.model == "opus"
        assert config.allowed_tools == ["Read", "Write"]

    def test_load_agent_config_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_agent_config(tmp_path / "nonexistent")


class TestLoadAllAgents:
    """Tests for loading all agents from a directory."""

    def test_load_all_agents(self, tmp_path: Path):
        # Create two agents
        for name in ["main", "monitor"]:
            agent_dir = tmp_path / name
            agent_dir.mkdir()
            with open(agent_dir / "agent.yaml", "w") as f:
                yaml.dump({"name": name, "model": "sonnet"}, f)

        agents = load_all_agents(tmp_path)
        assert len(agents) == 2
        assert "main" in agents
        assert "monitor" in agents

    def test_load_all_agents_empty(self, tmp_path: Path):
        agents = load_all_agents(tmp_path)
        assert agents == {}

    def test_load_all_agents_nonexistent(self, tmp_path: Path):
        agents = load_all_agents(tmp_path / "nonexistent")
        assert agents == {}


class TestLoadCordellConfig:
    """Tests for loading Cordell config."""

    def test_load_config_with_jobs(self, tmp_path: Path):
        config_data = {
            "jobs": {
                "morning": {
                    "session": "main",
                    "schedule": "0 8 * * *",
                    "prompt": "Good morning",
                },
            },
            "default_model": "opus",
            "log_level": "DEBUG",
        }
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_cordell_config(config_path)
        assert len(config.jobs) == 1
        assert "morning" in config.jobs
        assert config.jobs["morning"].session == "main"
        assert config.default_model == "opus"
        assert config.log_level == "DEBUG"

    def test_load_config_default(self, tmp_path: Path):
        config = load_cordell_config(tmp_path / "nonexistent.yaml")
        assert config.jobs == {}
        assert config.default_model == "sonnet"


class TestSessionState:
    """Tests for session state persistence."""

    def test_save_and_load_sessions(self, tmp_path: Path, monkeypatch):
        # Patch the state directory
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        monkeypatch.setattr("config.get_state_dir", lambda: state_dir)

        # Create state
        state = SessionsState(
            sessions={
                "test-123": SessionState(
                    session_id="test-123",
                    agent="main",
                    label="main — Jan 1",
                    created_at=datetime(2024, 1, 1, 12, 0, 0),
                ),
            }
        )

        # Save
        save_sessions_state(state)

        # Verify file exists
        state_path = state_dir / "sessions.json"
        assert state_path.exists()

        # Load
        loaded = load_sessions_state()
        assert "test-123" in loaded.sessions
        assert loaded.sessions["test-123"].session_id == "test-123"
        assert loaded.sessions["test-123"].agent == "main"
        assert loaded.sessions["test-123"].label == "main — Jan 1"
        assert loaded.sessions["test-123"].status == "active"

    def test_get_active_session(self):
        """get_active_session returns the most recent active session for an agent."""
        state = SessionsState(
            sessions={
                "old": SessionState(
                    session_id="old",
                    agent="main",
                    label="main — Jan 1",
                    created_at=datetime(2024, 1, 1),
                    status="active",
                ),
                "new": SessionState(
                    session_id="new",
                    agent="main",
                    label="main — Jan 2",
                    created_at=datetime(2024, 1, 2),
                    status="active",
                ),
                "archived": SessionState(
                    session_id="archived",
                    agent="main",
                    label="main — Jan 3",
                    created_at=datetime(2024, 1, 3),
                    status="archived",
                ),
            }
        )
        active = state.get_active_session("main")
        assert active is not None
        assert active.session_id == "new"

    def test_get_active_session_none(self):
        """get_active_session returns None when no active sessions exist."""
        state = SessionsState()
        assert state.get_active_session("main") is None

    def test_get_sessions_for_agent(self):
        """get_sessions_for_agent returns sessions sorted by created_at descending."""
        state = SessionsState(
            sessions={
                "old": SessionState(
                    session_id="old",
                    agent="main",
                    label="main — Jan 1",
                    created_at=datetime(2024, 1, 1),
                ),
                "new": SessionState(
                    session_id="new",
                    agent="main",
                    label="main — Jan 2",
                    created_at=datetime(2024, 1, 2),
                ),
                "other": SessionState(
                    session_id="other",
                    agent="monitor",
                    label="monitor — Jan 1",
                    created_at=datetime(2024, 1, 1),
                ),
            }
        )
        main_sessions = state.get_sessions_for_agent("main")
        assert len(main_sessions) == 2
        assert main_sessions[0].session_id == "new"
        assert main_sessions[1].session_id == "old"


class TestCreateSessionState:
    """Tests for create_session_state helper."""

    def test_creates_state(self):
        """create_session_state creates a session with auto-generated label."""
        state = create_session_state("main", "abc-123")
        assert state.session_id == "abc-123"
        assert state.agent == "main"
        assert state.status == "active"
        assert "main" in state.label
        assert state.created_at is not None

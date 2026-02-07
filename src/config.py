"""Configuration models and loaders for Cordell."""

import os
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Configuration for a single agent."""

    name: str
    model: str = "sonnet"
    system_prompt_file: str | None = None
    permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = (
        "default"
    )
    allowed_tools: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class JobConfig(BaseModel):
    """Configuration for a scheduled job."""

    session: str
    schedule: str  # cron expression
    prompt: str
    active_hours: tuple[int, int] | None = None  # (start_hour, end_hour)
    suppress_ok: bool = False


class CordellConfig(BaseModel):
    """Global Cordell configuration."""

    jobs: dict[str, JobConfig] = Field(default_factory=dict)
    default_model: str = "sonnet"
    log_level: str = "INFO"


class SessionState(BaseModel):
    """Persisted state for a session."""

    session_id: str
    agent: str
    label: str
    created_at: datetime
    status: Literal["active", "archived"] = "active"


class SessionsState(BaseModel):
    """Container for all session states."""

    sessions: dict[str, SessionState] = Field(default_factory=dict)

    def get_active_session(self, agent_name: str) -> SessionState | None:
        """Get the most recent active session for a given agent."""
        active = [
            s
            for s in self.sessions.values()
            if s.agent == agent_name and s.status == "active"
        ]
        if not active:
            return None
        return max(active, key=lambda s: s.created_at)

    def get_sessions_for_agent(self, agent_name: str) -> list[SessionState]:
        """Get all sessions for an agent, sorted by created_at descending."""
        sessions = [s for s in self.sessions.values() if s.agent == agent_name]
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)


def create_session_state(agent_name: str, session_id: str) -> SessionState:
    """Create a new SessionState with auto-generated label and timestamp."""
    now = datetime.now()
    label = f"{agent_name} — {now.strftime('%b %-d')}"
    return SessionState(
        session_id=session_id,
        agent=agent_name,
        label=label,
        created_at=now,
        status="active",
    )


def get_cordell_dir() -> Path:
    """Get the Cordell data directory."""
    return Path(os.environ.get("CORDELL_DIR", Path.home() / ".cordell"))


def get_state_dir() -> Path:
    """Get the state directory."""
    state_dir = get_cordell_dir() / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def get_workspaces_dir() -> Path:
    """Get the workspaces directory."""
    workspaces_dir = get_cordell_dir() / "workspaces"
    workspaces_dir.mkdir(parents=True, exist_ok=True)
    return workspaces_dir


def load_agent_config(agent_dir: Path) -> AgentConfig:
    """Load agent configuration from a directory."""
    config_path = agent_dir / "agent.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Agent config not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    return AgentConfig(**data)


def load_all_agents(agents_dir: Path) -> dict[str, AgentConfig]:
    """Load all agent configurations from the agents directory."""
    agents = {}
    if not agents_dir.exists():
        return agents

    for agent_dir in agents_dir.iterdir():
        if agent_dir.is_dir() and (agent_dir / "agent.yaml").exists():
            config = load_agent_config(agent_dir)
            agents[config.name] = config

    return agents


def load_cordell_config(config_path: Path | None = None) -> CordellConfig:
    """Load the global Cordell configuration."""
    if config_path is None:
        config_path = get_cordell_dir() / "config.yaml"

    if not config_path.exists():
        return CordellConfig()

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    # Convert jobs dict
    if "jobs" in data:
        data["jobs"] = {
            name: JobConfig(**job_data) for name, job_data in data["jobs"].items()
        }

    return CordellConfig(**data)


def load_sessions_state() -> SessionsState:
    """Load persisted session states."""
    state_path = get_state_dir() / "sessions.json"
    if not state_path.exists():
        return SessionsState()

    with open(state_path) as f:
        import json

        data = json.load(f)

    return SessionsState(**data)


def save_sessions_state(state: SessionsState) -> None:
    """Save session states to disk."""
    state_path = get_state_dir() / "sessions.json"
    with open(state_path, "w") as f:
        import json

        json.dump(state.model_dump(mode="json"), f, indent=2, default=str)


def get_agent_system_prompt(agent_config: AgentConfig, agent_dir: Path) -> str | None:
    """Load the system prompt for an agent."""
    if agent_config.system_prompt_file is None:
        return None

    prompt_path = agent_dir / agent_config.system_prompt_file
    if not prompt_path.exists():
        return None

    return prompt_path.read_text()

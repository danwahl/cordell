"""Session manager for Cordell.

Manages ClaudeSDKClient instances, handles concurrency with per-session locks,
and provides an asyncio bridge for Streamlit's synchronous runtime.
"""

import asyncio
import logging
import queue
import threading
from collections.abc import Iterator
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from config import (
    AgentConfig,
    SessionsState,
    create_session_state,
    get_agent_system_prompt,
    get_workspaces_dir,
    load_all_agents,
    load_sessions_state,
    save_sessions_state,
)
from protocols import Message, SessionInfo

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages Claude Agent SDK sessions with concurrency control."""

    def __init__(self, agents_dir: Path):
        """Initialize the session manager.

        Args:
            agents_dir: Path to the agents/ directory containing agent configs.
        """
        self._agents_dir = agents_dir
        self._agents: dict[str, AgentConfig] = {}
        self._clients: dict[str, ClaudeSDKClient] = {}  # Keyed by session_id
        self._locks: dict[str, asyncio.Lock] = {}  # Keyed by session_id
        self._busy: dict[str, bool] = {}  # Keyed by session_id
        self._state: SessionsState = SessionsState()

        # Asyncio event loop in background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # Load agents and state
        self._load_agents()
        self._load_state()

    def _run_loop(self) -> None:
        """Run the asyncio event loop in a background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _load_agents(self) -> None:
        """Load all agent configurations."""
        self._agents = load_all_agents(self._agents_dir)
        logger.info(f"Loaded {len(self._agents)} agents: {list(self._agents.keys())}")

    def _load_state(self) -> None:
        """Load persisted session state."""
        self._state = load_sessions_state()
        logger.info(f"Loaded state for {len(self._state.sessions)} sessions")

    def _save_state(self) -> None:
        """Save session state to disk."""
        save_sessions_state(self._state)

    def get_workspace(self, session_id: str) -> Path | None:
        """Get the workspace directory for a session."""
        session_state = self._state.sessions.get(session_id)
        if session_state is None:
            return None
        workspace = get_workspaces_dir() / session_state.agent
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _build_options(
        self, agent_config: AgentConfig, resume_id: str | None = None
    ) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions from an agent configuration."""
        agent_dir = self._agents_dir / agent_config.name
        system_prompt = get_agent_system_prompt(agent_config, agent_dir)

        workspace = get_workspaces_dir() / agent_config.name
        workspace.mkdir(parents=True, exist_ok=True)

        options = ClaudeAgentOptions(
            model=agent_config.model,
            system_prompt=system_prompt,
            permission_mode=agent_config.permission_mode,
            allowed_tools=agent_config.allowed_tools or None,
            cwd=str(workspace),
            resume=resume_id,
            env=agent_config.env or {},
        )

        return options

    async def _connect_client(
        self, session_id: str, agent_config: AgentConfig
    ) -> ClaudeSDKClient:
        """Connect a new or resumed client for a session."""
        from history import get_session_jsonl_path

        # Only resume if the SDK session file actually exists
        workspace = get_workspaces_dir() / agent_config.name
        jsonl_path = get_session_jsonl_path(session_id, workspace)

        resume_id = None
        if jsonl_path.exists():
            resume_id = session_id
            logger.info(f"Resuming session {session_id}")
        else:
            logger.info(f"Starting new session {session_id}")

        options = self._build_options(agent_config, resume_id)
        client = ClaudeSDKClient(options=options)
        await client.connect()
        logger.info(f"Connected client for session {session_id}")

        self._clients[session_id] = client
        self._locks[session_id] = asyncio.Lock()
        self._busy[session_id] = False

        return client

    async def _get_client(self, session_id: str) -> ClaudeSDKClient:
        """Get or lazily connect a client for a session."""
        if session_id in self._clients:
            return self._clients[session_id]

        # Find the session state to get the agent config
        session_state = self._state.sessions.get(session_id)
        if session_state is None:
            raise ValueError(f"Unknown session: {session_id}")

        agent_config = self._agents.get(session_state.agent)
        if agent_config is None:
            raise ValueError(f"Unknown agent: {session_state.agent}")

        return await self._connect_client(session_id, agent_config)

    def create_session(self, agent_name: str) -> SessionInfo:
        """Create a new session for an agent.

        The session will connect lazily on first message.
        """
        if agent_name not in self._agents:
            raise ValueError(f"Unknown agent: {agent_name}")

        # Generate a temporary session ID - the SDK will assign the real one
        # We use the agent name with a timestamp as a placeholder
        import uuid

        temp_session_id = str(uuid.uuid4())

        session_state = create_session_state(agent_name, temp_session_id)
        self._state.sessions[temp_session_id] = session_state
        self._save_state()

        logger.info(f"Created new session {temp_session_id} for agent {agent_name}")

        return SessionInfo(
            session_id=temp_session_id,
            agent=agent_name,
            label=session_state.label,
            created_at=session_state.created_at,
            status=session_state.status,
            is_busy=False,
        )

    def get_or_create_active_session(self, agent_name: str) -> SessionInfo:
        """Get the active session for an agent, or create one if none exists."""
        active = self._state.get_active_session(agent_name)
        if active:
            return SessionInfo(
                session_id=active.session_id,
                agent=active.agent,
                label=active.label,
                created_at=active.created_at,
                status=active.status,
                is_busy=self._busy.get(active.session_id, False),
            )
        return self.create_session(agent_name)

    async def _stream_message_async(self, session_id: str, content: str):
        """Stream messages as they arrive (async generator)."""
        client = await self._get_client(session_id)

        lock = self._locks[session_id]
        async with lock:
            self._busy[session_id] = True

            try:
                await client.query(content)

                async for msg in client.receive_response():
                    for converted in self._convert_message(msg):
                        yield converted

            except Exception as e:
                logger.error(f"Error sending message to {session_id}: {e}")
                yield Message(type="error", content=str(e))
            finally:
                self._busy[session_id] = False

        yield Message(type="done", content="")

    def _convert_message(self, msg) -> list[Message]:
        """Convert an SDK message to our Message type(s)."""
        class_name = type(msg).__name__
        messages = []

        if class_name == "AssistantMessage":
            content = getattr(msg, "content", "")

            if isinstance(content, str) and content:
                messages.append(Message(type="text", content=content))
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    block_class = type(block).__name__

                    if block_class == "TextBlock":
                        text = getattr(block, "text", "")
                        if text:
                            text_parts.append(text)
                    elif block_class == "ToolUseBlock":
                        if text_parts:
                            messages.append(
                                Message(type="text", content="\n".join(text_parts))
                            )
                            text_parts = []
                        name = getattr(block, "name", None)
                        input_data = getattr(block, "input", None)
                        messages.append(
                            Message(
                                type="tool_use",
                                content=f"Using {name or 'unknown'}",
                                tool_name=name,
                                tool_input=input_data,
                            )
                        )
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            if text_parts:
                                messages.append(
                                    Message(type="text", content="\n".join(text_parts))
                                )
                                text_parts = []
                            messages.append(
                                Message(
                                    type="tool_use",
                                    content=f"Using {block.get('name', 'unknown')}",
                                    tool_name=block.get("name"),
                                    tool_input=block.get("input"),
                                )
                            )

                if text_parts:
                    messages.append(Message(type="text", content="\n".join(text_parts)))

        elif class_name == "ToolResultMessage":
            content = getattr(msg, "content", "")
            messages.append(Message(type="tool_result", content=str(content)[:500]))

        return messages

    def send_message_sync(self, session_id: str, content: str) -> Iterator[Message]:
        """Send a message synchronously (for Streamlit).

        Uses a queue to bridge async streaming to sync iteration.
        """
        result_queue: queue.Queue[Message | None] = queue.Queue()

        async def stream_and_queue():
            try:
                async for msg in self._stream_message_async(session_id, content):
                    result_queue.put(msg)
            except Exception as e:
                result_queue.put(Message(type="error", content=str(e)))
            finally:
                result_queue.put(None)

        asyncio.run_coroutine_threadsafe(stream_and_queue(), self._loop)

        while True:
            msg = result_queue.get()
            if msg is None:
                break
            yield msg

    async def send_message(self, session_id: str, content: str):
        """Send a message asynchronously (streaming)."""
        async for msg in self._stream_message_async(session_id, content):
            yield msg

    def get_sessions_sync(self) -> list[SessionInfo]:
        """Get all sessions across all agents."""
        sessions = []
        for session_id, session_state in self._state.sessions.items():
            sessions.append(
                SessionInfo(
                    session_id=session_id,
                    agent=session_state.agent,
                    label=session_state.label,
                    created_at=session_state.created_at,
                    status=session_state.status,
                    is_busy=self._busy.get(session_id, False),
                )
            )
        # Sort by created_at descending
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions

    async def get_sessions(self) -> list[SessionInfo]:
        """Get all available sessions."""
        return self.get_sessions_sync()

    def get_session(self, session_id: str) -> SessionInfo | None:
        """Get a specific session by ID."""
        session_state = self._state.sessions.get(session_id)
        if session_state is None:
            return None
        return SessionInfo(
            session_id=session_id,
            agent=session_state.agent,
            label=session_state.label,
            created_at=session_state.created_at,
            status=session_state.status,
            is_busy=self._busy.get(session_id, False),
        )

    def get_agents(self) -> list[str]:
        """Get list of available agent names."""
        return list(self._agents.keys())

    def is_busy(self, session_id: str) -> bool:
        """Check if a session is currently processing."""
        return self._busy.get(session_id, False)

    def archive_session(self, session_id: str) -> None:
        """Archive a session (mark as inactive)."""
        if session_id in self._state.sessions:
            self._state.sessions[session_id].status = "archived"
            self._save_state()
            logger.info(f"Archived session {session_id}")

    def unarchive_session(self, session_id: str) -> None:
        """Unarchive a session (mark as active)."""
        if session_id in self._state.sessions:
            self._state.sessions[session_id].status = "active"
            self._save_state()
            logger.info(f"Unarchived session {session_id}")

    async def shutdown(self) -> None:
        """Gracefully shutdown all sessions."""
        logger.info("Shutting down session manager...")

        for session_id, client in self._clients.items():
            try:
                await client.interrupt()
                await client.disconnect()
                logger.info(f"Disconnected client for session {session_id}")
            except Exception as e:
                logger.error(f"Error disconnecting {session_id}: {e}")

        self._clients.clear()
        self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("Session manager shutdown complete")

    def shutdown_sync(self) -> None:
        """Synchronous shutdown wrapper."""
        future = asyncio.run_coroutine_threadsafe(self.shutdown(), self._loop)
        try:
            future.result(timeout=10)
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

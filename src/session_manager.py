"""Session manager for Cordell.

Manages ClaudeSDKClient instances, handles concurrency with per-session locks,
and provides an asyncio bridge for Streamlit's synchronous runtime.
"""

import asyncio
import logging
import os
import queue
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from config import (
    AgentConfig,
    SessionState,
    SessionsState,
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
        self._clients: dict[str, ClaudeSDKClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._busy: dict[str, bool] = {}
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

    def _get_workspace(self, agent_name: str) -> Path:
        """Get the workspace directory for an agent."""
        workspace = get_workspaces_dir() / agent_name
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _build_options(self, agent_config: AgentConfig, session_id: str | None = None) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions from an agent configuration."""
        agent_dir = self._agents_dir / agent_config.name

        # Get system prompt
        system_prompt = get_agent_system_prompt(agent_config, agent_dir)

        # Build options
        options = ClaudeAgentOptions(
            model=agent_config.model,
            system_prompt=system_prompt,
            permission_mode=agent_config.permission_mode,
            allowed_tools=agent_config.allowed_tools if agent_config.allowed_tools else None,
            cwd=str(self._get_workspace(agent_config.name)),
            resume=session_id,
        )

        return options

    async def _get_or_create_client(self, agent_name: str) -> ClaudeSDKClient:
        """Get an existing client or create a new one."""
        if agent_name in self._clients:
            return self._clients[agent_name]

        if agent_name not in self._agents:
            raise ValueError(f"Unknown agent: {agent_name}")

        agent_config = self._agents[agent_name]

        # Check for existing session
        session_id = None
        if agent_name in self._state.sessions:
            session_id = self._state.sessions[agent_name].session_id
            logger.info(f"Resuming session {session_id} for agent {agent_name}")

        # Apply any env var overrides
        old_env = {}
        for key, value in agent_config.env.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value

        try:
            options = self._build_options(agent_config, session_id)
            client = ClaudeSDKClient(options=options)
            self._clients[agent_name] = client
            self._locks[agent_name] = asyncio.Lock()
            self._busy[agent_name] = False
        finally:
            # Restore env vars
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        return client

    async def _send_message_async(self, session: str, content: str) -> list[Message]:
        """Send a message and collect the response (internal async version)."""
        client = await self._get_or_create_client(session)

        # Acquire lock
        lock = self._locks[session]
        async with lock:
            self._busy[session] = True
            messages: list[Message] = []

            try:
                await client.query(content)

                session_id_captured = False
                async for msg in client.receive_response():
                    # Capture session ID from init message
                    if not session_id_captured and hasattr(msg, "subtype"):
                        if msg.subtype == "init" and hasattr(msg, "data"):
                            new_session_id = msg.data.get("session_id")
                            if new_session_id:
                                self._update_session_state(session, new_session_id)
                                session_id_captured = True

                    # Convert SDK message to our Message type
                    converted = self._convert_message(msg)
                    if converted:
                        messages.append(converted)

            except Exception as e:
                logger.error(f"Error sending message to {session}: {e}")
                messages.append(Message(type="error", content=str(e)))
            finally:
                self._busy[session] = False

        messages.append(Message(type="done", content=""))
        return messages

    def _convert_message(self, msg) -> Message | None:
        """Convert an SDK message to our Message type."""
        # Handle different message types from the SDK
        msg_type = getattr(msg, "type", None)

        if msg_type == "assistant":
            content = getattr(msg, "message", {})
            if isinstance(content, dict):
                content_blocks = content.get("content", [])
            else:
                content_blocks = getattr(content, "content", [])

            # Extract text content
            text_parts = []
            for block in content_blocks if isinstance(content_blocks, list) else []:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        return Message(
                            type="tool_use",
                            content=f"Using {block.get('name', 'unknown')}",
                            tool_name=block.get("name"),
                            tool_input=block.get("input"),
                        )

            if text_parts:
                return Message(type="text", content="\n".join(text_parts))

        elif msg_type == "tool_result":
            content = getattr(msg, "content", "")
            return Message(type="tool_result", content=str(content)[:500])

        return None

    def _update_session_state(self, session: str, session_id: str) -> None:
        """Update the session state with a new session ID."""
        self._state.sessions[session] = SessionState(
            session_id=session_id,
            agent=session,
            created_at=datetime.now(),
        )
        self._save_state()
        logger.info(f"Updated session state for {session}: {session_id}")

    def send_message_sync(self, session: str, content: str) -> Iterator[Message]:
        """Send a message synchronously (for Streamlit).

        Uses a queue to bridge async iteration to sync.
        """
        result_queue: queue.Queue[Message | None] = queue.Queue()

        async def run_and_queue():
            try:
                messages = await self._send_message_async(session, content)
                for msg in messages:
                    result_queue.put(msg)
            except Exception as e:
                result_queue.put(Message(type="error", content=str(e)))
            finally:
                result_queue.put(None)  # Signal completion

        # Submit to background loop
        asyncio.run_coroutine_threadsafe(run_and_queue(), self._loop)

        # Yield from queue
        while True:
            msg = result_queue.get()
            if msg is None:
                break
            yield msg

    async def send_message(self, session: str, content: str):
        """Send a message asynchronously."""
        messages = await self._send_message_async(session, content)
        for msg in messages:
            yield msg

    def get_sessions_sync(self) -> list[SessionInfo]:
        """Get all available sessions (synchronous)."""
        sessions = []
        for name, config in self._agents.items():
            session_state = self._state.sessions.get(name)
            sessions.append(
                SessionInfo(
                    name=name,
                    session_id=session_state.session_id if session_state else "",
                    agent=config.name,
                    created_at=session_state.created_at if session_state else datetime.now(),
                    is_busy=self._busy.get(name, False),
                )
            )
        return sessions

    async def get_sessions(self) -> list[SessionInfo]:
        """Get all available sessions."""
        return self.get_sessions_sync()

    def is_busy(self, session: str) -> bool:
        """Check if a session is currently processing."""
        return self._busy.get(session, False)

    def get_session_id(self, session: str) -> str | None:
        """Get the SDK session ID for a named session."""
        if session in self._state.sessions:
            return self._state.sessions[session].session_id
        return None

    async def shutdown(self) -> None:
        """Gracefully shutdown all sessions."""
        logger.info("Shutting down session manager...")

        for name, client in self._clients.items():
            try:
                await client.interrupt()
                await client.disconnect()
                logger.info(f"Disconnected client for {name}")
            except Exception as e:
                logger.error(f"Error disconnecting {name}: {e}")

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

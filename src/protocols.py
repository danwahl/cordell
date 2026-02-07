"""Typed interfaces for Cordell components.

These protocols define the contracts between components, making it trivial
to extract them into separate services later.
"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol


@dataclass
class ToolUseInfo:
    """Information about a tool use in a message."""

    name: str
    input: dict
    output: str | None = None


@dataclass
class TokenUsage:
    """Token usage statistics."""

    input_tokens: int
    output_tokens: int


@dataclass
class HistoryEntry:
    """A single entry in conversation history."""

    uuid: str
    type: Literal["user", "assistant", "system"]
    timestamp: datetime
    content: str
    tool_uses: list[ToolUseInfo] = field(default_factory=list)
    token_usage: TokenUsage | None = None


@dataclass
class SessionInfo:
    """Information about a session."""

    name: str
    session_id: str
    agent: str
    created_at: datetime
    is_busy: bool = False


@dataclass
class Notification:
    """A notification from a session."""

    id: str
    source: str
    timestamp: datetime
    summary: str
    read: bool = False


@dataclass
class Message:
    """A message from the session manager during streaming."""

    type: Literal["text", "tool_use", "tool_result", "error", "done"]
    content: str
    tool_name: str | None = None
    tool_input: dict | None = None


class SessionManagerProtocol(Protocol):
    """Protocol for session management."""

    async def send_message(
        self, session: str, content: str
    ) -> AsyncIterator[Message]:
        """Send a message to a session and stream the response."""
        ...

    def send_message_sync(
        self, session: str, content: str
    ) -> Iterator[Message]:
        """Synchronous wrapper for send_message."""
        ...

    async def get_sessions(self) -> list[SessionInfo]:
        """Get all available sessions."""
        ...

    def get_sessions_sync(self) -> list[SessionInfo]:
        """Synchronous wrapper for get_sessions."""
        ...

    def is_busy(self, session: str) -> bool:
        """Check if a session is currently processing."""
        ...

    async def shutdown(self) -> None:
        """Gracefully shutdown all sessions."""
        ...


class HistoryReaderProtocol(Protocol):
    """Protocol for reading conversation history."""

    def get_history(self, session: str, limit: int = 200) -> list[HistoryEntry]:
        """Get conversation history for a session."""
        ...

    def get_session_id(self, session: str) -> str | None:
        """Get the SDK session ID for a named session."""
        ...


class NotificationBusProtocol(Protocol):
    """Protocol for the notification system."""

    def post(self, notification: Notification) -> None:
        """Post a new notification."""
        ...

    def get_unread(self) -> list[Notification]:
        """Get all unread notifications."""
        ...

    def get_all(self, limit: int = 50) -> list[Notification]:
        """Get all notifications, most recent first."""
        ...

    def mark_read(self, notification_id: str) -> None:
        """Mark a notification as read."""
        ...

    def mark_all_read(self) -> None:
        """Mark all notifications as read."""
        ...

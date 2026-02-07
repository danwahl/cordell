"""JSONL history parser for Claude Agent SDK session files.

This module reads the SDK's JSONL session files as the single source of truth
for conversation history. If the format changes, this is the only file to update.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from protocols import HistoryEntry, TokenUsage, ToolUseInfo

logger = logging.getLogger(__name__)


@dataclass
class HistoryCache:
    """Cache for parsed history entries."""

    mtime: float
    entries: list[HistoryEntry]


_cache: dict[str, HistoryCache] = {}


def encode_project_path(workspace: Path) -> str:
    """Encode a workspace path for the SDK's project directory naming.

    The SDK uses the absolute path with "/" replaced by "-".
    Example: /home/dan/project -> -home-dan-project
    """
    return str(workspace.absolute()).replace("/", "-")


def get_claude_projects_dir() -> Path:
    """Get the Claude SDK projects directory."""
    return Path.home() / ".claude" / "projects"


def get_session_dir(workspace: Path) -> Path:
    """Get the session directory for a workspace."""
    return get_claude_projects_dir() / encode_project_path(workspace)


def get_session_jsonl_path(session_id: str, workspace: Path) -> Path:
    """Get the JSONL file path for a session."""
    return get_session_dir(workspace) / f"{session_id}.jsonl"


def parse_timestamp(ts: str) -> datetime:
    """Parse an ISO timestamp from the JSONL format."""
    # Handle both formats: with and without milliseconds
    for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    # Fallback: use fromisoformat with Z replaced
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def extract_text_content(content: list | str) -> str:
    """Extract text content from a message content field.

    Content can be a string or a list of content blocks.
    """
    if isinstance(content, str):
        return content

    text_parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "thinking":
                # Optionally include thinking blocks
                pass
        elif isinstance(block, str):
            text_parts.append(block)

    return "\n".join(text_parts)


def extract_tool_uses(content: list) -> list[ToolUseInfo]:
    """Extract tool use information from message content blocks."""
    tool_uses = []

    if not isinstance(content, list):
        return tool_uses

    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_uses.append(
                ToolUseInfo(
                    name=block.get("name", "unknown"),
                    input=block.get("input", {}),
                )
            )

    return tool_uses


def parse_jsonl_entry(line: str) -> HistoryEntry | None:
    """Parse a single JSONL line into a HistoryEntry.

    Returns None if the line cannot be parsed or should be skipped.
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSONL line")
        return None

    entry_type = data.get("type")
    if entry_type not in ("user", "assistant", "system"):
        return None

    message = data.get("message", {})
    content = message.get("content", "")
    uuid = data.get("uuid", "")
    timestamp_str = data.get("timestamp", "")

    try:
        timestamp = parse_timestamp(timestamp_str) if timestamp_str else datetime.now()
    except Exception:
        timestamp = datetime.now()

    # Extract text content
    text_content = extract_text_content(content)

    # Extract tool uses for assistant messages
    tool_uses = []
    if entry_type == "assistant":
        tool_uses = extract_tool_uses(content)

    # Extract token usage
    token_usage = None
    usage = message.get("usage")
    if usage:
        token_usage = TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    return HistoryEntry(
        uuid=uuid,
        type=entry_type,
        timestamp=timestamp,
        content=text_content,
        tool_uses=tool_uses,
        token_usage=token_usage,
    )


def get_history(
    session_id: str, workspace: Path, limit: int = 200
) -> list[HistoryEntry]:
    """Get conversation history for a session.

    Reads the SDK's JSONL file and returns parsed entries.
    Uses mtime-based caching to avoid re-parsing unchanged files.
    Deduplicates entries by uuid (workaround for SDK stream-json bug).
    """
    jsonl_path = get_session_jsonl_path(session_id, workspace)

    if not jsonl_path.exists():
        return []

    # Check cache
    cache_key = str(jsonl_path)
    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        return []

    if cache_key in _cache and _cache[cache_key].mtime == mtime:
        entries = _cache[cache_key].entries
        return entries[-limit:] if limit else entries

    # Parse file
    entries: list[HistoryEntry] = []
    seen_uuids: set[str] = set()

    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                entry = parse_jsonl_entry(line)
                if entry is None:
                    continue

                # Deduplicate by uuid
                if entry.uuid and entry.uuid in seen_uuids:
                    continue
                if entry.uuid:
                    seen_uuids.add(entry.uuid)

                entries.append(entry)
    except OSError as e:
        logger.error(f"Failed to read session history: {e}")
        return []

    # Update cache
    _cache[cache_key] = HistoryCache(mtime=mtime, entries=entries)

    return entries[-limit:] if limit else entries


def clear_cache() -> None:
    """Clear the history cache."""
    _cache.clear()


class HistoryReader:
    """History reader implementation that conforms to HistoryReaderProtocol."""

    def __init__(self, workspace: Path, session_ids: dict[str, str]):
        """Initialize with workspace path and session name to ID mapping."""
        self._workspace = workspace
        self._session_ids = session_ids

    def get_history(self, session: str, limit: int = 200) -> list[HistoryEntry]:
        """Get conversation history for a named session."""
        session_id = self._session_ids.get(session)
        if session_id is None:
            return []
        return get_history(session_id, self._workspace, limit)

    def get_session_id(self, session: str) -> str | None:
        """Get the SDK session ID for a named session."""
        return self._session_ids.get(session)

    def update_session_id(self, session: str, session_id: str) -> None:
        """Update the session ID mapping."""
        self._session_ids[session] = session_id

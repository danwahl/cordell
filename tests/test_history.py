"""Tests for history module."""

import json
from pathlib import Path

from history import (
    HistoryReader,
    clear_cache,
    encode_project_path,
    extract_text_content,
    extract_tool_uses,
    get_history,
    get_session_dir,
    get_session_jsonl_path,
    parse_jsonl_entry,
    parse_timestamp,
)


class TestEncodeProjectPath:
    """Tests for encode_project_path."""

    def test_simple_path(self):
        path = Path("/home/dan/project")
        result = encode_project_path(path)
        assert "/" not in result
        assert result.startswith("-home-")

    def test_absolute_path(self, tmp_path: Path):
        result = encode_project_path(tmp_path)
        assert "/" not in result

    def test_hidden_directory(self):
        """SDK encodes dots as dashes for hidden directories."""
        path = Path("/home/dan/.cordell/workspaces/main")
        result = encode_project_path(path)
        assert "." not in result
        assert "-home-dan--cordell-workspaces-main" == result


class TestGetSessionDir:
    """Tests for get_session_dir."""

    def test_returns_path(self, tmp_path: Path):
        result = get_session_dir(tmp_path)
        assert isinstance(result, Path)
        assert ".claude" in str(result)
        assert "projects" in str(result)


class TestGetSessionJsonlPath:
    """Tests for get_session_jsonl_path."""

    def test_returns_jsonl_path(self, tmp_path: Path):
        result = get_session_jsonl_path("session-123", tmp_path)
        assert result.suffix == ".jsonl"
        assert "session-123" in str(result)


class TestParseTimestamp:
    """Tests for parse_timestamp."""

    def test_with_milliseconds(self):
        ts = "2024-01-15T10:30:45.123Z"
        result = parse_timestamp(ts)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_without_milliseconds(self):
        ts = "2024-01-15T10:30:45Z"
        result = parse_timestamp(ts)
        assert result.year == 2024

    def test_iso_format(self):
        ts = "2024-01-15T10:30:45+00:00"
        result = parse_timestamp(ts)
        assert result.year == 2024


class TestExtractTextContent:
    """Tests for extract_text_content."""

    def test_string_content(self):
        result = extract_text_content("Hello world")
        assert result == "Hello world"

    def test_text_blocks(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = extract_text_content(content)
        assert "Hello" in result
        assert "World" in result

    def test_mixed_blocks(self):
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "tool_use", "name": "Bash", "input": {}},
            {"type": "text", "text": "World"},
        ]
        result = extract_text_content(content)
        assert "Hello" in result
        assert "World" in result
        # tool_use should not appear in text
        assert "Bash" not in result

    def test_empty_list(self):
        result = extract_text_content([])
        assert result == ""


class TestExtractToolUses:
    """Tests for extract_tool_uses."""

    def test_no_tools(self):
        content = [{"type": "text", "text": "Hello"}]
        result = extract_tool_uses(content)
        assert result == []

    def test_with_tools(self):
        content = [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            {"type": "text", "text": "Result"},
            {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/test"}},
        ]
        result = extract_tool_uses(content)
        assert len(result) == 2
        assert result[0].name == "Bash"
        assert result[0].input == {"command": "ls"}
        assert result[1].name == "Read"

    def test_string_content(self):
        result = extract_tool_uses("not a list")
        assert result == []


class TestParseJsonlEntry:
    """Tests for parse_jsonl_entry."""

    def test_user_message(self):
        line = json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "Hello"},
                "uuid": "abc-123",
                "timestamp": "2024-01-15T10:00:00Z",
            }
        )
        result = parse_jsonl_entry(line)
        assert result is not None
        assert result.type == "user"
        assert result.content == "Hello"
        assert result.uuid == "abc-123"

    def test_assistant_message(self):
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hi there!"}],
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
                "uuid": "def-456",
                "timestamp": "2024-01-15T10:00:05Z",
            }
        )
        result = parse_jsonl_entry(line)
        assert result is not None
        assert result.type == "assistant"
        assert result.content == "Hi there!"
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 100
        assert result.token_usage.output_tokens == 50

    def test_assistant_with_tool_use(self):
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        },
                    ],
                },
                "uuid": "ghi-789",
                "timestamp": "2024-01-15T10:00:10Z",
            }
        )
        result = parse_jsonl_entry(line)
        assert result is not None
        assert len(result.tool_uses) == 1
        assert result.tool_uses[0].name == "Bash"

    def test_invalid_json(self):
        result = parse_jsonl_entry("not valid json")
        assert result is None

    def test_unknown_type(self):
        line = json.dumps({"type": "unknown", "data": {}})
        result = parse_jsonl_entry(line)
        assert result is None


class TestGetHistory:
    """Tests for get_history."""

    def test_nonexistent_file(self, tmp_path: Path):
        result = get_history("nonexistent", tmp_path)
        assert result == []

    def test_read_history(self, tmp_path: Path, monkeypatch):
        # Clear cache
        clear_cache()

        # Create a mock session dir
        session_dir = tmp_path / "projects" / encode_project_path(tmp_path)
        session_dir.mkdir(parents=True)

        # Patch get_session_dir to return our mock
        monkeypatch.setattr(
            "history.get_session_dir",
            lambda w: tmp_path / "projects" / encode_project_path(w),
        )

        # Create JSONL file
        jsonl_path = session_dir / "session-123.jsonl"
        with open(jsonl_path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"content": "Hello"},
                        "uuid": "msg-1",
                        "timestamp": "2024-01-15T10:00:00Z",
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "Hi!"}]},
                        "uuid": "msg-2",
                        "timestamp": "2024-01-15T10:00:05Z",
                    }
                )
                + "\n"
            )

        result = get_history("session-123", tmp_path)
        assert len(result) == 2
        assert result[0].content == "Hello"
        assert result[1].content == "Hi!"

    def test_deduplication(self, tmp_path: Path, monkeypatch):
        clear_cache()

        session_dir = tmp_path / "projects" / encode_project_path(tmp_path)
        session_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "history.get_session_dir",
            lambda w: tmp_path / "projects" / encode_project_path(w),
        )

        # Create JSONL with duplicate UUIDs
        jsonl_path = session_dir / "session-123.jsonl"
        with open(jsonl_path, "w") as f:
            for _ in range(3):
                f.write(
                    json.dumps(
                        {
                            "type": "user",
                            "message": {"content": "Hello"},
                            "uuid": "same-uuid",
                            "timestamp": "2024-01-15T10:00:00Z",
                        }
                    )
                    + "\n"
                )

        result = get_history("session-123", tmp_path)
        # Should deduplicate to 1
        assert len(result) == 1

    def test_limit(self, tmp_path: Path, monkeypatch):
        clear_cache()

        session_dir = tmp_path / "projects" / encode_project_path(tmp_path)
        session_dir.mkdir(parents=True)
        monkeypatch.setattr(
            "history.get_session_dir",
            lambda w: tmp_path / "projects" / encode_project_path(w),
        )

        jsonl_path = session_dir / "session-123.jsonl"
        with open(jsonl_path, "w") as f:
            for i in range(10):
                f.write(
                    json.dumps(
                        {
                            "type": "user",
                            "message": {"content": f"Message {i}"},
                            "uuid": f"msg-{i}",
                            "timestamp": "2024-01-15T10:00:00Z",
                        }
                    )
                    + "\n"
                )

        result = get_history("session-123", tmp_path, limit=5)
        assert len(result) == 5
        # Should be the last 5 messages
        assert result[0].content == "Message 5"


class TestHistoryReader:
    """Tests for HistoryReader class."""

    def test_get_session_id(self):
        reader = HistoryReader(
            workspace=Path("/tmp"),
            session_ids={"main": "session-123", "monitor": "session-456"},
        )
        assert reader.get_session_id("main") == "session-123"
        assert reader.get_session_id("monitor") == "session-456"
        assert reader.get_session_id("unknown") is None

    def test_update_session_id(self):
        reader = HistoryReader(
            workspace=Path("/tmp"),
            session_ids={},
        )
        reader.update_session_id("main", "session-new")
        assert reader.get_session_id("main") == "session-new"

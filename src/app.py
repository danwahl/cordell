"""Streamlit UI for Cordell.

Provides a chat interface for interacting with Claude agents, with session
management, notifications, and tool use visualization.
"""

import signal
import sys
from pathlib import Path

import streamlit as st

from history import get_history
from logging_utils import setup_logging
from notifications import NotificationBus
from protocols import SessionInfo
from session_manager import SessionManager

# Initialize logging
setup_logging()

# Page config
st.set_page_config(
    page_title="Cordell",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_agents_dir() -> Path:
    """Get the agents directory."""
    # Look for agents/ relative to the src/ directory
    src_dir = Path(__file__).parent
    project_dir = src_dir.parent
    return project_dir / "agents"


@st.cache_resource
def get_session_manager() -> SessionManager:
    """Get or create the session manager (singleton)."""
    agents_dir = get_agents_dir()
    return SessionManager(agents_dir)


@st.cache_resource
def get_notification_bus() -> NotificationBus:
    """Get or create the notification bus (singleton)."""
    return NotificationBus()


@st.cache_resource
def get_scheduler(_manager: SessionManager):
    """Get or create the scheduler (singleton).

    Also creates and injects the Cordell MCP server into the session manager.
    """
    from config import load_cordell_config
    from cordell_tools import create_cordell_mcp_server
    from scheduler import Scheduler

    config = load_cordell_config()
    bus = get_notification_bus()
    scheduler = Scheduler(config, _manager, bus)

    # Create and inject Cordell MCP tools
    cordell_server = create_cordell_mcp_server(scheduler)
    _manager.set_cordell_mcp_server(cordell_server)

    scheduler.start()
    return scheduler


def setup_signal_handlers(manager: SessionManager) -> None:
    """Set up signal handlers for graceful shutdown."""

    def handle_signal(signum, frame):
        st.toast("Shutting down...")
        manager.shutdown_sync()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


def render_sidebar(manager: SessionManager, bus: NotificationBus) -> SessionInfo | None:
    """Render the sidebar with session selector and notifications.

    Returns the selected SessionInfo or None if no sessions exist.
    """
    with st.sidebar:
        st.title("Cordell")

        # Get agents and sessions
        agents = manager.get_agents()
        sessions = manager.get_sessions_sync()

        if not agents:
            st.warning("No agents configured. Add agents to the agents/ directory.")
            return None

        # Prefer "main" agent, otherwise use first available
        default_agent = "main" if "main" in agents else agents[0]

        # Group sessions by agent
        sessions_by_agent: dict[str, list[SessionInfo]] = {
            agent: [] for agent in agents
        }
        for session in sessions:
            if session.agent in sessions_by_agent:
                sessions_by_agent[session.agent].append(session)

        # Initialize selected session in state
        if "selected_session_id" not in st.session_state:
            # Default to most recent active session for default agent
            if sessions_by_agent[default_agent]:
                active = [
                    s for s in sessions_by_agent[default_agent] if s.status == "active"
                ]
                if active:
                    st.session_state.selected_session_id = active[0].session_id
                else:
                    st.session_state.selected_session_id = None
            else:
                st.session_state.selected_session_id = None

        # New session button with agent selector
        col1, col2 = st.columns([3, 1])
        with col1:
            new_agent = st.selectbox(
                "Agent",
                agents,
                index=agents.index(default_agent),
                label_visibility="collapsed",
            )
        with col2:
            if st.button("➕", help="New session"):
                new_session = manager.create_session(new_agent)
                st.session_state.selected_session_id = new_session.session_id
                st.rerun()

        st.divider()

        # Session list as clickable items
        selected_session = None
        for session in sessions:
            is_selected = session.session_id == st.session_state.selected_session_id
            if is_selected:
                selected_session = session

            # Build label with icons
            icon = "📦 " if session.status == "archived" else ""
            label = f"{icon}{session.label}"

            # Use button styling for selection
            if st.button(
                label,
                key=f"session_{session.session_id}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                st.session_state.selected_session_id = session.session_id
                st.rerun()

        if not sessions:
            st.caption("No sessions yet. Click ➕ to start.")

        # Show actions for selected session
        if selected_session:
            st.divider()

            # Show busy indicator
            if selected_session.is_busy:
                st.info("⏳ Processing...")

            # Archive/unarchive button
            if selected_session.status == "active":
                if st.button("📦 Archive", key="archive_btn"):
                    manager.archive_session(selected_session.session_id)
                    st.rerun()
            else:
                if st.button("📂 Unarchive", key="unarchive_btn"):
                    manager.unarchive_session(selected_session.session_id)
                    st.rerun()

        st.divider()

        # Notifications
        unread_count = bus.unread_count
        notification_label = (
            f"Notifications ({unread_count})" if unread_count else "Notifications"
        )

        with st.expander(notification_label, expanded=unread_count > 0):
            notifications = bus.get_all(limit=20)

            if not notifications:
                st.caption("No notifications")
            else:
                if unread_count > 0:
                    if st.button("Mark all read", use_container_width=True):
                        bus.mark_all_read()
                        st.rerun()

                for notification in notifications:
                    icon = "📬" if not notification.read else "📭"
                    summary = notification.summary[:100]
                    st.markdown(f"{icon} **{notification.source}**: {summary}")
                    st.caption(notification.timestamp.strftime("%Y-%m-%d %H:%M"))

                    if not notification.read:
                        if st.button("Mark read", key=f"read_{notification.id}"):
                            bus.mark_read(notification.id)
                            st.rerun()

        return selected_session


def get_messages_key(session_id: str) -> str:
    """Get the session state key for a session's messages."""
    return f"messages_{session_id}"


def init_messages(session_id: str, manager: SessionManager) -> None:
    """Load messages from JSONL history (source of truth).

    Always rebuilds from JSONL - the mtime cache in history.py makes this cheap.
    """
    key = get_messages_key(session_id)
    messages: list[dict] = []

    # Get workspace for this session
    workspace = manager.get_workspace(session_id)
    if workspace:
        history = get_history(session_id, workspace, limit=100)

        for entry in history:
            if entry.type == "user" and entry.content and entry.content.strip():
                messages.append({"role": "user", "content": entry.content})
            elif entry.type == "assistant" and (entry.content or entry.tool_uses):
                # Merge consecutive assistant messages (SDK stores them separately)
                if messages and messages[-1]["role"] == "assistant":
                    prev = messages[-1]
                    if entry.content:
                        if prev["content"]:
                            prev["content"] += "\n" + entry.content
                        else:
                            prev["content"] = entry.content
                    prev["tool_uses"].extend(entry.tool_uses)
                else:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": entry.content or "",
                            "tool_uses": list(entry.tool_uses),
                        }
                    )

    st.session_state[key] = messages


def display_messages(session_id: str) -> None:
    """Display all messages for a session."""
    key = get_messages_key(session_id)
    messages = st.session_state.get(key, [])

    if not messages:
        st.caption("No conversation history yet. Send a message to start!")
        return

    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Show tool uses for assistant messages
            tool_uses = msg.get("tool_uses", [])
            for tool in tool_uses:
                with st.expander(f"🔧 {tool.name}"):
                    st.json(tool.input)
                    if tool.output:
                        st.text(tool.output[:500])


def stream_response(manager: SessionManager, session_id: str, content: str) -> str:
    """Stream the response and return the full text."""
    full_response = ""

    with st.chat_message("assistant"):
        message_placeholder = st.empty()

        for msg in manager.send_message_sync(session_id, content):
            if msg.type == "text":
                full_response += msg.content
                message_placeholder.markdown(full_response + "▌")
            elif msg.type == "tool_use":
                with st.expander(f"🔧 {msg.tool_name}", expanded=False):
                    if msg.tool_input:
                        st.json(msg.tool_input)
            elif msg.type == "tool_result":
                st.caption(f"Result: {msg.content[:200]}...")
            elif msg.type == "error":
                st.error(msg.content)
            elif msg.type == "done":
                break

        # Final render without cursor
        if full_response:
            message_placeholder.markdown(full_response)

    return full_response


def main() -> None:
    """Main application entry point."""
    # Initialize components
    manager = get_session_manager()
    bus = get_notification_bus()

    # Initialize scheduler (also injects Cordell MCP tools into manager)
    # The _ assignment suppresses the "unused variable" warning
    _ = get_scheduler(manager)

    # Set up signal handlers (only works in main thread)
    try:
        setup_signal_handlers(manager)
    except ValueError:
        # Signal handlers can only be set in main thread
        pass

    # Render sidebar and get selected session
    selected_session = render_sidebar(manager, bus)

    if not selected_session:
        st.info("Configure agents to get started.")
        return

    # Main chat area - show session label and status
    header = f"Chat: {selected_session.label}"
    if selected_session.status == "archived":
        header += " (archived)"
    st.header(header)

    # Initialize messages from history
    init_messages(selected_session.session_id, manager)

    # Display existing messages
    display_messages(selected_session.session_id)

    # Chat input - disabled for archived sessions
    is_archived = selected_session.status == "archived"
    is_busy = manager.is_busy(selected_session.session_id)

    if is_archived:
        st.info("This session is archived. Unarchive it to send messages.")
    elif prompt := st.chat_input("Send a message...", disabled=is_busy):
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Stream response (JSONL is the source of truth, no need to append to state)
        stream_response(manager, selected_session.session_id, prompt)


if __name__ == "__main__":
    main()

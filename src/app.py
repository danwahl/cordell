"""Streamlit UI for Cordell.

Provides a chat interface for interacting with Claude agents, with session
management, notifications, and tool use visualization.
"""

import signal
import sys
from pathlib import Path

import streamlit as st

from config import get_workspaces_dir
from history import get_history
from logging_utils import setup_logging
from notifications import NotificationBus
from protocols import Message
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


def setup_signal_handlers(manager: SessionManager) -> None:
    """Set up signal handlers for graceful shutdown."""

    def handle_signal(signum, frame):
        st.toast("Shutting down...")
        manager.shutdown_sync()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


def render_sidebar(manager: SessionManager, bus: NotificationBus) -> str | None:
    """Render the sidebar with session selector and notifications."""
    with st.sidebar:
        st.title("Cordell")

        # Session selector
        st.subheader("Sessions")
        sessions = manager.get_sessions_sync()

        if not sessions:
            st.warning("No agents configured. Add agents to the agents/ directory.")
            return None

        session_names = [s.name for s in sessions]
        selected = st.radio(
            "Select session",
            session_names,
            label_visibility="collapsed",
        )

        # Show busy indicator for selected session
        for session in sessions:
            if session.name == selected and session.is_busy:
                st.info("⏳ Processing...")

        st.divider()

        # Notifications
        unread_count = bus.unread_count
        notification_label = f"Notifications ({unread_count})" if unread_count else "Notifications"

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
                    st.markdown(
                        f"{icon} **{notification.source}**: {notification.summary[:100]}"
                    )
                    st.caption(notification.timestamp.strftime("%Y-%m-%d %H:%M"))

                    if not notification.read:
                        if st.button("Mark read", key=f"read_{notification.id}"):
                            bus.mark_read(notification.id)
                            st.rerun()

        return selected


def get_messages_key(session_name: str) -> str:
    """Get the session state key for a session's messages."""
    return f"messages_{session_name}"


def init_messages(session_name: str, manager: SessionManager) -> None:
    """Initialize messages from history if not already loaded."""
    key = get_messages_key(session_name)

    if key not in st.session_state:
        # Load from history on first access
        session_id = manager.get_session_id(session_name)
        messages = []

        if session_id:
            workspace = get_workspaces_dir() / session_name
            history = get_history(session_id, workspace, limit=100)

            for entry in history:
                if entry.type == "user" and entry.content and entry.content.strip():
                    messages.append({"role": "user", "content": entry.content})
                elif entry.type == "assistant" and entry.content:
                    messages.append({
                        "role": "assistant",
                        "content": entry.content,
                        "tool_uses": entry.tool_uses,
                    })

        st.session_state[key] = messages


def display_messages(session_name: str) -> None:
    """Display all messages for a session."""
    key = get_messages_key(session_name)
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


def stream_response(manager: SessionManager, session: str, content: str) -> str:
    """Stream the response and return the full text."""
    full_response = ""

    with st.chat_message("assistant"):
        message_placeholder = st.empty()

        for msg in manager.send_message_sync(session, content):
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

    # Main chat area
    st.header(f"Chat with {selected_session}")

    # Initialize messages from history
    init_messages(selected_session, manager)

    # Display existing messages
    display_messages(selected_session)

    # Chat input
    if prompt := st.chat_input("Send a message...", disabled=manager.is_busy(selected_session)):
        # Add user message to session state
        key = get_messages_key(selected_session)
        st.session_state[key].append({"role": "user", "content": prompt})

        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Stream response and add to session state
        response = stream_response(manager, selected_session, prompt)
        if response:
            st.session_state[key].append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()

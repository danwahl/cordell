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

        # Group sessions by agent
        sessions_by_agent: dict[str, list[SessionInfo]] = {
            agent: [] for agent in agents
        }
        for session in sessions:
            if session.agent in sessions_by_agent:
                sessions_by_agent[session.agent].append(session)

        # Build session lookup and options
        session_lookup: dict[str, SessionInfo] = {}
        session_options: list[str] = []

        for agent in agents:
            agent_sessions = sessions_by_agent[agent]
            if agent_sessions:
                for session in agent_sessions:
                    label = session.label
                    if session.status == "archived":
                        label = f"📦 {label}"
                    session_lookup[label] = session
                    session_options.append(label)
            else:
                # No sessions yet for this agent - create one on first use
                pass

        # Initialize selected session in state
        if "selected_session_id" not in st.session_state:
            # Default to most recent active session for first agent, or create one
            for agent in agents:
                if sessions_by_agent[agent]:
                    active = [
                        s for s in sessions_by_agent[agent] if s.status == "active"
                    ]
                    if active:
                        st.session_state.selected_session_id = active[0].session_id
                        break
            else:
                # No active sessions - will create on first agent selection
                st.session_state.selected_session_id = None

        st.subheader("Sessions")

        # Agent selector for new sessions
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_agent = st.selectbox(
                "Agent",
                agents,
                label_visibility="collapsed",
            )
        with col2:
            if st.button("➕", help="New session"):
                new_session = manager.create_session(selected_agent)
                st.session_state.selected_session_id = new_session.session_id
                st.rerun()

        # Session list
        if session_options:
            # Find current selection label
            current_label = None
            for label, session in session_lookup.items():
                if session.session_id == st.session_state.selected_session_id:
                    current_label = label
                    break

            # If current selection not in options, default to first
            if current_label not in session_options and session_options:
                current_label = session_options[0]
                st.session_state.selected_session_id = session_lookup[
                    current_label
                ].session_id

            selected_label = st.radio(
                "Select session",
                session_options,
                index=session_options.index(current_label) if current_label else 0,
                label_visibility="collapsed",
            )

            selected_session = session_lookup.get(selected_label)
            if selected_session:
                st.session_state.selected_session_id = selected_session.session_id

                # Show busy indicator
                if selected_session.is_busy:
                    st.info("⏳ Processing...")

                # Archive/unarchive button
                if selected_session.status == "active":
                    if st.button(
                        "📦 Archive", key="archive_btn", use_container_width=True
                    ):
                        manager.archive_session(selected_session.session_id)
                        st.rerun()
                else:
                    if st.button(
                        "📂 Unarchive", key="unarchive_btn", use_container_width=True
                    ):
                        manager.unarchive_session(selected_session.session_id)
                        st.rerun()
        else:
            # No sessions exist yet - create one for the first agent
            st.caption("No sessions yet.")
            if st.button("Create first session", use_container_width=True):
                new_session = manager.create_session(agents[0])
                st.session_state.selected_session_id = new_session.session_id
                st.rerun()
            selected_session = None

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
    """Initialize messages from history if not already loaded."""
    key = get_messages_key(session_id)

    if key not in st.session_state:
        messages = []

        # Get workspace for this session
        workspace = manager.get_workspace(session_id)
        if workspace:
            history = get_history(session_id, workspace, limit=100)

            for entry in history:
                if entry.type == "user" and entry.content and entry.content.strip():
                    messages.append({"role": "user", "content": entry.content})
                elif entry.type == "assistant" and entry.content:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": entry.content,
                            "tool_uses": entry.tool_uses,
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
        # Add user message to session state
        key = get_messages_key(selected_session.session_id)
        st.session_state[key].append({"role": "user", "content": prompt})

        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Stream response and add to session state
        response = stream_response(manager, selected_session.session_id, prompt)
        if response:
            st.session_state[key].append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()

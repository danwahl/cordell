"""Tests for notifications module."""

from datetime import datetime
from pathlib import Path

import pytest

from notifications import NotificationBus
from protocols import Notification


class TestNotificationBus:
    """Tests for NotificationBus."""

    @pytest.fixture
    def bus(self, tmp_path: Path) -> NotificationBus:
        """Create a notification bus with a temp state file."""
        return NotificationBus(state_path=tmp_path / "notifications.json")

    def test_post_notification(self, bus: NotificationBus):
        notification = Notification(
            id="test-1",
            source="main",
            timestamp=datetime.now(),
            summary="Test notification",
        )
        bus.post(notification)

        all_notifications = bus.get_all()
        assert len(all_notifications) == 1
        assert all_notifications[0].id == "test-1"

    def test_create_and_post(self, bus: NotificationBus):
        notification = bus.create_and_post(
            source="monitor",
            summary="Alert message",
        )

        assert notification.id  # Should have assigned ID
        assert notification.source == "monitor"
        assert notification.summary == "Alert message"
        assert not notification.read

        all_notifications = bus.get_all()
        assert len(all_notifications) == 1

    def test_get_unread(self, bus: NotificationBus):
        # Post some notifications
        bus.create_and_post("main", "Message 1")
        bus.create_and_post("main", "Message 2")

        unread = bus.get_unread()
        assert len(unread) == 2

    def test_mark_read(self, bus: NotificationBus):
        notification = bus.create_and_post("main", "Message")

        bus.mark_read(notification.id)

        unread = bus.get_unread()
        assert len(unread) == 0

        all_notifications = bus.get_all()
        assert len(all_notifications) == 1
        assert all_notifications[0].read is True

    def test_mark_all_read(self, bus: NotificationBus):
        bus.create_and_post("main", "Message 1")
        bus.create_and_post("main", "Message 2")
        bus.create_and_post("main", "Message 3")

        bus.mark_all_read()

        unread = bus.get_unread()
        assert len(unread) == 0

    def test_unread_count(self, bus: NotificationBus):
        assert bus.unread_count == 0

        bus.create_and_post("main", "Message 1")
        assert bus.unread_count == 1

        bus.create_and_post("main", "Message 2")
        assert bus.unread_count == 2

        bus.mark_all_read()
        assert bus.unread_count == 0

    def test_get_all_limit(self, bus: NotificationBus):
        for i in range(10):
            bus.create_and_post("main", f"Message {i}")

        result = bus.get_all(limit=5)
        assert len(result) == 5

    def test_get_all_ordered_by_timestamp(self, bus: NotificationBus):
        bus.create_and_post("main", "First")
        bus.create_and_post("main", "Second")
        bus.create_and_post("main", "Third")

        result = bus.get_all()
        # Most recent first
        assert result[0].summary == "Third"
        assert result[2].summary == "First"

    def test_clear(self, bus: NotificationBus):
        bus.create_and_post("main", "Message 1")
        bus.create_and_post("main", "Message 2")

        bus.clear()

        assert len(bus.get_all()) == 0

    def test_persistence(self, tmp_path: Path):
        state_path = tmp_path / "notifications.json"

        # Create bus and add notification
        bus1 = NotificationBus(state_path=state_path)
        bus1.create_and_post("main", "Persisted message")

        # Create new bus from same file
        bus2 = NotificationBus(state_path=state_path)

        all_notifications = bus2.get_all()
        assert len(all_notifications) == 1
        assert all_notifications[0].summary == "Persisted message"

    def test_assigns_id_if_empty(self, bus: NotificationBus):
        notification = Notification(
            id="",  # Empty ID
            source="main",
            timestamp=datetime.now(),
            summary="Test",
        )
        bus.post(notification)

        result = bus.get_all()
        assert result[0].id  # Should have assigned ID
        assert len(result[0].id) > 0

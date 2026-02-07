"""Notification bus for Cordell.

Implements NotificationBusProtocol with in-memory storage and JSON persistence.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from config import get_state_dir
from protocols import Notification

logger = logging.getLogger(__name__)


class NotificationBus:
    """In-memory notification bus with JSON persistence."""

    def __init__(self, state_path: Path | None = None):
        """Initialize the notification bus."""
        self._state_path = state_path or (get_state_dir() / "notifications.json")
        self._notifications: list[Notification] = []
        self._load()

    def _load(self) -> None:
        """Load notifications from disk."""
        if not self._state_path.exists():
            return

        try:
            with open(self._state_path) as f:
                data = json.load(f)

            self._notifications = [
                Notification(
                    id=n["id"],
                    source=n["source"],
                    timestamp=datetime.fromisoformat(n["timestamp"]),
                    summary=n["summary"],
                    read=n.get("read", False),
                )
                for n in data.get("notifications", [])
            ]
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to load notifications: {e}")
            self._notifications = []

    def _save(self) -> None:
        """Save notifications to disk."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_path, "w") as f:
                json.dump(
                    {
                        "notifications": [
                            {
                                "id": n.id,
                                "source": n.source,
                                "timestamp": n.timestamp.isoformat(),
                                "summary": n.summary,
                                "read": n.read,
                            }
                            for n in self._notifications
                        ]
                    },
                    f,
                    indent=2,
                )
        except OSError as e:
            logger.error(f"Failed to save notifications: {e}")

    def post(self, notification: Notification) -> None:
        """Post a new notification."""
        # Assign ID if not set
        if not notification.id:
            notification.id = str(uuid.uuid4())

        self._notifications.append(notification)
        self._save()
        summary = notification.summary[:50]
        logger.info(f"Posted notification from {notification.source}: {summary}")

    def create_and_post(self, source: str, summary: str) -> Notification:
        """Create and post a new notification."""
        notification = Notification(
            id=str(uuid.uuid4()),
            source=source,
            timestamp=datetime.now(),
            summary=summary,
        )
        self.post(notification)
        return notification

    def get_unread(self) -> list[Notification]:
        """Get all unread notifications, most recent first."""
        return sorted(
            [n for n in self._notifications if not n.read],
            key=lambda n: n.timestamp,
            reverse=True,
        )

    def get_all(self, limit: int = 50) -> list[Notification]:
        """Get all notifications, most recent first."""
        sorted_notifications = sorted(
            self._notifications, key=lambda n: n.timestamp, reverse=True
        )
        return sorted_notifications[:limit]

    def mark_read(self, notification_id: str) -> None:
        """Mark a notification as read."""
        for n in self._notifications:
            if n.id == notification_id:
                n.read = True
                self._save()
                return

    def mark_all_read(self) -> None:
        """Mark all notifications as read."""
        for n in self._notifications:
            n.read = True
        self._save()

    def clear(self) -> None:
        """Clear all notifications."""
        self._notifications = []
        self._save()

    @property
    def unread_count(self) -> int:
        """Get the count of unread notifications."""
        return sum(1 for n in self._notifications if not n.read)

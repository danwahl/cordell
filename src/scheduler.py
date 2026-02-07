"""Scheduler for Cordell using APScheduler.

Runs scheduled jobs against sessions and posts notifications.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import CordellConfig, JobConfig
from notifications import NotificationBus
from session_manager import SessionManager

logger = logging.getLogger(__name__)

HEARTBEAT_OK = "HEARTBEAT_OK"


class Scheduler:
    """APScheduler wrapper for Cordell jobs."""

    def __init__(
        self,
        config: CordellConfig,
        session_manager: SessionManager,
        notification_bus: NotificationBus,
    ):
        """Initialize the scheduler.

        Args:
            config: Cordell configuration with job definitions.
            session_manager: Session manager for sending messages.
            notification_bus: Notification bus for posting alerts.
        """
        self._config = config
        self._session_manager = session_manager
        self._notification_bus = notification_bus
        self._scheduler = BackgroundScheduler()
        self._setup_jobs()

    def _setup_jobs(self) -> None:
        """Set up all scheduled jobs from config."""
        for job_name, job_config in self._config.jobs.items():
            self._add_job(job_name, job_config)

    def _add_job(self, job_name: str, job_config: JobConfig) -> None:
        """Add a single job to the scheduler."""
        try:
            trigger = CronTrigger.from_crontab(job_config.schedule)
            self._scheduler.add_job(
                self._run_job,
                trigger=trigger,
                args=[job_name, job_config],
                id=job_name,
                name=job_name,
                replace_existing=True,
            )
            logger.info(f"Scheduled job '{job_name}' with schedule '{job_config.schedule}'")
        except Exception as e:
            logger.error(f"Failed to schedule job '{job_name}': {e}")

    def _is_in_active_hours(self, active_hours: tuple[int, int] | None) -> bool:
        """Check if current time is within active hours."""
        if active_hours is None:
            return True

        start_hour, end_hour = active_hours
        current_hour = datetime.now().hour

        # Handle ranges like (6, 22) = 6:00-21:59
        if start_hour <= end_hour:
            return start_hour <= current_hour < end_hour
        else:
            # Handle overnight ranges like (22, 6) = 22:00-05:59
            return current_hour >= start_hour or current_hour < end_hour

    def _run_job(self, job_name: str, job_config: JobConfig) -> None:
        """Execute a scheduled job."""
        # Check active hours
        if not self._is_in_active_hours(job_config.active_hours):
            logger.debug(f"Skipping job '{job_name}' - outside active hours")
            return

        # Get or create active session for this agent
        try:
            session = self._session_manager.get_or_create_active_session(job_config.agent)
        except ValueError as e:
            logger.error(f"Job '{job_name}' failed - unknown agent '{job_config.agent}': {e}")
            self._notification_bus.create_and_post(
                source=job_config.agent,
                summary=f"[{job_name}] Error: Unknown agent '{job_config.agent}'",
            )
            return

        logger.info(f"Running scheduled job '{job_name}' on session '{session.session_id}' (agent: {job_config.agent})")

        try:
            # Collect response
            response_text = ""
            for msg in self._session_manager.send_message_sync(
                session.session_id, job_config.prompt
            ):
                if msg.type == "text":
                    response_text += msg.content
                elif msg.type == "error":
                    response_text = f"Error: {msg.content}"
                    break

            # Check for heartbeat OK
            if job_config.suppress_ok and HEARTBEAT_OK in response_text:
                logger.info(f"Job '{job_name}' completed with HEARTBEAT_OK - suppressing notification")
                return

            # Post notification
            summary = response_text[:200] if response_text else "(No response)"
            self._notification_bus.create_and_post(
                source=job_config.agent,
                summary=f"[{job_name}] {summary}",
            )

        except Exception as e:
            logger.error(f"Job '{job_name}' failed: {e}")
            self._notification_bus.create_and_post(
                source=job_config.agent,
                summary=f"[{job_name}] Error: {e}",
            )

    def start(self) -> None:
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def get_jobs(self) -> list[dict]:
        """Get information about all scheduled jobs."""
        return [
            {
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "agent": self._config.jobs[job.id].agent if job.id in self._config.jobs else None,
            }
            for job in self._scheduler.get_jobs()
        ]

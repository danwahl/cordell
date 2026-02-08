"""Cordell-specific MCP tools for agent self-management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_agent_sdk import create_sdk_mcp_server, tool

if TYPE_CHECKING:
    from scheduler import Scheduler


def create_cordell_mcp_server(scheduler: Scheduler):
    """Create the Cordell MCP server.

    Args:
        scheduler: Reference to the Scheduler instance for job management.

    Returns:
        McpSdkServerConfig for the Cordell MCP server.
    """

    @tool(
        "schedule_job",
        "Create or update a recurring scheduled job",
        {"name": str, "schedule": str, "prompt": str, "agent": str},
    )
    async def schedule_job(args: dict) -> dict:
        """Schedule a new job or update an existing one."""
        name = args["name"]
        schedule = args["schedule"]
        prompt = args["prompt"]
        agent = args.get("agent", "main")

        # Validate cron expression
        try:
            from apscheduler.triggers.cron import CronTrigger

            CronTrigger.from_crontab(schedule)
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Invalid cron expression: {e}"}],
                "is_error": True,
            }

        # Add to scheduler
        try:
            scheduler.add_job_dynamic(name, agent, schedule, prompt)
            msg = f"Scheduled job '{name}': runs on {agent} at '{schedule}'"
            return {"content": [{"type": "text", "text": msg}]}
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Failed to schedule job: {e}"}],
                "is_error": True,
            }

    @tool("list_jobs", "List all scheduled jobs", {})
    async def list_jobs(args: dict) -> dict:
        """List all currently scheduled jobs."""
        jobs = scheduler.get_jobs()
        if not jobs:
            return {"content": [{"type": "text", "text": "No scheduled jobs."}]}

        lines = []
        for job in jobs:
            next_run = job.get("next_run", "unknown")
            lines.append(
                f"- {job['name']} (agent: {job.get('agent', '?')}, next: {next_run})"
            )

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool("remove_job", "Remove a scheduled job", {"name": str})
    async def remove_job(args: dict) -> dict:
        """Remove a scheduled job by name."""
        name = args["name"]
        try:
            scheduler.remove_job_dynamic(name)
            return {"content": [{"type": "text", "text": f"Removed job '{name}'"}]}
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error removing job: {e}"}],
                "is_error": True,
            }

    return create_sdk_mcp_server(
        name="cordell",
        version="1.0.0",
        tools=[schedule_job, list_jobs, remove_job],
    )

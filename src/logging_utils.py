"""Logging utilities for Cordell.

Provides structured logging with secret redaction.
"""

import logging
import os
import re

# Patterns for secrets to redact
REDACT_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9-]+"),  # Anthropic API keys
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),  # GitHub personal access tokens
    re.compile(r"gho_[a-zA-Z0-9]{36}"),  # GitHub OAuth tokens
    re.compile(r"github_pat_[a-zA-Z0-9_]{22,}"),  # GitHub fine-grained PATs
    re.compile(r"sk-[a-zA-Z0-9]{48}"),  # OpenAI API keys
    re.compile(r"or-[a-zA-Z0-9]{32,}"),  # OpenRouter keys
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"),  # Bearer tokens
]

REDACTION_PLACEHOLDER = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Redact known secret patterns from text."""
    result = text
    for pattern in REDACT_PATTERNS:
        result = pattern.sub(REDACTION_PLACEHOLDER, result)
    return result


class RedactingFormatter(logging.Formatter):
    """Log formatter that redacts secrets."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        return redact_secrets(message)


def setup_logging(level: str | None = None) -> None:
    """Set up logging with secret redaction.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
               Defaults to CORDELL_LOG_LEVEL env var or INFO.
    """
    if level is None:
        level = os.environ.get("CORDELL_LOG_LEVEL", "INFO")

    # Create formatter
    formatter = RedactingFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add console handler with redacting formatter
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Quiet down noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

"""Tests for logging_utils module."""

import logging

from logging_utils import REDACTION_PLACEHOLDER, redact_secrets, setup_logging


class TestRedactSecrets:
    """Tests for redact_secrets."""

    def test_anthropic_api_key(self):
        text = "Using key sk-ant-api03-abcdefghij1234567890"
        result = redact_secrets(text)
        assert "sk-ant-" not in result
        assert REDACTION_PLACEHOLDER in result

    def test_github_pat(self):
        text = "Token: ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "ghp_" not in result
        assert REDACTION_PLACEHOLDER in result

    def test_github_oauth(self):
        text = "OAuth: gho_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert "gho_" not in result
        assert REDACTION_PLACEHOLDER in result

    def test_openai_key(self):
        # OpenAI keys are sk- followed by exactly 48 alphanumeric chars
        text = "Key: sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        result = redact_secrets(text)
        assert "sk-aaaa" not in result
        assert REDACTION_PLACEHOLDER in result

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = redact_secrets(text)
        assert "eyJhbG" not in result
        assert REDACTION_PLACEHOLDER in result

    def test_no_secrets(self):
        text = "This is a normal message with no secrets"
        result = redact_secrets(text)
        assert result == text

    def test_multiple_secrets(self):
        # GitHub PAT needs exactly 36 chars after ghp_
        text = "Key1: sk-ant-api03-abc Key2: ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        result = redact_secrets(text)
        assert result.count(REDACTION_PLACEHOLDER) == 2


class TestSetupLogging:
    """Tests for setup_logging."""

    def test_setup_default_level(self):
        setup_logging()
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_setup_debug_level(self):
        setup_logging("DEBUG")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_setup_from_env(self, monkeypatch):
        monkeypatch.setenv("CORDELL_LOG_LEVEL", "WARNING")
        setup_logging()
        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

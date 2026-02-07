# Cordell

A persistent, session-aware personal AI assistant built on the Claude Agent SDK.

## Features

- **Persistent sessions**: Conversations persist across restarts via SDK session files
- **Multiple agents**: Configure different agents for different purposes (main assistant, monitoring, etc.)
- **Scheduled jobs**: Run prompts on a schedule with APScheduler
- **Notifications**: Get notified when agents complete scheduled tasks
- **Streamlit UI**: Chat interface with session switching and tool use visualization

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Claude Code CLI (for OAuth authentication)

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd cordell
uv sync
```

### 2. Authenticate with Claude

```bash
claude setup-token
```

This stores your OAuth token which Cordell uses to interact with Claude.

### 3. Install pre-commit hooks (optional)

```bash
uv run pre-commit install
```

## Running Locally

```bash
uv run streamlit run src/app.py
```

Open http://localhost:8501 in your browser.

## Running with Docker

### 1. Create environment file

```bash
cp .env.example .env
# Edit .env and add your CLAUDE_CODE_OAUTH_TOKEN
```

### 2. Build and run

**Production:**
```bash
docker compose up --build
```

**Development (with live reload):**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Open http://localhost:8501 in your browser.

## Configuration

### Agents

Agents are defined in `agents/<name>/`:
- `agent.yaml` - Agent configuration (model, tools, permissions)
- `CLAUDE.md` - System prompt for the agent

Example `agent.yaml`:
```yaml
name: main
model: sonnet
system_prompt_file: CLAUDE.md
permission_mode: default
allowed_tools:
  - Read
  - Write
  - Bash
```

### Scheduled Jobs

Jobs are defined in `~/.cordell/config.yaml`:

```yaml
jobs:
  morning-check:
    session: monitor
    schedule: "0 8 * * *"  # 8 AM daily
    prompt: "Check system status"
    active_hours: [6, 22]  # Only run between 6 AM and 10 PM
    suppress_ok: true      # Don't notify if response contains HEARTBEAT_OK
```

## Project Structure

```
cordell/
├── src/
│   ├── app.py              # Streamlit UI
│   ├── config.py           # Configuration models
│   ├── history.py          # JSONL session parser
│   ├── logging_utils.py    # Logging with secret redaction
│   ├── notifications.py    # Notification system
│   ├── protocols.py        # Typed interfaces
│   ├── scheduler.py        # APScheduler wrapper
│   └── session_manager.py  # SDK client lifecycle
├── agents/
│   ├── main/               # General-purpose assistant
│   └── monitor/            # Lightweight monitoring agent
├── tests/                  # Unit tests
├── Dockerfile
├── docker-compose.yml      # Production config
└── docker-compose.dev.yml  # Development overrides
```

## Testing

```bash
uv run pytest
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CLAUDE_CODE_OAUTH_TOKEN` | OAuth token from `claude setup-token` | Required |
| `CORDELL_LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR) | INFO |
| `CORDELL_DIR` | Data directory for state | `~/.cordell` |

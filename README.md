# agent
A modern, terminal-based AI agent interface powered by the Claude Agent SDK.

## Installation
1. Copy `.env.example` to `.env` and add your API keys.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
Start the agent with the `jun` command:

```bash
jun
```

## Features
- **BENEDICTJUN UI**: A beautiful, pixel-perfect terminal interface.
- **Persistent Sessions**: Continues conversations across restarts.
- **Slash Commands**: Control the agent with `/help`, `/model`, `/tools`, etc.
- **Rich Output**: Markdown rendering, syntax highlighting, and styled panels.

## Environment
The agent reads `.env` and maps `ANTHROPIC_AUTH_TOKEN` to `ANTHROPIC_API_KEY` for the SDK.

Required values (already populated in `.env`):
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`
- `OPENAI_MODEL` (used as the default model if `AGENT_MODEL` is not set)

Optional overrides:
- `AGENT_MODEL`
- `ALLOWED_TOOLS` (comma-separated, default: `Read,Edit,Write,Glob,Grep,Bash`). For chatlog tools, allow:
  - `mcp__chatlog__list_topics`
  - `mcp__chatlog__search_by_topics`
  - `mcp__chatlog__search_by_keywords`
  - `mcp__chatlog__load_messages`
  - `mcp__chatlog__expand_query`
  - `mcp__chatlog__search_semantic`
  - `mcp__chatlog__filter_by_person`
  - `mcp__chatlog__format_messages`
- `MAX_TURNS` (default: `4`)
- `CONTINUE_CONVERSATION` (`1` or `0`, default: `1`)
 - `CHATLOG_EMBEDDINGS_NPY` (default: `cleaned_chatlog_embeddings.npy`)
 - `CHATLOG_EMBEDDINGS_INDEX` (default: `cleaned_chatlog_embeddings_index.json`)
 - `CHATLOG_EMBEDDING_MODEL` (default: `embedding-3`)
 - `CHATLOG_SEM_TOP_K` (default: `50`)
 - `CHATLOG_SEM_WEIGHT` (default: `0.6`)
 - `CHATLOG_KW_WEIGHT` (default: `0.4`)
 - `ZHIPU_API_KEY` (required for embedding build)
 - `ZHIPU_EMBEDDINGS_URL` (optional override for embeddings endpoint)

## Persistence
Session IDs are saved to `session.json` so the next run can resume the same session.

## Run
```powershell
python .\basic_session_agent.py
```

## Build chatlog embeddings (semantic search)
```powershell
python .\scripts\build_chatlog_embeddings.py
```

## TUI
```powershell
python .\tui_agent.py
```

Common commands:
- `/help`
- `/session`
- `/reset`
- `/model claude-sonnet-4-5`
- `/tools Read,Edit,Write,Glob,Grep,Bash`
- `/max 4`
- `/continue on`
- `/resume session-xyz`
- `/fork`
- `/perm default`
- `/info`
- `/save`
- `/history`
- `/status`
- `/clear`

## Files
- `session.json` stores the current session id.
- `history.jsonl` stores prompt/response history.
- `tui_config.json` stores persisted TUI settings.

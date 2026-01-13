# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BENEDICTJUN is a terminal-based AI agent interface built on the Claude Agent SDK. It provides a rich TUI (Terminal User Interface) for interactive conversations with Claude, featuring:

- **Subagent Support**: Specialized agents for exploration, planning, coding, reviewing, and debugging
- **ReAct Pattern**: Structured reasoning and acting framework
- **Context Management**: Automatic token tracking and compaction
- **Session Persistence**: Full session lifecycle management

## Quick Start

**Run the TUI agent:**
```powershell
python .\tui_agent.py
# or via the batch wrapper:
jun
```

**Run the basic session agent:**
```powershell
python .\basic_session_agent.py
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

## Architecture

### Entry Points
- `tui_agent.py` - Main TUI application using Rich and prompt_toolkit
- `basic_session_agent.py` - Minimal example showing core SDK usage

### Module Structure (Fixed in v0.3.0)

```
benedictjun/
├── tui_agent.py           # Main TUI entry point
├── basic_session_agent.py # Simple example
├── src/
│   ├── __init__.py        # Package exports
│   ├── agents/
│   │   ├── definitions.py # AgentDefinition for subagents
│   │   └── react.py       # ReAct pattern implementation
│   ├── context/
│   │   ├── manager.py     # ContextManager for token tracking
│   │   └── history.py     # Message history handling
│   └── session/
│       ├── persistence.py # SessionManager for session lifecycle
│       └── transcript.py  # SessionTranscript for JSONL history
├── session.json           # Current session ID
├── history.jsonl          # Conversation history backup (legacy)
├── context_state.json     # Saved context state
└── tui_config.json        # User configuration
```

### Core Components

#### Session Management (`src/session/persistence.py`)
- `SessionManager`: Handles session lifecycle (create, fork, resume, delete)
- `SessionInfo`: Metadata about sessions (name, message count, timestamps)
- Uses `resume` parameter for SDK session continuity (P0 Fix)

#### Session Storage (`src/session/transcript.py`) - NEW in v0.7.0

采用 Claude Code 标准格式存储会话历史：

**文件结构：**
```
.claude/sessions/
├── sessions.json            # 会话元数据索引
└── <session_id>.jsonl       # 每个会话的完整对话历史
```

**JSONL 转录格式：**
```jsonl
{"role": "user", "content": "...", "timestamp": "2026-01-09T12:00:00Z"}
{"role": "assistant", "content": "...", "timestamp": "2026-01-09T12:00:01Z"}
```

**关键特性：**
- 每个会话独立文件，便于管理和恢复
- `/resume` 显示历史消息预览
- 自动追加消息到当前会话文件

#### Context Management (`src/context/manager.py`)
- `ContextManager`: Tracks message history and token usage
- Automatic compaction when approaching limits (80% threshold)
- Summary generation for context preservation
- Per-model token limit awareness

#### Agent Definitions (`src/agents/definitions.py`)
- Predefined subagents: `explorer`, `planner`, `coder`, `reviewer`, `debugger`, `test-runner`
- Each agent has specific tools and model settings
- Invoked via the `Task` tool in `allowed_tools`

#### ReAct Controller (`src/agents/react.py`)
- Implements Reasoning + Acting pattern
- Step-by-step thought/action/observation loop
- Traces for debugging and analysis

**ReAct Commands:**
| Command | Description |
|---------|-------------|
| `/react` | Show ReAct mode status |
| `/react on` | Enable ReAct for all queries |
| `/react off` | Disable ReAct mode |
| `/react goal <task>` | Run single ReAct task |

**Example Output:**
```
┌─ Step 1 ────────────────────────────────────────┐
│ Thought: I need to search for the weather...   │
│ Action: mcp__web__web_search                   │
│ Observation: Beijing weather today is 5°C...   │
└─────────────────────────────────────────────────┘
```

### Message Types
The SDK provides these message types for response handling:
- `AssistantMessage` with `TextBlock`, `ToolUseBlock`, `ToolResultBlock`
- `ThinkingBlock` for Extended Thinking (Opus 4.5) - Now properly handled (P1 Fix)
- `ResultMessage` containing final result and session ID
- `SystemMessage` for init events (session ID captured here)
- `StreamEvent` for real-time streaming

## Environment Variables

Required (in `.env`):
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN` (auto-mapped to `ANTHROPIC_API_KEY`)

Optional:
- `ANTHROPIC_MODEL` - Model override (supports Claude, DeepSeek, GPT, etc.)
- `AGENT_MODEL` - Alternative model override
- `ALLOWED_TOOLS` - Comma-separated tool list (default includes `Task` for subagents)
- `MAX_TURNS` - Turn limit (default: `4`)
- `CONTINUE_CONVERSATION` - `1` or `0` (default: `1`)
- `TAVILY_API_KEY` - API key for web search functionality
- `POE_API_KEY` - Poe API key for memory extraction (GPT-5-nano)
- `POE_EXTRACTION_MODEL` - Model for extraction (default: `gpt-5-nano`)
- `ZHIPU_API_KEY` - ZHIPU API key for future RAG support
- `ZHIPU_EMBEDDING_MODEL` - Embedding model (default: `embedding-3`)

## Web Search Tools

The project includes web search capabilities via the `web_search` MCP server:
- `mcp__web__web_search` - Search the web using Tavily API
- `mcp__web__web_fetch` - Fetch and read web pages

**When to use web search:**
- Current events, news, or time-sensitive information
- Information outside the model's training data
- Real-time data queries (stock prices, weather, etc.)

The agent is configured to automatically use web search for factual queries that might change over time.

## Skills System

Skills are reusable prompts and instructions that extend the agent's capabilities. When your request matches a skill's description, the skill is automatically activated.

### Available Skills

| Skill | Description |
|-------|-------------|
| `commit-helper` | Generates conventional commit messages from git diffs |
| `code-reviewer` | Systematic code review with quality/security focus |
| `debug-helper` | Debugging methodology and problem diagnosis |
| `doc-generator` | Documentation templates (README, docstrings) |
| `test-writer` | Test case writing with best practices |

### Skill Commands

| Command | Description |
|---------|-------------|
| `/skills` | List all available skills |
| `/skills enable <name>` | Manually enable a skill |
| `/skills disable` | Disable current skill |
| `/skills info <name>` | Show skill details |
| `/skills refresh` | Reload skills from disk |

### Creating Custom Skills

1. Create a directory in `.claude/skills/your-skill-name/`
2. Add a `SKILL.md` file with this format:

```markdown
---
name: your-skill-name
description: Brief description of when to use this skill
allowed-tools: Read, Write (optional)
---

# Your Skill Instructions

Markdown content with step-by-step guidance for Claude.
```

Skills are stored in:
- `.claude/skills/` - Project-specific skills
- `~/.claude/skills/` - Global user skills (shared across projects)

## Memory System

A ChatGPT-style memory system that remembers user preferences, facts, opinions, and attitudes across sessions.

### How It Works

1. **MCP Tools**: The Agent can actively call memory tools during conversation
   - `mcp__memory__recall_memory` - Search memories by topic
   - `mcp__memory__remember` - Save user-requested memories
   - `mcp__memory__get_user_profile` - Get core user profile
   - `mcp__memory__list_memories` - List all memories
   - `mcp__memory__forget` - Delete a memory

2. **Auto Extraction**: After each conversation, GPT-5-nano (Poe API) extracts relevant information in the background

3. **Conflict Detection**: When new information conflicts with existing memories, you'll be prompted to resolve

### Memory Categories

| Category | Description | Example |
|----------|-------------|---------|
| `preference` | User preferences | "prefers Google docstring style" |
| `fact` | Objective facts | "works as a backend developer" |
| `opinion` | Subjective views | "thinks FastAPI is better than Flask" |
| `attitude` | Values, tendencies | "values code security highly" |

### Memory Commands

| Command | Description |
|---------|-------------|
| `/memory` | Show memory statistics |
| `/memory list [category]` | List memories |
| `/memory forget <id>` | Delete a memory |
| `/memory clear` | Clear all memories |
| `/memory conflicts` | View pending conflicts |
| `/memory resolve <id> <action>` | Resolve a conflict |
| `/memory profile [key=value]` | View/edit user profile |

### Storage Location

Memories are stored in: `~/.benedictjun/memories.json`

## Chatlog Retrieval System

Intelligent chatlog retrieval with a task reasoning path and atomic tools.

### How It Works

1. **Keyword Expansion (optional)**: Expand a query into keywords/topics
2. **Topic/Semantic Search**: Retrieve line numbers using index or embeddings
3. **Context Window**: Load nearby messages for conversation context
4. **Person Focus (optional)**: Filter messages to target a specific person

### MCP Tools

| Tool | Description |
|------|-------------|
| `mcp__chatlog__get_chatlog_stats` | Get statistics about loaded chatlog |
| `mcp__chatlog__search_person` | Search messages from a specific person |
| `mcp__chatlog__list_topics` | List available topics |
| `mcp__chatlog__search_by_topics` | Find line numbers by topics |
| `mcp__chatlog__search_by_keywords` | Find line numbers by keywords |
| `mcp__chatlog__load_messages` | Load messages by line numbers |
| `mcp__chatlog__expand_query` | Expand question into keywords/topics |
| `mcp__chatlog__search_semantic` | Semantic search by embeddings |
| `mcp__chatlog__filter_by_person` | Filter messages by target person |
| `mcp__chatlog__format_messages` | Format messages for display |
| `mcp__chatlog__parse_task` | Parse task intent and generate sub-questions |
| `mcp__chatlog__retrieve_evidence` | Retrieve structured evidence from multiple paths |
| `mcp__chatlog__analyze_evidence` | Analyze evidence into signals and framework |

Recommended task reasoning flow:
- `mcp__chatlog__parse_task` -> `mcp__chatlog__retrieve_evidence` -> `mcp__chatlog__analyze_evidence`

### Chatlog Commands

| Command | Description |
|---------|-------------|
| `/chatlog` or `/chatlog stats` | Show chatlog statistics |
| `/chatlog query <问题> [@人物]` | Intelligent search |
| `/chatlog person <名字>` | View person's messages |
| `/chatlog reload` | Reload chatlog file |

### Example Usage

```
/chatlog query 冯天奇的消费习惯怎么样 @冯天奇
/chatlog person 冯天奇
/chatlog stats
```

### Configuration

Environment variables in `.env`:
- `CHATLOG_CLEANER_MODEL` - Model for keyword expansion (default: Gemini-2.5-Flash-Lite)
- `CHATLOG_CONTEXT_BEFORE` - Messages before match (default: 5)
- `CHATLOG_CONTEXT_AFTER` - Messages after match (default: 5)
- `CHATLOG_CHAR_THRESHOLD` - Trigger cleaning above this (default: 3000)
- `CHATLOG_TARGET_CHARS` - Target size after cleaning (default: 2000)

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/session` | Show current session info |
| `/reset` | Clear session and context |
| `/model [name]` | Show or set model |
| `/tools [list]` | Show or set allowed tools |
| `/max [n]` | Show or set max turns |
| `/continue [on\|off]` | Toggle continue conversation |
| `/resume [id]` | Resume a session (shows list if no ID) |
| `/fork` | Fork current session |
| `/agents` | List available subagents |
| `/skills` | List and manage skills |
| `/thinking [on\|off]` | Toggle thinking display (Extended Thinking) |
| `/compact` | Compact context with summary |
| `/context` | Show context statistics |
| `/sessions` | List recent sessions |
| `/info` | Show server info |
| `/save` | Save current config |
| `/history` | Show history file path |
| `/memory` | Manage long-term memories |
| `/chatlog` | Query chatlog history |
| `/clear` | Clear screen and context |
| `/exit` | Exit the application |

## Version History

### v0.7.0 (Current)
- **Session Storage Refactor**: Claude Code 标准格式的会话历史存储
- **Per-session JSONL files**: 每个会话独立 `.jsonl` 文件
- **SessionTranscript**: 新增转录管理类
- **Resume Preview**: `/resume` 显示历史消息预览

### v0.6.0
- **Chatlog MCP**: Intelligent chatlog retrieval with keyword expansion
- **Chatlog Commands**: `/chatlog query/stats/person/reload` for manual control
- **Multi-keyword Search**: Uses small model to expand query into 10 related keywords
- **Context Preservation**: Extracts ±5 messages around matches to preserve conversation flow
- **Smart Cleaning**: Uses Gemini-2.5-Flash-Lite for result filtering when data is large

### v0.5.5
- **ReAct Mode**: Integrated Thought → Action → Observation reasoning pattern
- **ReAct Commands**: `/react on/off/goal` for manual control
- **Visual Trace**: Display reasoning steps in rich panels

### v0.5.0
- **Memory System**: ChatGPT-style memory with MCP tools
- **Memory MCP Server**: recall_memory, remember, get_user_profile, list_memories, forget
- **Auto Extraction**: GPT-5-nano (Poe API) for background memory extraction
- **Conflict Detection**: Automatic conflict detection and resolution UI
- **Memory Commands**: `/memory` with subcommands for management

### v0.4.0
- **Skills System**: Claude Code-style skills with SKILL.md files
- **Pre-built Skills**: commit-helper, code-reviewer, debug-helper, doc-generator, test-writer
- **Auto-activation**: Skills automatically match based on user request
- **Skill Commands**: `/skills` for listing, enabling, and managing skills

### v0.3.0
- **P0 Fix**: Session management using `SessionManager` with proper `resume` parameter
- **P0 Fix**: Subagent support with `AGENT_DEFINITIONS` and `Task` tool
- **P1 Fix**: Context management with `ContextManager` and `/compact` command
- **P1 Fix**: `ThinkingBlock` handling for Extended Thinking (Opus 4.5)
- **P2 Fix**: Robust error handling with exponential backoff reconnection
- **P2 Fix**: Query timeout handling (5 minutes default)

### v0.2.0
- Initial TUI with BENEDICTJUN styling
- Basic session persistence
- Tool use display

## Known Issues

- Permission mode (`/perm`) removed as it's not part of SDK public API
- AI-powered compact requires active client connection

## Claude Agent SDK 规范

本项目遵循 Claude Agent SDK 标准。开发时请参考以下规范：

### SDK 客户端使用

| 场景 | 推荐方式 |
|-----|---------|
| 有状态多轮对话 | `ClaudeSDKClient` |
| 无状态单次查询 | `query()` 函数 |
| 会话恢复 | `resume` 参数 |

### Subagent 设计原则

```
✅ 单一职责 - 每个 agent 只做一件事
✅ 工具最小权限 - 只授予必要工具
✅ 禁止 Task 递归 - subagent 不能包含 Task 工具
✅ 清晰描述 - Claude 根据描述决定调用
```

定义位置：`src/agents/definitions.py`

### MCP 服务器规范

工具命名：`mcp__<server>__<tool>`  
例如：`mcp__web__web_search`, `mcp__memory__recall_memory`

配置文件：`.mcp.json`（项目根目录）

### Context 管理

- SDK 在 ~50k tokens 时自动触发 compaction
- 使用 `CLAUDE.md` 存储稳定指令以启用 prompt caching
- 使用 subagent 进行上下文隔离

### Session 存储格式

符合 Claude Code 标准：
```
.claude/sessions/
├── sessions.json          # 元数据索引
└── <session_id>.jsonl     # JSONL 对话历史
```

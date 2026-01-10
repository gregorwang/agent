"""
BENEDICTJUN Terminal UI Agent
A modern, beautiful command-line interface for Claude Agent SDK in BENEDICTJUN style

Fixed according to ANALYSIS_REPORT.md:
- P0: Session management with SessionManager integration
- P0: Subagent support with Task tool and AgentDefinition
- P1: Context management with ContextManager
- P1: Improved streaming with ThinkingBlock support
- P2: Robust error handling with reconnection logic
"""

import asyncio
import json
import os
import getpass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,  # P1 Fix: Added ThinkingBlock support
    ToolResultBlock,
    ToolUseBlock,
)
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PromptStyle
from prompt_toolkit.completion import WordCompleter, FuzzyWordCompleter
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.syntax import Syntax
from rich.table import Table
from rich.columns import Columns
from rich.layout import Layout
from rich.align import Align
from rich.box import ROUNDED, HEAVY, DOUBLE, MINIMAL
from rich import box

# Import new modules for proper architecture
from src.session.persistence import SessionManager
from src.session.transcript import SessionTranscript
from src.context.manager import ContextManager
from src.agents.definitions import AGENT_DEFINITIONS, get_agent_definitions
from src.tools.web_search import create_web_mcp_server
from src.permissions import PermissionManager
from src.ui.components import (
    ToolApprovalPrompt,
    SelectionMenu,
    DiffPreview,
    ThinkingPanel,
    ConfirmPrompt,
    ApprovalResult,
)
from src.ui.styles import COLORS, STYLES as UI_STYLES
from src.router import ModelRouter, get_router, TaskType
from src.skills import SkillManager, get_skill_manager
from src.memory import (
    MemoryStorage,
    MemoryCategory,
    get_memory_storage,
    create_memory_mcp_server,
    get_memory_extractor
)
from src.agents.react import ReActController, ReActTrace, run_react
from src.chatlog import create_chatlog_mcp_server
from src.chatlog.trigger import should_use_chatlog_chain
from src.commands import CommandDispatcher, AppState, CommandResult


# ═══════════════════════════════════════════════════════════════════════════════
# Constants & Configuration
# ═══════════════════════════════════════════════════════════════════════════════

SESSION_PATH = Path("session.json")
SESSIONS_DIR = Path(".claude/sessions")
HISTORY_PATH = Path("history.jsonl")
CONFIG_PATH = Path("tui_config.json")
CONTEXT_PATH = Path("context_state.json")

# Color palette imported from src/ui/styles.py
# COLORS is now imported directly, not duplicated here

VERSION = "0.5.0"

# P2 Fix: Connection retry settings
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY_BASE = 1.0  # Base delay in seconds, will be multiplied exponentially
QUERY_TIMEOUT = 300  # 5 minutes timeout for queries
RESPONSE_IDLE_TIMEOUT = 120  # Stop waiting if no new stream events arrive
RESPONSE_TOTAL_TIMEOUT = 300  # Hard stop for response streaming

console = Console()


# ═══════════════════════════════════════════════════════════════════════════════
# Turn Statistics Tracking
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TurnStats:
    """Statistics for a single query turn, tracking tokens and costs."""
    input_tokens: int = 0
    output_tokens: int = 0
    turn_count: int = 0
    total_cost_usd: float = 0.0
    
    def add(self, other: "TurnStats") -> None:
        """Accumulate stats from another turn."""
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.turn_count += other.turn_count
        self.total_cost_usd += other.total_cost_usd
    
    @property
    def total_tokens(self) -> int:
        """Total tokens (input + output)."""
        return self.input_tokens + self.output_tokens


@dataclass
class QueryStats:
    """Lightweight stats for non-streaming queries."""
    duration_seconds: float = 0.0
    tool_calls: int = 0
    tool_names: list[str] = None
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.tool_names is None:
            self.tool_names = []


def print_turn_stats(stats: TurnStats) -> None:
    """Print token usage and turn statistics at end of conversation."""
    if stats.turn_count == 0 and stats.total_tokens == 0:
        return  # Don't print if no stats
    
    table = Table(
        box=ROUNDED,
        border_style=COLORS["muted"],
        show_header=False,
        padding=(0, 1),
    )
    table.add_column("Metric", style=COLORS["muted"])
    table.add_column("Value", style=COLORS["text"], justify="right")
    
    table.add_row("Turns", str(stats.turn_count))
    table.add_row("Input", f"{stats.input_tokens:,} tokens")
    table.add_row("Output", f"{stats.output_tokens:,} tokens")
    
    if stats.total_cost_usd > 0:
        table.add_row("Cost", f"${stats.total_cost_usd:.4f}")
    
    console.print(table)

# Prompt toolkit style for input
# Prompt toolkit style for input
prompt_style = PromptStyle.from_dict({
    "prompt": f"bold {COLORS['text']}",
    "bottom-toolbar": f"bg:#1a1a2e {COLORS['muted']}",
    "completion-menu": "bg:#2d2d2d #eeeeee",
    "completion-menu.completion": "bg:#2d2d2d #eeeeee",
    "completion-menu.completion.current": f"bg:{COLORS['primary']} #000000",
    "scrollbar.background": "bg:#222222",
    "scrollbar.button": "bg:#777777",
})

# Command metadata for autocompletion
COMMANDS_META = {
    "/help": "Show all commands",
    "/clear": "Clear conversation history",
    "/compact": "Compact context",
    "/config": "Open config panel",
    "/agents": "List subagents",
    "/skills": "List and manage skills",
    "/exit": "Exit application",
    "/session": "Show session info",
    "/reset": "Reset session",
    "/model": "Switch model",
    "/tools": "Configure tools",
    "/max": "Set max turns",
    "/continue": "Toggle auto-continue",
    "/resume": "Resume session",
    "/fork": "Fork session",
    "/thinking": "Toggle thinking",
    "/context": "Show context stats",
    "/sessions": "List recent sessions",
    "/info": "Server info",
    "/save": "Save config",
    "/history": "Show history path",
    "/permissions": "Manage tool permissions",
    "/route": "Dynamic model routing",
    "/memory": "Manage user memories",
    "/react": "ReAct reasoning mode",
    "/chatlog": "Query chatlog history",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Global Managers (P0/P1 Fix: Proper session and context management)
# ═══════════════════════════════════════════════════════════════════════════════

# Initialize managers globally
session_manager = SessionManager(session_path=SESSION_PATH, sessions_dir=SESSIONS_DIR)
session_transcript = SessionTranscript(transcripts_dir=SESSIONS_DIR)
context_manager = ContextManager(model="claude-sonnet-4-5")
permission_manager = PermissionManager(settings_path=Path("permissions.json"))
skill_manager = get_skill_manager(project_path=Path(".claude/skills"))
memory_storage = get_memory_storage()


# ═══════════════════════════════════════════════════════════════════════════════
# Session & History Management (Legacy compatibility layer)
# ═══════════════════════════════════════════════════════════════════════════════

def load_session_id() -> Optional[str]:
    """Load the current session ID from disk (uses SessionManager)."""
    return session_manager.get_current_session_id()


def save_session_id(session_id: str) -> None:
    """Save the session ID to disk (uses SessionManager)."""
    session_manager.set_current_session_id(session_id)


def append_history(role: str, content: str) -> None:
    """Append a message to the history file, context manager, and session transcript."""
    # P1 Fix: Also track in context manager
    if role == "user":
        context_manager.add_user_message(content)
    elif role == "assistant":
        context_manager.add_assistant_message(content)
    
    # NEW: Save to session transcript (per-session JSONL file)
    current_session = session_manager.get_current_session_id()
    if current_session:
        session_transcript.append_message(
            session_id=current_session,
            role=role,
            content=content,
        )
    
    # Keep legacy JSONL history as backup
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "role": role,
        "content": content,
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_default_tools() -> list[str]:
    """Get the default list of allowed tools (P0 Fix: includes Task for subagents)."""
    default = (
        "Read,Edit,Write,Glob,Grep,Bash,Task,"
        "mcp__web__web_search,mcp__web__web_fetch,"
        "mcp__memory__recall_memory,mcp__memory__remember,mcp__memory__get_user_profile,"
        "mcp__chatlog__query_chatlog,mcp__chatlog__get_chatlog_stats,mcp__chatlog__search_person"
    )
    tools = os.getenv("ALLOWED_TOOLS", default).split(",")
    return [tool.strip() for tool in tools if tool.strip()]



def load_config() -> dict:
    """Load configuration from file."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# UI Components
# ═══════════════════════════════════════════════════════════════════════════════

def get_pixel_alien() -> Text:
    """Return the pixel alien art."""
    # Simplified ASCII pixel alien
    art = (
        "     ▀▄   ▄▀     \n"
        "    ▄█▀███▀█▄    \n"
        "   █▀███████▀█   \n"
        "   █ █▀▀▀▀▀█ █   \n"
        "      ▀▀ ▀▀      "
    )
    return Text(art, style="cyan justify_center")

def print_dashboard(model: str) -> None:
    """Print the main startup dashboard."""
    user = getpass.getuser()
    cwd = os.getcwd()
    
    # Get context stats for display
    ctx_stats = context_manager.get_stats()
    
    # 1. Header Title
    title = f" BENEDICTJUN {VERSION} "
    
    # 2. Central Welcome & Logo
    welcome_text = Text(f"\nWelcome back {user}!\n", style="bold white justify_center")
    logo = get_pixel_alien()
    
    # 3. Columns (Info vs Tips)
    # Left Column: Info
    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_row(Text(f"{model} · Context: {ctx_stats['current_tokens']}/{ctx_stats['max_tokens']}", style="dim white"))
    info_table.add_row(Text(f"Session: {session_manager.get_current_session_id() or '(none)'}", style="dim white"))
    info_table.add_row(Text(cwd, style="dim white"))

    # Right Column: Tips & Activity
    tips_text = Text()
    tips_text.append("Tips for getting started\n", style=f"bold {COLORS['primary']}")
    tips_text.append("Run ", style="dim white")
    tips_text.append("/init", style="white")
    tips_text.append(" to create a CLAUDE.md file with instruction...\n", style="dim white")
    
    tips_text.append("\nRecent activity\n", style=f"bold {COLORS['primary']}")
    
    # Show recent sessions
    recent = session_manager.get_recent_sessions(3)
    if recent:
        for sess in recent:
            name = sess.name or sess.session_id[:20]
            tips_text.append(f"  {name}\n", style="dim white")
    else:
        tips_text.append("  No recent sessions\n", style="dim white")
    tips_text.append("/resume for more", style="dim white")

    # Combine into a grid
    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    
    grid.add_row(welcome_text)
    grid.add_row(logo)
    grid.add_row(Text("\n", style="dim")) # Spacer
    
    # Split bottom section
    bottom_grid = Table.grid(expand=True)
    bottom_grid.add_column(ratio=1) # Left
    bottom_grid.add_column(ratio=1) # Right
    
    bottom_grid.add_row(info_table, tips_text)
    
    grid.add_row(bottom_grid)
    
    # Wrap everything in the main Panel
    console.print(Panel(
        grid,
        title=title,
        title_align="left",
        border_style=f"{COLORS['primary']}",
        box=ROUNDED,
        padding=(1, 2)
    ))
    
    # Print Slash Command Hints below
    print_slash_hints()

def print_slash_hints() -> None:
    """Print the list of available slash commands at the bottom."""
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(style=COLORS['secondary'], no_wrap=True)
    grid.add_column(style="dim white")
    
    hints = [
        ("/help", "Show all commands"),
        ("/clear", "Clear conversation history and free up context"),
        ("/compact", "Clear history but keep a summary (uses AI)"),
        ("/config", "Open config panel"),
        ("/agents", "List available subagents"),
        ("/exit", "Exit the application"),
    ]
    
    console.print(Text("─" * console.width, style="dim white"))
    for cmd, desc in hints:
        grid.add_row(cmd, desc)
    console.print(grid)
    console.print(Text("─" * console.width, style="dim white"))


def count_quote_lines(text: str) -> int:
    """Count evidence lines starting with '>'."""
    return sum(1 for line in text.splitlines() if line.strip().startswith(">"))


def truncate_text(text: str, max_chars: int = 2000) -> str:
    """Truncate long text to keep outputs readable."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def format_tool_use(name: str, input_data: dict) -> Panel:
    """Format a tool use block."""
    input_str = json.dumps(input_data, indent=2, ensure_ascii=False)
    if len(input_str) > 500:
        input_str = input_str[:500] + "\n... (truncated)"
    
    content = Text()
    content.append(f"{name}\n", style="bold yellow")
    content.append(input_str, style="dim")
    
    return Panel(
        content,
        title="[bold yellow]Tool Call[/bold yellow]",
        title_align="left",
        border_style="yellow",
        box=ROUNDED,
    )


def format_tool_result(content: str) -> Panel:
    """Format a tool result block."""
    if len(content) > 500:
        content = content[:500] + "\n... (truncated)"

    return Panel(
        Text(content, style="dim white"),
        title="[bold blue]Result[/bold blue]",
        title_align="left",
        border_style="blue",
        box=MINIMAL,
    )


def extract_tool_result_text(content: object) -> str:
    """Best-effort extraction of text from tool result payloads."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        inner = content.get("content")
        if inner is not None:
            return extract_tool_result_text(inner)
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(text)
                continue
            part = extract_tool_result_text(item)
            if part:
                parts.append(part)
        return "\n".join(parts)
    return str(content)


def format_thinking(content: str) -> Panel:
    """P1 Fix: Format a thinking block (Extended Thinking)."""
    if len(content) > 300:
        content = content[:300] + "\n... (truncated)"
    
    return Panel(
        Text(content, style=f"italic {COLORS['thinking']}"),
        title="[bold purple]Thinking[/bold purple]",
        title_align="left",
        border_style="purple",
        box=MINIMAL,
    )


def format_user_message(text: str) -> None:
    """Format and print a user message."""
    pass  # The prompt itself shows the user input


def format_assistant_start() -> None:
    """Print the assistant message header."""
    console.print()


def format_final_result(result: str) -> None:
    """Format the final result message."""
    console.print()
    console.print(Markdown(result))
    console.print()


def render_session_table(sessions: list, title: str = "Sessions", show_last_used: bool = False) -> Table:
    """
    P1 Refactor: Render a table of sessions - extracted from duplicate code in /resume and /sessions.
    
    Args:
        sessions: List of SessionInfo objects
        title: Table title
        show_last_used: Whether to include last used column
    """
    table = Table(title=title, box=ROUNDED)
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Messages", style="green")
    if show_last_used:
        table.add_column("Last Used", style="dim")
    
    for s in sessions:
        row_data = [
            s.session_id[:20] + "..." if len(s.session_id) > 20 else s.session_id,
            s.name or "(unnamed)",
            str(s.message_count),
        ]
        if show_last_used:
            last_used = s.last_used.strftime("%m-%d %H:%M") if s.last_used else "?"
            row_data.append(last_used)
        table.add_row(*row_data)
    
    return table


def display_react_trace(trace) -> None:
    """
    P1 Refactor: Display ReAct trace steps in panels - extracted from duplicate code.
    
    Args:
        trace: ReActTrace object containing steps and final answer
    """
    for step in trace.steps:
        observation_text = (step.observation or '')[:300]
        if step.observation and len(step.observation) > 300:
            observation_text += '...'
        
        console.print(Panel(
            f"[bold cyan]Thought[/bold cyan]: {step.thought}\n\n"
            f"[bold green]Action[/bold green]: {step.action or 'None'}\n"
            f"[bold yellow]Observation[/bold yellow]: {observation_text}",
            title=f"Step {step.step_number}",
            border_style="cyan" if not step.is_final else "green"
        ))
    
    if trace.final_answer:
        console.print(Panel(
            f"{trace.final_answer}",
            title="✓ Final Answer",
            border_style=COLORS['success']
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# Connection Management (P2 Fix: Robust error handling)
# ═══════════════════════════════════════════════════════════════════════════════

async def connect_with_retry(options: ClaudeAgentOptions) -> ClaudeSDKClient:
    """
    P2 Fix: Connect to SDK with exponential backoff retry logic.
    """
    last_error = None
    
    for attempt in range(MAX_RECONNECT_ATTEMPTS):
        try:
            client = ClaudeSDKClient(options)
            await asyncio.wait_for(client.connect(), timeout=30)
            return client
        except asyncio.TimeoutError:
            last_error = TimeoutError(f"Connection timed out (attempt {attempt + 1})")
            console.print(f"[{COLORS['warning']}]Connection timeout, retrying...[/{COLORS['warning']}]")
        except Exception as e:
            last_error = e
            console.print(f"[{COLORS['warning']}]Connection failed: {e}, retrying...[/{COLORS['warning']}]")
        
        if attempt < MAX_RECONNECT_ATTEMPTS - 1:
            delay = RECONNECT_DELAY_BASE * (2 ** attempt)
            await asyncio.sleep(delay)
    
    raise ConnectionError(f"Failed to connect after {MAX_RECONNECT_ATTEMPTS} attempts: {last_error}")


# ═══════════════════════════════════════════════════════════════════════════════
# Query Execution
# ═══════════════════════════════════════════════════════════════════════════════

async def run_query(
    client: ClaudeSDKClient,
    prompt: str,
    session_id: str,
    show_thinking: bool = False,
    thinking_budget: int = 0
) -> None:
    """
    Execute a query and display results in BENEDICTJUN style.
    
    P0 Fix: Uses proper session management via SessionManager
    P1 Fix: Handles ThinkingBlock and real streaming
    P2 Fix: Includes timeout handling
    NEW: Token usage tracking and turn counting
    """
    # Initialize stats tracking
    stats = TurnStats()
    tool_names: list[str] = []
    start_time = asyncio.get_event_loop().time()
    
    try:
        printed_header = False
        current_text = ""
        printed_content = False  # Track if we already printed content via TextBlock
        
        # Prepare params
        query_params = {"session_id": session_id}
        if thinking_budget > 0:
            query_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget
            }
            # Extended thinking usually requires higher max_tokens response limit
            # We assume the SDK/API handles the mapping or we might need to set max_tokens_to_sample
        
        with Live(
            Spinner("dots", text=f"[{COLORS['muted']}] Thinking...[/{COLORS['muted']}]"),
            refresh_per_second=10,
            transient=True
        ) as live:
            # P0 Fix: Use resume parameter for session continuity in SDK options
            # Note: session_id here is for internal session management
            await asyncio.wait_for(
                client.query(prompt, **query_params),
                timeout=QUERY_TIMEOUT
            )
            
            response_iter = client.receive_response().__aiter__()
            stream_start = asyncio.get_event_loop().time()
            while True:
                if asyncio.get_event_loop().time() - stream_start > RESPONSE_TOTAL_TIMEOUT:
                    live.stop()
                    console.print(
                        f"[{COLORS['warning']}]Response stream exceeded {RESPONSE_TOTAL_TIMEOUT}s; stopping.[/{COLORS['warning']}]"
                    )
                    break
                try:
                    message = await asyncio.wait_for(
                        response_iter.__anext__(),
                        timeout=RESPONSE_IDLE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    live.stop()
                    console.print(
                        f"[{COLORS['warning']}]No response for {RESPONSE_IDLE_TIMEOUT}s; stopping stream.[/{COLORS['warning']}]"
                    )
                    break
                except StopAsyncIteration:
                    break
                if isinstance(message, SystemMessage):
                    # P0 Fix: Capture session ID from init message
                    if message.subtype == "init":
                        new_session_id = message.data.get("session_id") if hasattr(message, 'data') else None
                        if new_session_id:
                            session_manager.set_current_session_id(new_session_id)
                    continue
                
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        # P1 Fix: Handle ThinkingBlock for Extended Thinking (Opus 4.5)
                        if isinstance(block, ThinkingBlock):
                            if show_thinking:
                                live.stop()
                                console.print(format_thinking(block.thinking))
                                live.start()
                            continue
                        
                        if isinstance(block, TextBlock):
                            live.stop()
                            console.print(Markdown(block.text))
                            current_text += block.text
                            printed_content = True  # Mark that we printed content
                            live.start()
                        
                        elif isinstance(block, ToolUseBlock):
                            live.stop()
                            console.print(format_tool_use(block.name, block.input))
                            # Track tool use as a turn
                            stats.turn_count += 1
                            if block.name:
                                tool_names.append(block.name)
                            live.start()
                        
                        elif isinstance(block, ToolResultBlock):
                            live.stop()
                            tool_text = extract_tool_result_text(block.content)
                            console.print(format_tool_result(tool_text))
                            live.start()
                
                elif isinstance(message, StreamEvent):
                    # P1 Fix: Handle stream events for real-time text display
                    if hasattr(message, 'delta') and message.delta:
                        live.update(Text(current_text + message.delta, style="white"))
                        current_text += message.delta
                    continue
                
                elif isinstance(message, ResultMessage):
                    live.stop()
                    # P0 Fix: Proper session management
                    if message.session_id:
                        session_manager.set_current_session_id(message.session_id)
                        session_manager.update_session(
                            message.session_id,
                            increment_messages=True
                        )
                    
                    # NEW: Extract token usage from ResultMessage
                    if hasattr(message, 'usage') and message.usage:
                        stats.input_tokens += getattr(message.usage, 'input_tokens', 0)
                        stats.output_tokens += getattr(message.usage, 'output_tokens', 0)
                    if hasattr(message, 'total_cost_usd') and message.total_cost_usd:
                        stats.total_cost_usd += message.total_cost_usd
                    
                    # Count this as at least one turn if we had any response
                    if stats.turn_count == 0:
                        stats.turn_count = 1
                    
                    # BUG FIX: Only print result if we haven't already printed it via TextBlock
                    if message.result and not printed_content:
                        format_final_result(message.result)
                    
                    # Always append to history (even if we printed via TextBlock)
                    if message.result:
                        append_history("assistant", message.result)
                    break
        
        # P1 Fix: Check if context needs compaction
        if context_manager.should_compact:
            console.print(f"[{COLORS['warning']}]Context is getting full. Consider using /compact.[/{COLORS['warning']}]")
        
        # NEW: Print token usage stats at end of conversation
        print_turn_stats(stats)
        total_time = asyncio.get_event_loop().time() - start_time
        tools_used = ", ".join(sorted(set(tool_names))) if tool_names else "-"
        console.print(
            f"[dim]tools={len(tool_names)} ({tools_used}) · "
            f"time={total_time:.1f}s[/dim]"
        )

    except asyncio.TimeoutError:
        console.print(f"[bold red]Error:[/bold red] Query timed out after {QUERY_TIMEOUT}s")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")

async def run_query_collect(
    client: ClaudeSDKClient,
    prompt: str,
    session_id: str,
    show_thinking: bool = False,
    thinking_budget: int = 0,
    return_stats: bool = False,
    show_progress: bool = False
) -> str | tuple[str, QueryStats]:
    """Execute a query and return the final text without rendering."""
    result_text = ""
    last_tool_text = ""
    stats = QueryStats()
    start_time = asyncio.get_event_loop().time()
    query_params = {"session_id": session_id}
    if thinking_budget > 0:
        query_params["thinking"] = {
            "type": "enabled",
            "budget_tokens": thinking_budget
        }

    try:
        await asyncio.wait_for(
            client.query(prompt, **query_params),
            timeout=QUERY_TIMEOUT
        )

        response_iter = client.receive_response().__aiter__()
        stream_start = asyncio.get_event_loop().time()
        while True:
            if asyncio.get_event_loop().time() - stream_start > RESPONSE_TOTAL_TIMEOUT:
                console.print(
                    f"[{COLORS['warning']}]Response stream exceeded {RESPONSE_TOTAL_TIMEOUT}s; stopping.[/{COLORS['warning']}]"
                )
                if not result_text and last_tool_text:
                    result_text = last_tool_text
                break
            try:
                message = await asyncio.wait_for(
                    response_iter.__anext__(),
                    timeout=RESPONSE_IDLE_TIMEOUT
                )
            except asyncio.TimeoutError:
                console.print(
                    f"[{COLORS['warning']}]No response for {RESPONSE_IDLE_TIMEOUT}s; stopping stream.[/{COLORS['warning']}]"
                )
                if not result_text and last_tool_text:
                    result_text = last_tool_text
                break
            except StopAsyncIteration:
                break
            if isinstance(message, SystemMessage):
                if message.subtype == "init":
                    new_session_id = message.data.get("session_id") if hasattr(message, 'data') else None
                    if new_session_id:
                        session_manager.set_current_session_id(new_session_id)
                continue

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result_text += block.text
                    elif isinstance(block, ToolResultBlock):
                        tool_text = extract_tool_result_text(block.content)
                        if tool_text:
                            last_tool_text = tool_text
                            result_text += tool_text
                        if show_progress:
                            console.print(format_tool_result(tool_text))
                    elif isinstance(block, ToolUseBlock):
                        stats.tool_calls += 1
                        if block.name:
                            stats.tool_names.append(block.name)
                        if show_progress:
                            console.print(format_tool_use(block.name, block.input))
            elif isinstance(message, ResultMessage):
                if message.session_id:
                    session_manager.set_current_session_id(message.session_id)
                    session_manager.update_session(
                        message.session_id,
                        increment_messages=True
                    )
                if hasattr(message, 'usage') and message.usage:
                    stats.input_tokens += getattr(message.usage, 'input_tokens', 0)
                    stats.output_tokens += getattr(message.usage, 'output_tokens', 0)
                if message.result:
                    result_text = message.result
                break

    except asyncio.TimeoutError:
        console.print(f"[bold red]Error:[/bold red] Query timed out after {QUERY_TIMEOUT}s")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")

    stats.duration_seconds = asyncio.get_event_loop().time() - start_time
    if return_stats:
        return result_text.strip(), stats
    return result_text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Main Application
# ═══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    """Main application entry point."""
    global context_manager
    
    load_dotenv()
    
    # Map custom env names to SDK defaults if needed
    if not os.getenv("ANTHROPIC_API_KEY") and os.getenv("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
    
    # Load configuration
    config = load_config()
    model = (
        config.get("model")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("AGENT_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "claude-sonnet-4-5"
    )
    max_turns = int(config.get("max_turns") or os.getenv("MAX_TURNS", "8"))  # Increased from 4 to allow more tool calls
    chatlog_max_turns = int(
        config.get("chatlog_max_turns")
        or os.getenv("CHATLOG_MAX_TURNS", "16")
    )
    config_tools = config.get("allowed_tools")
    allowed_tools = config_tools if isinstance(config_tools, list) else get_default_tools()
    continue_value = config.get("continue_conversation", os.getenv("CONTINUE_CONVERSATION", "1"))
    continue_conversation = str(continue_value).lower() in {"1", "true", "on", "yes"}
    show_thinking = config.get("show_thinking", False)
    thinking_budget = int(config.get("thinking_budget", 0))
    mouse_support_value = config.get("mouse_support", os.getenv("MOUSE_SUPPORT", "0"))
    mouse_support = str(mouse_support_value).lower() in {"1", "true", "on", "yes"}
    
    # P0 Fix: Use global session_manager (already initialized at module level)
    # Force new session structure on startup to avoid inheriting old context
    # User expects new window = new session
    resume_session_id = session_manager.create_session()

    
    # P1 Fix: Initialize context manager with correct model
    context_manager = ContextManager(model=model)
    
    # Try to load saved context state
    if CONTEXT_PATH.exists():
        try:
            context_manager = ContextManager.load_from_file(str(CONTEXT_PATH))
        except Exception:
            pass  # Start fresh if loading fails
    
    fork_next = False
    client: Optional[ClaudeSDKClient] = None
    reconnect = True
    current_continue_conversation: Optional[bool] = None
    react_mode = False  # ReAct reasoning mode toggle
    
    # === NEW: Initialize AppState for command handlers ===
    app_state = AppState(
        model=model,
        max_turns=max_turns,
        chatlog_max_turns=chatlog_max_turns,
        allowed_tools=allowed_tools,
        continue_conversation=continue_conversation,
        show_thinking=show_thinking,
        thinking_budget=thinking_budget,
        react_mode=react_mode,
        client=client,
        reconnect=reconnect,
        resume_session_id=resume_session_id,
        session_manager=session_manager,
        session_transcript=session_transcript,
        context_manager=context_manager,
        permission_manager=permission_manager,
        skill_manager=skill_manager,
        memory_storage=memory_storage,
        console=console,
    )
    
    # Create command dispatcher
    dispatcher = CommandDispatcher(app_state)
    
    # Clear screen and print dashboard
    os.system("cls" if os.name == "nt" else "clear")
    print_dashboard(model)
    
    # Setup completer with fuzzy matching
    # FuzzyWordCompleter filters as you type: /m shows /model, /memory, /max, etc.
    completer = FuzzyWordCompleter(
        list(COMMANDS_META.keys()),
        meta_dict=COMMANDS_META,
    )

    session = PromptSession(
        style=prompt_style,
        completer=completer,
        complete_while_typing=True,
        mouse_support=mouse_support
    )
    
    while True:
        try:
            with patch_stdout():
                text = await session.prompt_async(
                    HTML(f'<style fg="{COLORS["primary"]}">[INPUT]</style> ❯ '),
                    bottom_toolbar=HTML(
                        ' <style bg="#333333" fg="#ffffff"><b> / </b></style> Menu '
                        ' <style bg="#333333" fg="#ffffff"><b> ↑/↓ </b></style> Navigate '
                        ' <style bg="#333333" fg="#ffffff"><b> Enter </b></style> Select '
                        ' <style bg="#333333" fg="#ffffff"><b> Esc </b></style> Cancel '
                    ),
                )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye! 👋[/dim]")
            break
        
        if not text.strip():
            continue
        
        # Handle commands
        if text.startswith("/"):
            parts = text.strip().split(maxsplit=1)
            command = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            
            # === NEW: Try dispatcher first for simple commands ===
            result = await dispatcher.handle(text)
            
            if result.handled:
                # Sync state changes back from AppState to local variables
                model = app_state.model
                max_turns = app_state.max_turns
                allowed_tools = app_state.allowed_tools
                continue_conversation = app_state.continue_conversation
                show_thinking = app_state.show_thinking
                thinking_budget = app_state.thinking_budget
                react_mode = app_state.react_mode
                resume_session_id = app_state.resume_session_id
                
                # Check if state changes require reconnection
                if app_state.reconnect:
                    reconnect = True
                    app_state.mark_connected()  # Reset the flag
                
                # Handle exit
                if result.should_exit:
                    break
                    
                continue
            
            # === Complex commands that need more integration (handled inline) ===
            
            if command == "/skills":
                # /skills [list|enable|disable|info|refresh] [skill_name]
                subparts = arg.strip().split(maxsplit=1)
                subcommand = subparts[0].lower() if subparts else "list"
                skill_arg = subparts[1] if len(subparts) > 1 else ""
                
                if subcommand == "list" or not subcommand:
                    # List all available skills
                    skills = skill_manager.list_skills()
                    if skills:
                        table = Table(title="Available Skills", box=ROUNDED)
                        table.add_column("Name", style="cyan")
                        table.add_column("Description", style="white")
                        table.add_column("Status", style="green")
                        
                        active_skill = skill_manager.active_skill
                        for skill in skills:
                            status = "● ACTIVE" if (active_skill and active_skill.name == skill.name) else ""
                            desc = skill.description[:50] + "..." if len(skill.description) > 50 else skill.description
                            table.add_row(skill.name, desc, status)
                        
                        console.print(table)
                        console.print(f"\n[dim]Usage: /skills enable <name> | /skills disable | /skills info <name>[/dim]")
                    else:
                        console.print(f"[{COLORS['muted']}]No skills found. Create skills in .claude/skills/ directory.[/{COLORS['muted']}]")
                
                elif subcommand == "enable":
                    if skill_arg:
                        skill = skill_manager.get_skill_by_name(skill_arg)
                        if skill:
                            skill_manager.activate_skill(skill)
                            console.print(f"[{COLORS['success']}]✓ Skill '{skill.name}' enabled[/{COLORS['success']}]")
                            console.print(f"[dim]{skill.description}[/dim]")
                        else:
                            console.print(f"[{COLORS['error']}]Skill '{skill_arg}' not found[/{COLORS['error']}]")
                    else:
                        console.print(f"[{COLORS['warning']}]Usage: /skills enable <skill_name>[/{COLORS['warning']}]")
                
                elif subcommand == "disable":
                    skill_manager.deactivate_skill()
                    console.print(f"[{COLORS['success']}]✓ Skills disabled[/{COLORS['success']}]")
                
                elif subcommand == "info":
                    if skill_arg:
                        skill = skill_manager.get_skill_by_name(skill_arg)
                        if skill:
                            console.print(Panel(
                                f"[bold cyan]{skill.name}[/bold cyan]\n\n"
                                f"[dim]{skill.description}[/dim]\n\n"
                                f"[white]{skill.instructions[:500]}{'...' if len(skill.instructions) > 500 else ''}[/white]\n\n"
                                f"[dim]Path: {skill.path}[/dim]"
                                + (f"\n[dim]Allowed tools: {', '.join(skill.allowed_tools)}[/dim]" if skill.allowed_tools else ""),
                                title="Skill Details",
                                border_style=COLORS['primary']
                            ))
                        else:
                            console.print(f"[{COLORS['error']}]Skill '{skill_arg}' not found[/{COLORS['error']}]")
                    else:
                        console.print(f"[{COLORS['warning']}]Usage: /skills info <skill_name>[/{COLORS['warning']}]")
                
                elif subcommand == "refresh":
                    skill_manager.discover_skills()
                    count = len(skill_manager.list_skills())
                    console.print(f"[{COLORS['success']}]✓ Refreshed. Found {count} skills.[/{COLORS['success']}]")
                
                else:
                    console.print(f"[{COLORS['warning']}]Unknown subcommand. Use: list, enable, disable, info, refresh[/{COLORS['warning']}]")
                
                continue
            
            if command == "/memory":
                # /memory [list|forget|clear|conflicts|stats] [args]
                subparts = arg.strip().split(maxsplit=1)
                subcommand = subparts[0].lower() if subparts else "stats"
                mem_arg = subparts[1] if len(subparts) > 1 else ""
                
                if subcommand == "stats" or not subcommand:
                    # Show memory statistics
                    stats = memory_storage.get_stats()
                    profile = memory_storage.get_profile()
                    
                    console.print(Panel(
                        f"[bold]用户画像[/bold]: {profile.to_context_string()}\n\n"
                        f"[bold]记忆总数[/bold]: {stats['total_memories']}\n"
                        f"  • 偏好: {stats['by_category'].get('preference', 0)}\n"
                        f"  • 事实: {stats['by_category'].get('fact', 0)}\n"
                        f"  • 观点: {stats['by_category'].get('opinion', 0)}\n"
                        f"  • 态度: {stats['by_category'].get('attitude', 0)}\n\n"
                        f"[bold]待处理冲突[/bold]: {stats['pending_conflicts']}\n"
                        f"[dim]存储路径: {stats['storage_path']}[/dim]",
                        title="📚 Memory Status",
                        border_style=COLORS["primary"]
                    ))
                    console.print(f"\n[dim]Usage: /memory list [category] | /memory forget <id> | /memory clear | /memory conflicts[/dim]")
                
                elif subcommand == "list":
                    # List memories
                    category = None
                    if mem_arg:
                        try:
                            category = MemoryCategory(mem_arg)
                        except ValueError:
                            console.print(f"[{COLORS['warning']}]无效类别。可选: preference, fact, opinion, attitude[/{COLORS['warning']}]")
                            continue
                    
                    memories = memory_storage.list_memories(category=category, limit=20)
                    
                    if memories:
                        table = Table(title=f"记忆列表{f' ({category.value})' if category else ''}", box=ROUNDED)
                        table.add_column("ID", style="cyan", width=8)
                        table.add_column("类别", style="green", width=10)
                        table.add_column("内容", style="white")
                        table.add_column("日期", style="dim", width=10)
                        
                        for mem in memories:
                            content = mem.content[:40] + "..." if len(mem.content) > 40 else mem.content
                            table.add_row(
                                mem.id,
                                mem.category.value,
                                content,
                                mem.created_at[:10]
                            )
                        
                        console.print(table)
                    else:
                        console.print(f"[{COLORS['muted']}]没有记忆记录[/{COLORS['muted']}]")
                
                elif subcommand == "forget":
                    if mem_arg:
                        memory = memory_storage.get_memory(mem_arg)
                        if memory:
                            if memory_storage.delete_memory(mem_arg):
                                console.print(f"[{COLORS['success']}]✓ 已删除记忆: {memory.content[:30]}...[/{COLORS['success']}]")
                            else:
                                console.print(f"[{COLORS['error']}]删除失败[/{COLORS['error']}]")
                        else:
                            console.print(f"[{COLORS['error']}]未找到ID为 {mem_arg} 的记忆[/{COLORS['error']}]")
                    else:
                        console.print(f"[{COLORS['warning']}]Usage: /memory forget <memory_id>[/{COLORS['warning']}]")
                
                elif subcommand == "clear":
                    count = memory_storage.clear_all()
                    console.print(f"[{COLORS['success']}]✓ 已清除 {count} 条记忆[/{COLORS['success']}]")
                
                elif subcommand == "conflicts":
                    conflicts = memory_storage.get_conflicts()
                    if conflicts:
                        console.print(f"[bold yellow]待处理的记忆冲突 ({len(conflicts)})[/bold yellow]\n")
                        for c in conflicts:
                            console.print(Panel(
                                f"[bold]现有记忆[/bold]: {c.existing_content}\n"
                                f"[bold]新信息[/bold]: {c.new_content}\n\n"
                                f"[dim]冲突ID: {c.id}[/dim]",
                                title=f"⚠️ 冲突 ({c.category.value})",
                                border_style="yellow"
                            ))
                            console.print(f"  解决: /memory resolve {c.id} [replace|keep_both|ignore]\n")
                    else:
                        console.print(f"[{COLORS['success']}]✓ 没有待处理的冲突[/{COLORS['success']}]")
                
                elif subcommand == "resolve":
                    # /memory resolve <conflict_id> <action>
                    resolve_parts = mem_arg.split(maxsplit=1)
                    if len(resolve_parts) == 2:
                        conflict_id, action = resolve_parts
                        if action in ["replace", "keep_both", "ignore"]:
                            if memory_storage.resolve_conflict(conflict_id, action):
                                console.print(f"[{COLORS['success']}]✓ 冲突已解决 (action: {action})[/{COLORS['success']}]")
                            else:
                                console.print(f"[{COLORS['error']}]未找到冲突ID: {conflict_id}[/{COLORS['error']}]")
                        else:
                            console.print(f"[{COLORS['warning']}]无效操作。可选: replace, keep_both, ignore[/{COLORS['warning']}]")
                    else:
                        console.print(f"[{COLORS['warning']}]Usage: /memory resolve <conflict_id> <replace|keep_both|ignore>[/{COLORS['warning']}]")
                
                elif subcommand == "profile":
                    # Show/edit profile
                    if mem_arg:
                        # Parse key=value
                        if "=" in mem_arg:
                            key, value = mem_arg.split("=", 1)
                            memory_storage.update_profile(**{key.strip(): value.strip()})
                            console.print(f"[{COLORS['success']}]✓ 用户画像已更新: {key} = {value}[/{COLORS['success']}]")
                        else:
                            console.print(f"[{COLORS['warning']}]Usage: /memory profile <key>=<value>[/{COLORS['warning']}]")
                    else:
                        profile = memory_storage.get_profile()
                        console.print(f"[cyan]用户画像:[/cyan]")
                        console.print(f"  姓名: {profile.name or '(未设置)'}")
                        console.print(f"  语言: {profile.language}")
                        console.print(f"  职业: {profile.occupation or '(未设置)'}")
                
                else:
                    console.print(f"[{COLORS['warning']}]Unknown subcommand. Use: stats, list, forget, clear, conflicts, resolve, profile[/{COLORS['warning']}]")
                
                continue
            
            if command == "/chatlog":
                # /chatlog [query|stats|person] [args]
                from src.chatlog import query_chatlog_sync, get_chatlog_stats_sync
                from src.chatlog.loader import get_chatlog_loader
                
                subparts = arg.strip().split(maxsplit=1)
                subcommand = subparts[0].lower() if subparts else "stats"
                chatlog_arg = subparts[1] if len(subparts) > 1 else ""
                
                if subcommand == "stats" or not subcommand:
                    # Show chatlog statistics
                    result = get_chatlog_stats_sync()
                    console.print(Markdown(result))
                
                elif subcommand == "query":
                    # Query chatlog with a question
                    if chatlog_arg:
                        console.print(f"[{COLORS['muted']}]正在检索聊天记录...[/{COLORS['muted']}]")
                        # Check if there's a @person mention
                        target_person = None
                        if "@" in chatlog_arg:
                            parts = chatlog_arg.split("@")
                            chatlog_arg = parts[0].strip()
                            target_person = parts[1].split()[0] if parts[1] else None
                        
                        result = query_chatlog_sync(
                            question=chatlog_arg,
                            target_person=target_person,
                            max_results=100
                        )
                        console.print(Markdown(result))
                    else:
                        console.print(f"[{COLORS['warning']}]Usage: /chatlog query <问题> [@人物][/{COLORS['warning']}]")
                        console.print(f"[dim]示例: /chatlog query 冯天奇的消费习惯怎么样 @冯天奇[/dim]")
                
                elif subcommand == "person":
                    # Search for a specific person
                    if chatlog_arg:
                        loader = get_chatlog_loader()
                        if not loader.is_loaded:
                            loader.load()
                        
                        person_messages = loader.get_messages_by_sender(chatlog_arg)
                        if person_messages:
                            console.print(f"[cyan]找到 {len(person_messages)} 条来自「{chatlog_arg}」的消息[/cyan]")
                            console.print(f"[dim]显示最近20条:[/dim]\n")
                            for msg in person_messages[-20:]:
                                console.print(f"[dim]{msg.timestamp}[/dim] {msg.content}")
                        else:
                            console.print(f"[{COLORS['warning']}]未找到「{chatlog_arg}」的消息[/{COLORS['warning']}]")
                    else:
                        # List all senders
                        loader = get_chatlog_loader()
                        if not loader.is_loaded:
                            loader.load()
                        
                        console.print("[cyan]聊天记录中的发送者:[/cyan]")
                        for sender in loader.senders:
                            count = len(loader.get_messages_by_sender(sender))
                            console.print(f"  • {sender} ({count} 条消息)")
                
                elif subcommand == "reload":
                    # Reload chatlog file
                    from src.chatlog.loader import ChatlogLoader
                    global _chatlog_loader
                    loader = ChatlogLoader()
                    if loader.load():
                        console.print(f"[{COLORS['success']}]✓ 聊天记录已重新加载 ({loader.message_count} 条消息)[/{COLORS['success']}]")
                    else:
                        console.print(f"[{COLORS['error']}]✗ 加载失败[/{COLORS['error']}]")
                
                else:
                    console.print(f"[{COLORS['warning']}]Unknown subcommand. Use: stats, query, person, reload[/{COLORS['warning']}]")
                    console.print(f"[dim]示例:[/dim]")
                    console.print(f"  /chatlog stats           - 查看统计信息")
                    console.print(f"  /chatlog query <问题>    - 智能检索")
                    console.print(f"  /chatlog person <名字>   - 查看特定人物消息")
                
                continue
            
            if command == "/react":
                # /react [on|off|goal] [goal_text]
                subparts = arg.strip().split(maxsplit=1)
                subcommand = subparts[0].lower() if subparts else ""
                goal_text = subparts[1] if len(subparts) > 1 else ""
                
                if subcommand == "on":
                    react_mode = True
                    console.print(f"[{COLORS['success']}]✓ ReAct mode enabled[/{COLORS['success']}]")
                    console.print(f"[dim]All queries will use Thought → Action → Observation loop[/dim]")
                
                elif subcommand == "off":
                    react_mode = False
                    console.print(f"[{COLORS['success']}]✓ ReAct mode disabled[/{COLORS['success']}]")
                
                elif subcommand == "goal" and goal_text:
                    # Run a single ReAct task
                    console.print(f"[{COLORS['primary']}]🧠 Running ReAct for: {goal_text}[/{COLORS['primary']}]")
                    
                    if client is None:
                        # Connect first
                        options = ClaudeAgentOptions(
                            model=model,
                            max_turns=effective_max_turns,
                            allowed_tools=allowed_tools,
                            mcp_servers={
                                "memory": create_memory_mcp_server(),
                                "web": create_web_mcp_server(),
                                "chatlog": create_chatlog_mcp_server(),
                            },
                        )
                        try:
                            client = await connect_with_retry(options)
                        except ConnectionError as e:
                            console.print(f"[{COLORS['error']}]Connection failed: {e}[/{COLORS['error']}]")
                            continue
                    
                    try:
                        # Run ReAct
                        controller = ReActController(client, max_steps=10, verbose=False)
                        trace = await controller.run(goal_text, session_id="react")
                        
                        # P1 Refactor: Use helper function for trace display
                        display_react_trace(trace)
                        console.print(f"[dim]ReAct completed: {len(trace.steps)} steps, success={trace.success}[/dim]")
                        
                    except Exception as e:
                        console.print(f"[{COLORS['error']}]ReAct error: {e}[/{COLORS['error']}]")
                
                elif not subcommand:
                    # Show status
                    status = "ON" if react_mode else "OFF"
                    console.print(f"[cyan]ReAct mode:[/cyan] {status}")
                    console.print(f"\n[dim]Usage:[/dim]")
                    console.print(f"  /react on          - Enable ReAct for all queries")
                    console.print(f"  /react off         - Disable ReAct mode")
                    console.print(f"  /react goal <task> - Run single ReAct task")
                
                else:
                    console.print(f"[{COLORS['warning']}]Usage: /react [on|off|goal <task>][/{COLORS['warning']}]")
                
                continue
            
            if command == "/route":
                # /route [auto|manual|test|info] [test_prompt]
                router = get_router()
                subparts = arg.strip().split(maxsplit=1)
                subcommand = subparts[0].lower() if subparts else "info"
                test_prompt = subparts[1] if len(subparts) > 1 else ""
                
                if subcommand == "auto":
                    router.enabled = True
                    console.print(f"[{COLORS['success']}]✓ 自动路由已启用[/{COLORS['success']}]")
                
                elif subcommand == "manual":
                    router.enabled = False
                    console.print(f"[{COLORS['success']}]✓ 手动模式，使用 /model 切换[/{COLORS['success']}]")
                
                elif subcommand == "test":
                    if test_prompt:
                        decision = router.route(test_prompt)
                        task_emoji = {
                            TaskType.MATH: "🔢",
                            TaskType.CODE: "💻",
                            TaskType.REASONING: "🧠",
                            TaskType.TOOL_USE: "🔧",
                            TaskType.CHAT: "💬",
                        }.get(decision.task_type, "📍")
                        console.print(f"[cyan]测试输入:[/cyan] {test_prompt[:50]}...")
                        console.print(f"[cyan]路由结果:[/cyan] {task_emoji} {decision.model}")
                        console.print(f"[cyan]原因:[/cyan] {decision.reason}")
                        console.print(f"[cyan]支持工具:[/cyan] {'是' if decision.supports_tools else '否'}")
                        console.print(f"[cyan]置信度:[/cyan] {decision.confidence:.0%}")
                    else:
                        console.print(f"[{COLORS['warning']}]用法: /route test <测试提示词>[/{COLORS['warning']}]")
                
                elif subcommand == "info" or not subcommand:
                    status = "启用" if router.enabled else "禁用"
                    console.print(f"[cyan]自动路由:[/cyan] {status}")
                    console.print(f"[cyan]当前模型:[/cyan] {model}")
                    console.print()
                    # Show model info
                    for m in [router.MODEL_REASONER, router.MODEL_CHAT]:
                        info = router.get_model_info(m)
                        marker = "→ " if m == model else "  "
                        console.print(f"{marker}[bold]{info['name']}[/bold]")
                        console.print(f"   {info['description']}")
                        console.print(f"   工具支持: {'✓' if info['supports_tools'] else '✗'}")
                
                else:
                    console.print(f"[{COLORS['warning']}]用法: /route [auto|manual|test|info][/{COLORS['warning']}]")
                
                continue
            
            if command == "/permissions":
                # /permissions [add|remove|list] [tool_name]
                subparts = arg.strip().split(maxsplit=1)
                subcommand = subparts[0].lower() if subparts else "list"
                tool_arg = subparts[1] if len(subparts) > 1 else ""
                
                if subcommand == "list" or not subcommand:
                    # Show current permissions
                    status = permission_manager.get_status()
                    
                    table = Table(title="Permission Settings", box=ROUNDED)
                    table.add_column("Category", style="cyan")
                    table.add_column("Tools", style="white")
                    
                    if status["allowlist"]:
                        table.add_row("✓ Always Allowed", ", ".join(status["allowlist"]))
                    if status["denylist"]:
                        table.add_row("✗ Denied", ", ".join(status["denylist"]))
                    table.add_row("Safe (auto-allowed)", ", ".join(status["safe_tools"]))
                    table.add_row("Dangerous (ask)", ", ".join(status["dangerous_tools"]))
                    
                    console.print(table)
                    console.print(f"\n[dim]Usage: /permissions add <tool> | /permissions remove <tool>[/dim]")
                
                elif subcommand == "add":
                    if tool_arg:
                        permission_manager.add_to_allowlist(tool_arg)
                        console.print(f"[{COLORS['success']}]✓ Added '{tool_arg}' to always-allowed list[/{COLORS['success']}]")
                    else:
                        console.print(f"[{COLORS['warning']}]Usage: /permissions add <tool_name>[/{COLORS['warning']}]")
                
                elif subcommand == "remove":
                    if tool_arg:
                        permission_manager.remove_from_allowlist(tool_arg)
                        console.print(f"[{COLORS['success']}]✓ Removed '{tool_arg}' from always-allowed list[/{COLORS['success']}]")
                    else:
                        console.print(f"[{COLORS['warning']}]Usage: /permissions remove <tool_name>[/{COLORS['warning']}]")
                
                elif subcommand == "reset":
                    permission_manager.reset()
                    console.print(f"[{COLORS['success']}]✓ Permissions reset to defaults[/{COLORS['success']}]")
                
                else:
                    console.print(f"[{COLORS['warning']}]Unknown subcommand. Use: list, add, remove, reset[/{COLORS['warning']}]")
                
                continue
            
            if command in ("/clear", "/cls"):
                context_manager.clear()
                # CRITICAL: Reset client to force new session with zero context
                if client:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    client = None
                reconnect = True
                # Create brand new session ID
                resume_session_id = session_manager.create_session()
                os.system("cls" if os.name == "nt" else "clear")
                print_dashboard(model)
                console.print(f"[{COLORS['success']}]✓ 上下文已清除，新会话: {resume_session_id[:16]}...[/{COLORS['success']}]")
                continue
            
            console.print(f"[{COLORS['warning']}]Unknown command. Type /help for available commands.[/{COLORS['warning']}]")
            continue
        
        # Handle regular query
        resume_session_id = session_manager.get_current_session_id()
        if resume_session_id is None:
            resume_session_id = session_manager.create_session()
        
        append_history("user", text)
        
        # Save original text for memory extraction (before skill injection modifies it)
        original_text = text
        chatlog_task_chain = False
        chatlog_question = original_text
        
        # NEW: Chatlog trigger detection - auto-inject prompt for evidence-based queries
        if should_use_chatlog_chain(text):
            console.print(f"[{COLORS['secondary']}]🔍 检测到需要历史证据的问题，将自动查询聊天记录[/{COLORS['secondary']}]")
            chatlog_task_chain = True
            chatlog_question = original_text
            text = f"""## 重要提示
你需要先调用 mcp__chatlog__query_chatlog 工具来查询相关的聊天记录，
然后基于查询结果给出有证据支持的分析。
在最终回答中必须引用具体的对话片段作为证据，使用markdown引用格式：
> [时间] 发送者: 内容
调用工具时，question 参数必须使用用户原话，不要自行扩展关键词或场景。
需要进行两轮检索：第一轮寻找支持结论的证据，第二轮主动寻找相反证据并解释冲突点。

强制使用 Task 子代理链：
1) 调用 Task 子代理 chatlog-searcher，输入必须包含原始用户问题。
2) 调用 Task 子代理 chatlog-refuter，输入必须包含原始用户问题。
3) 调用 Task 子代理 chatlog-synthesizer，输入包含前两步的原始输出，用于综合结论。

## 用户问题
{text}"""

        # NEW: Skill activation (explicit only; no auto-matching)
        if skill_manager.active_skill:
            skill_injection = skill_manager.activate_skill(skill_manager.active_skill)
            console.print(f"[{COLORS['secondary']}]📚 Using skill: {skill_manager.active_skill.name}[/{COLORS['secondary']}]")
            text = f"{skill_injection}\n\n---\n\n## User Request:\n{text}"
        
        # NEW: Dynamic model routing based on task type
        router = get_router()
        decision = router.route(text, require_tools=chatlog_task_chain)
        routed_model = decision.model
        routed_tools = allowed_tools if decision.supports_tools else []
        effective_continue_conversation = (
            False if chatlog_task_chain else continue_conversation
        )
        
        # Display routing decision
        task_emoji = {
            TaskType.MATH: "🔢",
            TaskType.CODE: "💻",
            TaskType.REASONING: "🧠",
            TaskType.TOOL_USE: "🔧",
            TaskType.CHAT: "💬",
        }.get(decision.task_type, "📍")
        console.print(f"[{COLORS['muted']}]{task_emoji} {decision.reason}[/{COLORS['muted']}]")
        
        # Check if model/continue behavior changed and needs reconnection
        if routed_model != model:
            model = routed_model
            reconnect = True
        if current_continue_conversation is None or (
            current_continue_conversation != effective_continue_conversation
        ):
            reconnect = True
        
        effective_max_turns = max_turns
        if chatlog_task_chain:
            effective_max_turns = max(max_turns, chatlog_max_turns)

        if reconnect or client is None:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            
            # P0 Fix: Include agents in options for subagent support
            # Use routed model and tools
            # Build MCP servers dict - include memory and chatlog for all, web for tool-capable models
            mcp_servers = {
                "memory": create_memory_mcp_server(),
                "chatlog": create_chatlog_mcp_server(),
            }
            if decision.supports_tools:
                mcp_servers["web"] = create_web_mcp_server()
            
            options = ClaudeAgentOptions(
                model=model,
                max_turns=effective_max_turns,
                allowed_tools=routed_tools,
                continue_conversation=effective_continue_conversation,
                agents=AGENT_DEFINITIONS if decision.supports_tools else {},  # No subagents for R1
                resume=None,  # Fresh session - no context inheritance from previous windows
                mcp_servers=mcp_servers,
            )
            
            try:
                # P2 Fix: Use connection with retry
                client = await connect_with_retry(options)
            except ConnectionError as e:
                console.print(f"[bold red]Connection failed:[/bold red] {e}")
                continue
            
            reconnect = False
            current_continue_conversation = effective_continue_conversation
        
        if chatlog_task_chain:
            console.print(f"[{COLORS['secondary']}]🧩 Running chatlog task chain[/{COLORS['secondary']}]")
            console.print(f"[{COLORS['muted']}]Step 1/3: chatlog-searcher[/{COLORS['muted']}]")
            search_prompt = (
                "Call Task subagent chatlog-searcher.\n"
                "<QUESTION>\n"
                f"{chatlog_question}\n"
                "</QUESTION>"
            )
            search_output, search_stats = await run_query_collect(
                client,
                search_prompt,
                session_id=resume_session_id,
                show_thinking=show_thinking,
                thinking_budget=thinking_budget,
                return_stats=True,
                show_progress=True
            )
            if search_output:
                console.print(Markdown("#### chatlog-searcher 输出\n" + truncate_text(search_output, 2000)))
            evidence_score = count_quote_lines(search_output)
            evidence_note = (
                "证据较弱，注意结论不确定性。"
                if evidence_score < 2 else "证据充足。"
            )

            refuter_session_id = session_manager.fork_session(resume_session_id, name="Chatlog refuter")
            console.print(f"[{COLORS['muted']}]Step 2/3: chatlog-refuter[/{COLORS['muted']}]")
            refute_prompt = (
                "Call Task subagent chatlog-refuter.\n"
                "<QUESTION>\n"
                f"{chatlog_question}\n"
                "</QUESTION>"
            )
            refute_output, refute_stats = await run_query_collect(
                client,
                refute_prompt,
                session_id=refuter_session_id,
                show_thinking=show_thinking,
                thinking_budget=thinking_budget,
                return_stats=True,
                show_progress=True
            )
            if refute_output:
                console.print(Markdown("#### chatlog-refuter 输出\n" + truncate_text(refute_output, 2000)))

            # Truncate outputs to prevent context overflow (max 500 chars each)
            def _truncate(text: str, max_chars: int = 500) -> str:
                if not text or len(text) <= max_chars:
                    return text or ""
                return text[:max_chars] + "\n...(已截断)"
            
            search_truncated = _truncate(search_output, 500)
            refute_truncated = _truncate(refute_output, 500)
            
            synth_prompt = (
                "Call Task subagent chatlog-synthesizer.\n\n"
                f"User question: {chatlog_question}\n\n"
                f"Evidence strength: {evidence_note}\n\n"
                "Evidence (truncated):\n"
                f"{search_truncated}\n\n"
                "Counter-evidence (truncated):\n"
                f"{refute_truncated}"
            )
            console.print(f"[{COLORS['muted']}]Step 3/3: chatlog-synthesizer[/{COLORS['muted']}]")
            final_output, synth_stats = await run_query_collect(
                client,
                synth_prompt,
                session_id=resume_session_id,
                show_thinking=show_thinking,
                thinking_budget=thinking_budget,
                return_stats=True,
                show_progress=True
            )

            if final_output:
                console.print(Markdown("#### chatlog-synthesizer 输出"))
                format_final_result(final_output)
                append_history("assistant", final_output)
            else:
                fallback_parts = [
                    "未能生成综合结论（模型未返回结果或响应超时）。",
                ]
                if search_output or refute_output:
                    fallback_parts.append("\n证据（截断）：\n")
                    fallback_parts.append(truncate_text(search_output))
                    fallback_parts.append("\n反证（截断）：\n")
                    fallback_parts.append(truncate_text(refute_output))
                fallback_text = "\n".join(fallback_parts).strip()
                format_final_result(fallback_text)
                append_history("assistant", fallback_text)
            def _print_step_stats(label: str, stats: QueryStats) -> None:
                tool_names = ", ".join(sorted(set(stats.tool_names))) if stats.tool_names else "-"
                console.print(
                    f"[dim]{label}: tools={stats.tool_calls} ({tool_names}) · "
                    f"time={stats.duration_seconds:.1f}s · "
                    f"tokens={stats.input_tokens}/{stats.output_tokens}[/dim]"
                )
            _print_step_stats("searcher", search_stats)
            _print_step_stats("refuter", refute_stats)
            _print_step_stats("synthesizer", synth_stats)
            total_time = search_stats.duration_seconds + refute_stats.duration_seconds + synth_stats.duration_seconds
            console.print(f"[dim]subagent_chain=chatlog-evidence total_time={total_time:.1f}s[/dim]")
            continue

        # Check if ReAct mode is enabled
        if react_mode:
            console.print(f"[{COLORS['secondary']}]🧠 ReAct Mode[/{COLORS['secondary']}]")
            try:
                controller = ReActController(client, max_steps=10, verbose=False)
                trace = await controller.run(original_text, session_id=resume_session_id)
                
                # P1 Refactor: Use helper function for trace display
                display_react_trace(trace)
                console.print(f"[dim]ReAct: {len(trace.steps)} steps, success={trace.success}[/dim]")
                
            except Exception as e:
                console.print(f"[{COLORS['error']}]ReAct error: {e}[/{COLORS['error']}]")
                console.print(f"[dim]Falling back to normal query...[/dim]")
                await run_query(
                    client, 
                    text, 
                    session_id=resume_session_id, 
                    show_thinking=show_thinking,
                    thinking_budget=thinking_budget
                )
        else:
            await run_query(
                client, 
                text, 
                session_id=resume_session_id, 
                show_thinking=show_thinking,
                thinking_budget=thinking_budget
            )
        
        # Async memory extraction after conversation
        # Use GPT-5-nano via Poe API for cost-effective extraction
        try:
            extractor = get_memory_extractor()
            if extractor.poe.is_configured:
                # Get conversation history for extraction
                conversation_text = f"用户: {original_text}\n助手: [已回复]"
                
                # Run extraction (async, non-blocking report)
                report = await extractor.extract_and_report(conversation_text)
                if report and "提取了" in report:
                    console.print(f"[{COLORS['muted']}]{report}[/{COLORS['muted']}]")
        except Exception:
            pass  # Silently ignore extraction errors
    
    # Cleanup
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    
    # Save context state on exit
    try:
        context_manager.save_to_file(str(CONTEXT_PATH))
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())

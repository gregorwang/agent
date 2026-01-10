"""
Utility Command Handlers

Handles utility and information commands:
- /help - Show all commands
- /save - Save current config
- /info - Show server info
- /history - Show history file path
- /context - Show context statistics
- /compact - Compact context with summary
- /clear, /cls - Clear screen and context
- /agents - List available subagents
- /exit, /quit, /q - Exit application
"""

import json
import os
from pathlib import Path

from rich.table import Table
from rich.syntax import Syntax
from rich.box import ROUNDED

from .base import CommandHandler, CommandResult, AppState
from src.ui.styles import COLORS


class HelpHandler(CommandHandler):
    """Handles /help command - show all commands."""
    
    commands = ["/help"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        from tui_agent import print_slash_hints, COMMANDS_META
        
        print_slash_hints()
        
        # Extended help
        extra_commands = [
            ("/session", "Show current session ID"),
            ("/reset", "Clear current session"),
            ("/model [name]", "Show or set model"),
            ("/tools [list]", "Show or set allowed tools"),
            ("/max [n]", "Show or set max turns"),
            ("/continue [on|off]", "Toggle continue conversation"),
            ("/resume [id]", "Resume a specific session"),
            ("/fork", "Fork current session for next query"),
            ("/agents", "List available subagents"),
            ("/thinking [on|budget]", "Toggle thinking display/budget"),
            ("/compact", "Compact context with AI summary"),
            ("/context", "Show context statistics"),
            ("/sessions", "List recent sessions"),
            ("/info", "Show server info"),
            ("/save", "Save current config"),
            ("/history", "Show history file path"),
        ]
        
        grid = Table.grid(expand=True, padding=(0, 2))
        grid.add_column(style=COLORS['secondary'], no_wrap=True)
        grid.add_column(style="dim white")
        
        for cmd, desc in extra_commands:
            grid.add_row(cmd, desc)
        
        self.console.print(grid)
        return CommandResult.success()


class ExitHandler(CommandHandler):
    """Handles /exit, /quit, /q commands - exit application."""
    
    commands = ["/exit", "/quit", "/q"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        self.console.print("\n[dim]Goodbye! 👋[/dim]")
        return CommandResult.exit()


class SaveHandler(CommandHandler):
    """Handles /save command - save current config."""
    
    commands = ["/save"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        from tui_agent import CONFIG_PATH, CONTEXT_PATH
        
        CONFIG_PATH.write_text(
            json.dumps({
                "model": self.state.model,
                "max_turns": self.state.max_turns,
                "allowed_tools": self.state.allowed_tools,
                "continue_conversation": "1" if self.state.continue_conversation else "0",
                "show_thinking": self.state.show_thinking,
                "thinking_budget": self.state.thinking_budget,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        
        # Also save context state
        self.state.context_manager.save_to_file(str(CONTEXT_PATH))
        self.console.print(f"[{COLORS['success']}]✓ Saved to {CONFIG_PATH}[/{COLORS['success']}]")
        return CommandResult.success()


class InfoHandler(CommandHandler):
    """Handles /info command - show server info."""
    
    commands = ["/info"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if self.state.client:
            try:
                info = await self.state.client.get_server_info()
                self.console.print(Syntax(
                    json.dumps(info or {}, indent=2, ensure_ascii=False),
                    "json",
                    theme="monokai",
                ))
            except Exception as e:
                self.console.print(f"[{COLORS['error']}]Failed to get info: {e}[/{COLORS['error']}]")
        else:
            self.console.print(f"[{COLORS['muted']}]Not connected yet[/{COLORS['muted']}]")
        
        return CommandResult.success()


class HistoryHandler(CommandHandler):
    """Handles /history command - show history file path."""
    
    commands = ["/history"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        from tui_agent import HISTORY_PATH
        self.console.print(f"[cyan]History file:[/cyan] {HISTORY_PATH.absolute()}")
        return CommandResult.success()


class ContextHandler(CommandHandler):
    """Handles /context command - show context statistics."""
    
    commands = ["/context"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        stats = self.state.context_manager.get_stats()
        self.console.print(f"[cyan]Token usage:[/cyan] {stats['current_tokens']}/{stats['max_tokens']} ({stats['usage_ratio']:.1%})")
        self.console.print(f"[cyan]Messages:[/cyan] {stats['message_count']}")
        self.console.print(f"[cyan]Has summary:[/cyan] {'Yes' if stats['has_summary'] else 'No'}")
        
        if stats['usage_ratio'] > 0.8:
            self.console.print(f"[{COLORS['warning']}]Warning: Context is getting full. Consider /compact[/{COLORS['warning']}]")
        
        return CommandResult.success()


class CompactHandler(CommandHandler):
    """Handles /compact command - compact context with summary."""
    
    commands = ["/compact"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if self.state.client:
            self.console.print(f"[{COLORS['muted']}]Generating summary...[/{COLORS['muted']}]")
            self.state.context_manager.clear_keep_summary()
            self.console.print(f"[{COLORS['success']}]✓ Context compacted with summary[/{COLORS['success']}]")
            stats = self.state.context_manager.get_stats()
            self.console.print(f"[cyan]New token usage:[/cyan] {stats['current_tokens']}/{stats['max_tokens']}")
        else:
            self.state.context_manager.clear_keep_summary()
            self.console.print(f"[{COLORS['success']}]✓ Context compacted (basic summary)[/{COLORS['success']}]")
        
        return CommandResult.success()


class ClearHandler(CommandHandler):
    """Handles /clear, /cls commands - clear screen and context."""
    
    commands = ["/clear", "/cls"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        from tui_agent import print_dashboard
        
        self.state.context_manager.clear()
        os.system("cls" if os.name == "nt" else "clear")
        print_dashboard(self.state.model)
        return CommandResult.success()


class AgentsHandler(CommandHandler):
    """Handles /agents command - list available subagents."""
    
    commands = ["/agents"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        from src.agents.definitions import get_agent_definitions
        
        agents = get_agent_definitions()
        table = Table(title="Available Subagents", box=ROUNDED)
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Model", style="green")
        table.add_column("Tools", style="dim")
        
        for name, agent in agents.items():
            table.add_row(
                name,
                agent.description[:50] + "..." if len(agent.description) > 50 else agent.description,
                agent.model,
                ", ".join(agent.tools) if agent.tools else "inherit"
            )
        
        self.console.print(table)
        self.console.print(f"\n[dim]Use these with the Task tool, e.g., 'Ask explorer to find all Python files'[/dim]")
        return CommandResult.success()


# Export all handlers
UTILITY_HANDLERS = [
    HelpHandler,
    ExitHandler,
    SaveHandler,
    InfoHandler,
    HistoryHandler,
    ContextHandler,
    CompactHandler,
    ClearHandler,
    AgentsHandler,
]

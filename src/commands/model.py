"""
Model Command Handlers

Handles model and configuration commands:
- /model - Show or set model
- /tools - Show or set allowed tools
- /max - Show or set max turns
- /continue - Toggle continue conversation
- /thinking - Toggle thinking display/budget
"""

from rich.table import Table
from rich.box import ROUNDED

from .base import CommandHandler, CommandResult, AppState
from src.ui.styles import COLORS
from src.ui.components import SelectionMenu


class ModelHandler(CommandHandler):
    """Handles /model command - show or set model."""
    
    commands = ["/model"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if arg:
            self.state.model = arg.strip()
            from src.context.manager import ContextManager
            self.state.context_manager = ContextManager(model=self.state.model)
            self.state.needs_reconnect()
            self.console.print(f"[{COLORS['success']}]✓ Model set to: {self.state.model}[/{COLORS['success']}]")
        else:
            # Use the reusable SelectionMenu component
            models_data = [
                {"id": "claude-opus-4-5", "name": "Opus 4.5", "desc": "Most capable for complex work", "extra": "$15/Mtok", "badge": "New"},
                {"id": "claude-sonnet-4-5", "name": "Sonnet 4.5", "desc": "Balanced intelligence & speed (Recommended)", "extra": "$3/Mtok", "badge": "New"},
                {"id": "claude-haiku-4-5", "name": "Haiku 4.5", "desc": "Fastest for quick answers", "extra": "$1/Mtok"},
                {"id": "claude-opus-4-1", "name": "Opus 4.1", "desc": "Previous generation flagship", "extra": "$15/Mtok"},
                {"id": "claude-sonnet-4", "name": "Sonnet 4", "desc": "Previous generation balanced", "extra": "$3/Mtok"},
            ]
            
            menu = SelectionMenu(
                title="Select Model",
                items=models_data,
                description="Switch between Claude models. Applies to this session.",
                current_value=self.state.model,
            )
            
            selected_id = await menu.run()
            
            if selected_id:
                self.state.model = selected_id
                from src.context.manager import ContextManager
                self.state.context_manager = ContextManager(model=self.state.model)
                self.state.needs_reconnect()
                self.console.print(f"[{COLORS['success']}]✓ Model set to: {self.state.model}[/{COLORS['success']}]")
            else:
                self.console.print(f"[{COLORS['muted']}]Cancelled[/{COLORS['muted']}]")
        
        return CommandResult.success()


class ToolsHandler(CommandHandler):
    """Handles /tools command - show or set allowed tools."""
    
    commands = ["/tools"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if arg:
            self.state.allowed_tools = [t.strip() for t in arg.split(",") if t.strip()]
            # Ensure Task is included for subagent support
            if "Task" not in self.state.allowed_tools:
                self.state.allowed_tools.append("Task")
                self.console.print(f"[{COLORS['warning']}]Note: 'Task' tool added for subagent support[/{COLORS['warning']}]")
            self.console.print(f"[{COLORS['success']}]✓ Tools: {', '.join(self.state.allowed_tools)}[/{COLORS['success']}]")
            self.state.needs_reconnect()
        else:
            self.console.print(f"[cyan]Tools:[/cyan] {', '.join(self.state.allowed_tools)}")
        
        return CommandResult.success()


class MaxTurnsHandler(CommandHandler):
    """Handles /max command - show or set max turns."""
    
    commands = ["/max"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if arg:
            try:
                self.state.max_turns = int(arg)
                self.console.print(f"[{COLORS['success']}]✓ Max turns: {self.state.max_turns}[/{COLORS['success']}]")
                self.state.needs_reconnect()
            except ValueError:
                self.console.print(f"[{COLORS['error']}]✗ Invalid number[/{COLORS['error']}]")
        else:
            options = [2, 4, 6, 8, 12, 16, 24, 32]
            items = [
                {"id": str(val), "name": str(val), "desc": "turns"} for val in options
            ]
            menu = SelectionMenu(
                title="Set Max Turns",
                items=items,
                description="Select a max turn limit for this session.",
                current_value=str(self.state.max_turns),
            )
            selected_id = await menu.run()
            if selected_id:
                self.state.max_turns = int(selected_id)
                self.console.print(f"[{COLORS['success']}]✓ Max turns: {self.state.max_turns}[/{COLORS['success']}]")
                self.state.needs_reconnect()
            else:
                self.console.print(f"[cyan]Max turns:[/cyan] {self.state.max_turns}")

        return CommandResult.success()


class ContinueHandler(CommandHandler):
    """Handles /continue command - toggle continue conversation."""
    
    commands = ["/continue"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if arg:
            value = arg.strip().lower()
            if value in {"on", "1", "true"}:
                self.state.continue_conversation = True
                self.console.print(f"[{COLORS['success']}]✓ Continue conversation: ON[/{COLORS['success']}]")
                self.state.needs_reconnect()
            elif value in {"off", "0", "false"}:
                self.state.continue_conversation = False
                self.console.print(f"[{COLORS['success']}]✓ Continue conversation: OFF[/{COLORS['success']}]")
                self.state.needs_reconnect()
            else:
                self.console.print(f"[{COLORS['warning']}]Usage: /continue on|off[/{COLORS['warning']}]")
        else:
            status = "ON" if self.state.continue_conversation else "OFF"
            self.console.print(f"[cyan]Continue conversation:[/cyan] {status}")
        
        return CommandResult.success()


class ThinkingHandler(CommandHandler):
    """Handles /thinking command - toggle thinking display/budget."""
    
    commands = ["/thinking"]
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        if arg:
            value = arg.strip().lower()
            if value in {"on", "1", "true"}:
                self.state.show_thinking = True
                if self.state.thinking_budget == 0:
                    self.state.thinking_budget = 4096  # default budget
                self.console.print(f"[{COLORS['success']}]✓ Thinking display: ON (Budget: {self.state.thinking_budget})[/{COLORS['success']}]")
            elif value in {"off", "0", "false"}:
                self.state.show_thinking = False
                self.state.thinking_budget = 0
                self.console.print(f"[{COLORS['success']}]✓ Thinking display: OFF[/{COLORS['success']}]")
            else:
                try:
                    budget_val = int(value)
                    if budget_val > 0:
                        self.state.show_thinking = True
                        self.state.thinking_budget = budget_val
                        self.console.print(f"[{COLORS['success']}]✓ Thinking budget set to: {self.state.thinking_budget}[/{COLORS['success']}]")
                    else:
                        self.state.show_thinking = False
                        self.state.thinking_budget = 0
                        self.console.print(f"[{COLORS['success']}]✓ Thinking display: OFF[/{COLORS['success']}]")
                except ValueError:
                    self.console.print(f"[{COLORS['warning']}]Usage: /thinking on|off|[tokens][/{COLORS['warning']}]")
        else:
            status = "ON" if self.state.show_thinking else "OFF"
            self.console.print(f"[cyan]Thinking display:[/cyan] {status}")
            self.console.print(f"[cyan]Thinking budget:[/cyan] {self.state.thinking_budget if self.state.thinking_budget > 0 else 'Disabled'}")
        
        return CommandResult.success()


# Export all handlers
MODEL_HANDLERS = [
    ModelHandler,
    ToolsHandler,
    MaxTurnsHandler,
    ContinueHandler,
    ThinkingHandler,
]

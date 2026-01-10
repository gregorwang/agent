"""
Command Handler Base Classes and AppState

This module provides the foundation for the command handler architecture:
- AppState: Centralized state container for all TUI state
- CommandHandler: Base class for command handlers
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Callable, Awaitable
from rich.console import Console

# Forward imports to avoid circular dependencies
# Actual types will be set at runtime


@dataclass
class AppState:
    """
    Centralized state container for all TUI application state.
    
    This replaces the scattered local variables in main() with a single
    organized state object that can be passed to command handlers.
    """
    # Model configuration
    model: str = "claude-sonnet-4-5"
    max_turns: int = 8
    chatlog_max_turns: int = 16
    allowed_tools: list = field(default_factory=list)
    continue_conversation: bool = True
    
    # Thinking mode
    show_thinking: bool = False
    thinking_budget: int = 0
    
    # ReAct mode
    react_mode: bool = False
    
    # Connection state
    client: Any = None  # ClaudeSDKClient
    reconnect: bool = True
    
    # Session state
    resume_session_id: Optional[str] = None
    
    # Managers (set during initialization)
    session_manager: Any = None
    session_transcript: Any = None  # SessionTranscript for conversation history
    context_manager: Any = None
    permission_manager: Any = None
    skill_manager: Any = None
    memory_storage: Any = None
    
    # Console for output
    console: Console = field(default_factory=Console)
    
    def needs_reconnect(self) -> None:
        """Mark that the client needs to reconnect."""
        self.reconnect = True
    
    def mark_connected(self) -> None:
        """Mark that the client is connected."""
        self.reconnect = False


class CommandResult:
    """Result of a command execution."""
    
    def __init__(
        self,
        handled: bool = True,
        should_exit: bool = False,
        error: Optional[str] = None
    ):
        self.handled = handled
        self.should_exit = should_exit
        self.error = error
    
    @classmethod
    def not_handled(cls) -> "CommandResult":
        """Command was not handled by this handler."""
        return cls(handled=False)
    
    @classmethod
    def success(cls) -> "CommandResult":
        """Command executed successfully."""
        return cls(handled=True)
    
    @classmethod
    def exit(cls) -> "CommandResult":
        """User requested to exit."""
        return cls(handled=True, should_exit=True)
    
    @classmethod
    def fail(cls, error: str) -> "CommandResult":
        """Command failed with error."""
        return cls(handled=True, error=error)


class CommandHandler:
    """
    Base class for command handlers.
    
    Subclasses should implement:
    - commands: List of command names this handler responds to
    - handle(): The actual command logic
    """
    
    # List of commands this handler responds to (e.g., ["/session", "/reset"])
    commands: list[str] = []
    
    def __init__(self, state: AppState):
        self.state = state
        self.console = state.console
    
    def can_handle(self, command: str) -> bool:
        """Check if this handler can handle the given command."""
        return command.lower() in self.commands
    
    async def handle(self, command: str, arg: str) -> CommandResult:
        """
        Handle the command.
        
        Args:
            command: The command name (e.g., "/session")
            arg: Any arguments after the command
            
        Returns:
            CommandResult indicating success/failure
        """
        raise NotImplementedError("Subclasses must implement handle()")

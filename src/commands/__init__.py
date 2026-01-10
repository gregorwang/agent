"""
Command Handler Module

Provides a centralized command dispatcher that routes commands to appropriate handlers.
"""

from typing import List, Type
from rich.console import Console

from .base import AppState, CommandHandler, CommandResult
from .session import SESSION_HANDLERS
from .model import MODEL_HANDLERS
from .utility import UTILITY_HANDLERS


class CommandDispatcher:
    """
    Centralized command dispatcher.
    
    Routes slash commands to the appropriate handler based on command name.
    """
    
    def __init__(self, state: AppState):
        self.state = state
        self.handlers: List[CommandHandler] = []
        
        # Register all handlers
        self._register_handlers()
    
    def _register_handlers(self) -> None:
        """Register all command handlers."""
        all_handler_classes: List[Type[CommandHandler]] = [
            *SESSION_HANDLERS,
            *MODEL_HANDLERS,
            *UTILITY_HANDLERS,
        ]
        
        for handler_class in all_handler_classes:
            self.handlers.append(handler_class(self.state))
    
    async def handle(self, text: str) -> CommandResult:
        """
        Handle a command.
        
        Args:
            text: The full command text (e.g., "/model claude-sonnet-4-5")
            
        Returns:
            CommandResult indicating what happened
        """
        # Parse command and arguments
        parts = text.strip().split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        
        # Find a handler for this command
        for handler in self.handlers:
            if handler.can_handle(command):
                return await handler.handle(command, arg)
        
        # No handler found
        return CommandResult.not_handled()
    
    def get_registered_commands(self) -> List[str]:
        """Get a list of all registered command names."""
        commands = []
        for handler in self.handlers:
            commands.extend(handler.commands)
        return commands


# Convenience function to create a dispatcher with default state
def create_dispatcher(state: AppState) -> CommandDispatcher:
    """Create a command dispatcher with the given state."""
    return CommandDispatcher(state)


__all__ = [
    "AppState",
    "CommandHandler",
    "CommandResult",
    "CommandDispatcher",
    "create_dispatcher",
]

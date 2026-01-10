"""
BENEDICTJUN - Claude Agent SDK based TUI Agent

This package provides:
- Session management (persistence.py)
- Context management (manager.py) 
- Agent definitions (definitions.py)
- ReAct controller (react.py)
- UI components (ui/) - Claude Code style TUI components
- Permission management (permissions.py)
- Chatlog retrieval (chatlog/) - Intelligent chatlog search with keyword expansion
"""

__version__ = "0.5.0"

# Re-export key components for easier imports
from .session.persistence import SessionManager, SessionInfo
from .context.manager import ContextManager, Message
from .agents.definitions import AGENT_DEFINITIONS, get_agent_definitions, create_custom_agent
from .agents.react import ReActController, run_react, ReActTrace, ReActStep
from .permissions import PermissionManager

# Chatlog retrieval
from .chatlog import (
    ChatlogLoader,
    ChatlogSearcher,
    ChatlogCleaner,
    create_chatlog_mcp_server,
    get_chatlog_tools_info,
    query_chatlog_sync,
    get_chatlog_stats_sync,
)

# UI components
from .ui import (
    ToolApprovalPrompt,
    SelectionMenu,
    DiffPreview,
    ThinkingPanel,
    COLORS as UI_COLORS,
    STYLES as UI_STYLES,
)

__all__ = [
    # Session management
    "SessionManager",
    "SessionInfo",
    # Context management
    "ContextManager",
    "Message",
    # Agent definitions
    "AGENT_DEFINITIONS",
    "get_agent_definitions",
    "create_custom_agent",
    # ReAct
    "ReActController",
    "run_react",
    "ReActTrace",
    "ReActStep",
    # Permissions
    "PermissionManager",
    # Chatlog retrieval
    "ChatlogLoader",
    "ChatlogSearcher",
    "ChatlogCleaner",
    "create_chatlog_mcp_server",
    "get_chatlog_tools_info",
    "query_chatlog_sync",
    "get_chatlog_stats_sync",
    # UI
    "ToolApprovalPrompt",
    "SelectionMenu",
    "DiffPreview",
    "ThinkingPanel",
    "UI_COLORS",
    "UI_STYLES",
]

"""
Chatlog MCP Module for BENEDICTJUN Agent

Provides intelligent chatlog retrieval with:
- Multi-keyword semantic expansion
- Context-aware window extraction
- Small model cleaning for large results
"""

from .loader import ChatlogLoader, ChatMessage
from .searcher import ChatlogSearcher, SearchResult
from .cleaner import ChatlogCleaner
from .mcp_server import (
    create_chatlog_mcp_server,
    get_chatlog_tools_info,
    query_chatlog_sync,
    get_chatlog_stats_sync,
)

__all__ = [
    "ChatlogLoader",
    "ChatMessage", 
    "ChatlogSearcher",
    "SearchResult",
    "ChatlogCleaner",
    "create_chatlog_mcp_server",
    "get_chatlog_tools_info",
    "query_chatlog_sync",
    "get_chatlog_stats_sync",
]


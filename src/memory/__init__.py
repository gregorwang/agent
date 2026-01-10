"""
Memory Module for BENEDICTJUN Agent

Provides a ChatGPT-style memory system with:
- Memory MCP Server: Tools for Agent to recall/save memories
- Memory Extractor: Async extraction using GPT-5-nano (Poe)
- Memory Storage: Persistent JSON storage
"""

from .storage import (
    MemoryStorage,
    MemoryCategory,
    Memory,
    UserProfile,
    MemoryConflict,
    get_memory_storage
)

from .mcp_server import (
    create_memory_mcp_server,
    get_memory_tools_info
)

from .extractor import (
    MemoryExtractor,
    ExtractionResult,
    get_memory_extractor
)

from .poe_client import (
    PoeClient,
    PoeConfig,
    get_poe_client
)


__all__ = [
    # Storage
    "MemoryStorage",
    "MemoryCategory",
    "Memory",
    "UserProfile",
    "MemoryConflict",
    "get_memory_storage",
    
    # MCP Server
    "create_memory_mcp_server",
    "get_memory_tools_info",
    
    # Extractor
    "MemoryExtractor",
    "ExtractionResult",
    "get_memory_extractor",
    
    # Poe Client
    "PoeClient",
    "PoeConfig",
    "get_poe_client",
]

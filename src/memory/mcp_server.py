"""
Memory MCP Server for BENEDICTJUN Agent

Provides MCP tools for memory management that the Agent can call:
- recall_memory: Search for relevant memories
- remember: Save a new memory
- get_user_profile: Get core user profile
- list_memories: List all memories
- forget: Delete a memory
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from claude_agent_sdk import tool, create_sdk_mcp_server

from .storage import (
    MemoryStorage,
    MemoryCategory,
    Memory,
    get_memory_storage
)


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Tool Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Global storage reference (set during server creation)
_memory_storage: Optional[MemoryStorage] = None


def _get_storage() -> MemoryStorage:
    """Get the memory storage instance."""
    global _memory_storage
    if _memory_storage is None:
        _memory_storage = get_memory_storage()
    return _memory_storage


@tool(
    "recall_memory",
    "根据话题或关键词检索相关的用户记忆。用于获取与当前对话相关的用户偏好、事实、观点等信息。",
    {
        "topic": str,      # 搜索话题或关键词
        "limit": int       # 返回结果数量限制（默认5）
    }
)
async def recall_memory(args: dict) -> dict:
    """
    Search for memories relevant to a topic.
    
    The Agent calls this to retrieve user context before responding.
    """
    storage = _get_storage()
    
    topic = args.get("topic", "")
    limit = args.get("limit", 5)
    
    if not topic:
        return {
            "memories": [],
            "message": "请提供搜索话题"
        }
    
    # Search by keywords
    results = storage.search_by_keywords(topic, limit=limit)
    
    memories = []
    for memory, score in results:
        memories.append({
            "id": memory.id,
            "category": memory.category.value,
            "content": memory.content,
            "relevance": round(score, 2)
        })
    
    return {
        "memories": memories,
        "count": len(memories),
        "query": topic
    }


@tool(
    "remember",
    "保存用户明确要求记住的信息。类别包括：preference（偏好）、fact（事实）、opinion（观点）、attitude（态度）。",
    {
        "category": str,   # 类别: preference/fact/opinion/attitude
        "content": str,    # 要记住的内容
        "key": str,        # 可选：对于偏好类型，指定键名
        "value": str       # 可选：对于偏好类型，指定值
    }
)
async def remember(args: dict) -> dict:
    """
    Save a new memory when user explicitly asks to remember something.
    """
    storage = _get_storage()
    
    category_str = args.get("category", "fact")
    content = args.get("content", "")
    key = args.get("key")
    value = args.get("value")
    
    if not content:
        return {"status": "error", "message": "内容不能为空"}
    
    # Map string to enum
    try:
        category = MemoryCategory(category_str)
    except ValueError:
        category = MemoryCategory.FACT
    
    # Check for conflicts
    conflict = storage.detect_conflict(category, content, key=key)
    
    if conflict:
        return {
            "status": "conflict",
            "message": f"检测到冲突：已存在相似记忆「{conflict.existing_content}」",
            "conflict_id": conflict.id
        }
    
    # Save memory
    memory = storage.add_memory(
        category=category,
        content=content,
        key=key,
        value=value,
        source="explicit"
    )
    
    return {
        "status": "saved",
        "memory_id": memory.id,
        "message": f"已记住: {content[:50]}..."
    }


@tool(
    "get_user_profile",
    "获取用户的核心画像信息，包括姓名、语言偏好、职业等基础信息。这些信息始终可用且token消耗很少。",
    {}
)
async def get_user_profile(args: dict) -> dict:
    """
    Get the core user profile.
    
    This is lightweight and can be called frequently.
    """
    storage = _get_storage()
    profile = storage.get_profile()
    
    return {
        "profile": profile.to_dict(),
        "context_string": profile.to_context_string()
    }


@tool(
    "list_memories",
    "列出已保存的记忆。可以按类别筛选（preference/fact/opinion/attitude）。",
    {
        "category": str,  # 可选：筛选类别
        "limit": int      # 返回数量限制
    }
)
async def list_memories(args: dict) -> dict:
    """
    List stored memories, optionally filtered by category.
    """
    storage = _get_storage()
    
    category_str = args.get("category")
    limit = args.get("limit", 20)
    
    # Map string to enum
    category = None
    if category_str:
        try:
            category = MemoryCategory(category_str)
        except ValueError:
            pass
    
    memories = storage.list_memories(category=category, limit=limit)
    
    result = []
    for mem in memories:
        result.append({
            "id": mem.id,
            "category": mem.category.value,
            "content": mem.content,
            "created_at": mem.created_at[:10]  # Just date
        })
    
    stats = storage.get_stats()
    
    return {
        "memories": result,
        "count": len(result),
        "total": stats["total_memories"],
        "by_category": stats["by_category"]
    }


@tool(
    "forget",
    "删除指定ID的记忆。",
    {
        "memory_id": str  # 要删除的记忆ID
    }
)
async def forget(args: dict) -> dict:
    """
    Delete a specific memory by ID.
    """
    storage = _get_storage()
    
    memory_id = args.get("memory_id", "")
    
    if not memory_id:
        return {"status": "error", "message": "请提供记忆ID"}
    
    # Try to get the memory first to show what was deleted
    memory = storage.get_memory(memory_id)
    
    if not memory:
        return {"status": "not_found", "message": f"未找到ID为 {memory_id} 的记忆"}
    
    content_preview = memory.content[:30] + "..." if len(memory.content) > 30 else memory.content
    
    if storage.delete_memory(memory_id):
        return {
            "status": "deleted",
            "message": f"已删除记忆: {content_preview}"
        }
    
    return {"status": "error", "message": "删除失败"}


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Server Creation
# ═══════════════════════════════════════════════════════════════════════════════

def create_memory_mcp_server(storage: Optional[MemoryStorage] = None):
    """
    Create the Memory MCP server.
    
    Args:
        storage: Optional MemoryStorage instance to use
        
    Returns:
        An MCP server that can be passed to ClaudeAgentOptions.mcp_servers
    """
    global _memory_storage
    
    if storage:
        _memory_storage = storage
    else:
        _memory_storage = get_memory_storage()
    
    return create_sdk_mcp_server(
        name="memory",
        version="1.0.0",
        tools=[
            recall_memory,
            remember,
            get_user_profile,
            list_memories,
            forget
        ]
    )


def get_memory_tools_info() -> List[Dict[str, str]]:
    """Get information about available memory tools for documentation."""
    return [
        {
            "name": "mcp__memory__recall_memory",
            "description": "根据话题检索相关记忆",
            "usage": "当需要了解用户偏好或背景时调用"
        },
        {
            "name": "mcp__memory__remember",
            "description": "保存用户要求记住的信息",
            "usage": "当用户说「记住...」时调用"
        },
        {
            "name": "mcp__memory__get_user_profile",
            "description": "获取用户核心画像",
            "usage": "需要基本用户信息时调用"
        },
        {
            "name": "mcp__memory__list_memories",
            "description": "列出所有记忆",
            "usage": "用户查看记忆列表时调用"
        },
        {
            "name": "mcp__memory__forget",
            "description": "删除记忆",
            "usage": "用户要求忘记某事时调用"
        }
    ]

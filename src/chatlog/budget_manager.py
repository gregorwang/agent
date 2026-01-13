"""
Tool Budget Manager for Chatlog Queries

Prevents infinite tool call loops and token explosion by enforcing:
- Maximum tool calls per question
- Maximum loaded messages total
- Maximum tool result characters

When budget is exceeded, the system enters "best-effort mode":
returns already collected evidence with gap annotations.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, List


@dataclass
class ToolBudget:
    """Budget constraints for a single query session."""
    
    # Configurable limits
    max_tool_calls: int = 3
    max_loaded_messages: int = 40
    max_tool_result_chars: int = 12000
    
    # Current usage tracking
    tool_calls: int = 0
    loaded_messages: int = 0
    total_result_chars: int = 0
    tool_history: List[str] = field(default_factory=list)
    
    def can_call_tool(self, tool_name: str = "") -> bool:
        """Check if another tool call is allowed."""
        return self.tool_calls < self.max_tool_calls
    
    def can_load_messages(self, count: int) -> bool:
        """Check if loading more messages is allowed."""
        return self.loaded_messages + count <= self.max_loaded_messages
    
    def record_tool_call(self, tool_name: str, result_chars: int):
        """Record a tool call and its result size."""
        self.tool_calls += 1
        self.total_result_chars += result_chars
        self.tool_history.append(tool_name)
    
    def record_messages(self, count: int):
        """Record loaded messages count."""
        self.loaded_messages += count
    
    def is_over_budget(self) -> bool:
        """Check if any budget limit has been exceeded."""
        return (
            self.tool_calls >= self.max_tool_calls or
            self.loaded_messages >= self.max_loaded_messages or
            self.total_result_chars >= self.max_tool_result_chars
        )
    
    def get_remaining(self) -> Dict[str, int]:
        """Get remaining budget for each metric."""
        return {
            "tool_calls": max(0, self.max_tool_calls - self.tool_calls),
            "messages": max(0, self.max_loaded_messages - self.loaded_messages),
            "chars": max(0, self.max_tool_result_chars - self.total_result_chars),
        }
    
    def get_status(self) -> Dict:
        """Get current budget status for debugging/logging."""
        return {
            "tool_calls": f"{self.tool_calls}/{self.max_tool_calls}",
            "messages": f"{self.loaded_messages}/{self.max_loaded_messages}",
            "chars": f"{self.total_result_chars}/{self.max_tool_result_chars}",
            "over_budget": self.is_over_budget(),
            "history": self.tool_history[-5:],  # Last 5 calls
        }
    
    def get_gap_annotation(self) -> str:
        """Generate annotation describing what was not retrieved due to budget."""
        gaps = []
        remaining = self.get_remaining()
        
        if remaining["tool_calls"] == 0:
            gaps.append(f"已达工具调用上限({self.max_tool_calls}次)")
        if remaining["messages"] == 0:
            gaps.append(f"已达消息加载上限({self.max_loaded_messages}条)")
        if remaining["chars"] == 0:
            gaps.append(f"已达结果字符上限({self.max_tool_result_chars}字符)")
        
        if gaps:
            return "⚠️ 证据收集受预算限制: " + "; ".join(gaps)
        return ""


class BudgetManager:
    """Manage tool budgets per query session."""
    
    def __init__(self):
        self._budgets: Dict[str, ToolBudget] = {}
        
        # Load defaults from environment
        self._default_max_calls = int(os.getenv("CHATLOG_MAX_TOOL_CALLS", "3"))
        self._default_max_messages = int(os.getenv("CHATLOG_MAX_MESSAGES", "40"))
        self._default_max_chars = int(os.getenv("CHATLOG_MAX_RESULT_CHARS", "12000"))
    
    def get_budget(self, session_id: str) -> ToolBudget:
        """Get or create budget for a session."""
        if session_id not in self._budgets:
            self._budgets[session_id] = ToolBudget(
                max_tool_calls=self._default_max_calls,
                max_loaded_messages=self._default_max_messages,
                max_tool_result_chars=self._default_max_chars,
            )
        return self._budgets[session_id]
    
    def clear_budget(self, session_id: str):
        """Clear budget for a session (call after query completes)."""
        self._budgets.pop(session_id, None)
    
    def clear_all(self):
        """Clear all budgets."""
        self._budgets.clear()


# Global singleton instance
_budget_manager: Optional[BudgetManager] = None


def get_budget_manager() -> BudgetManager:
    """Get the global budget manager instance."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = BudgetManager()
    return _budget_manager


def check_budget(session_id: str, tool_name: str = "") -> bool:
    """
    Convenience function to check if a tool call is allowed.
    
    Usage:
        if not check_budget(session_id, "search_by_topics"):
            return _error("Budget exceeded", ...)
    """
    manager = get_budget_manager()
    budget = manager.get_budget(session_id)
    return budget.can_call_tool(tool_name)


def record_tool_usage(session_id: str, tool_name: str, result_chars: int, messages_loaded: int = 0):
    """
    Convenience function to record tool usage.
    
    Call this after every tool completes to track budget consumption.
    """
    manager = get_budget_manager()
    budget = manager.get_budget(session_id)
    budget.record_tool_call(tool_name, result_chars)
    if messages_loaded > 0:
        budget.record_messages(messages_loaded)


def get_budget_status(session_id: str) -> Dict:
    """Get budget status for a session."""
    manager = get_budget_manager()
    budget = manager.get_budget(session_id)
    return budget.get_status()

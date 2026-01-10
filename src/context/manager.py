"""
Context Manager for managing conversation context and token limits.

This module provides tools for:
- Tracking message history
- Estimating token usage
- Compacting context when approaching limits
- Generating conversation summaries
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
import json


@dataclass
class Message:
    """Represents a message in the conversation."""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    token_estimate: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.token_estimate == 0:
            # Rough estimate: ~4 chars per token for English
            self.token_estimate = len(self.content) // 4 + 1

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "token_estimate": self.token_estimate,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(timezone.utc),
            token_estimate=data.get("token_estimate", 0),
            metadata=data.get("metadata", {}),
        )


class ContextManager:
    """
    Manages conversation context with token limit awareness.

    Features:
    - Tracks all messages in the conversation
    - Estimates token usage
    - Automatically compacts when approaching limits
    - Maintains a summary of compacted messages
    """

    # Default token limits for different models
    MODEL_LIMITS = {
        "claude-opus-4-5": 200000,
        "claude-sonnet-4-5": 200000,
        "claude-haiku-3-5": 200000,
        "default": 100000,
    }

    def __init__(
        self,
        max_tokens: int | None = None,
        model: str = "default",
        compact_threshold: float = 0.8,
        keep_recent: int = 10,
    ):
        """
        Initialize the context manager.

        Args:
            max_tokens: Maximum tokens to allow (uses model default if None)
            model: Model name for determining token limits
            compact_threshold: Compact when this % of limit is reached (0.0-1.0)
            keep_recent: Number of recent messages to keep when compacting
        """
        self.max_tokens = max_tokens or self.MODEL_LIMITS.get(
            model, self.MODEL_LIMITS["default"]
        )
        self.compact_threshold = compact_threshold
        self.keep_recent = keep_recent

        self.messages: list[Message] = []
        self.summary: str = ""
        self.summary_token_estimate: int = 0
        self.total_messages_processed: int = 0
        self.compaction_count: int = 0

    @property
    def current_tokens(self) -> int:
        """Estimate current token usage."""
        message_tokens = sum(m.token_estimate for m in self.messages)
        return message_tokens + self.summary_token_estimate

    @property
    def token_usage_ratio(self) -> float:
        """Get the ratio of tokens used to max tokens."""
        return self.current_tokens / self.max_tokens

    @property
    def should_compact(self) -> bool:
        """Check if compaction is needed."""
        return self.token_usage_ratio >= self.compact_threshold

    def add_message(
        self,
        role: Literal["user", "assistant", "system"],
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        """
        Add a message to the context.

        Args:
            role: The role of the message sender
            content: The message content
            metadata: Optional metadata to attach

        Returns:
            The created Message object
        """
        message = Message(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self.messages.append(message)
        self.total_messages_processed += 1

        # Check if we need to compact
        if self.should_compact:
            self._compact()

        return message

    def add_user_message(self, content: str, **metadata) -> Message:
        """Convenience method to add a user message."""
        return self.add_message("user", content, metadata)

    def add_assistant_message(self, content: str, **metadata) -> Message:
        """Convenience method to add an assistant message."""
        return self.add_message("assistant", content, metadata)

    def add_system_message(self, content: str, **metadata) -> Message:
        """Convenience method to add a system message."""
        return self.add_message("system", content, metadata)

    def _compact(self) -> None:
        """
        Compact the context by summarizing old messages.

        Keeps the most recent messages and creates a summary of older ones.
        """
        if len(self.messages) <= self.keep_recent:
            return

        # Split messages
        old_messages = self.messages[:-self.keep_recent]
        self.messages = self.messages[-self.keep_recent:]

        # Generate summary of old messages
        old_summary = self._generate_summary(old_messages)

        # Combine with existing summary
        if self.summary:
            self.summary = f"{self.summary}\n\n---\n\n{old_summary}"
        else:
            self.summary = old_summary

        self.summary_token_estimate = len(self.summary) // 4 + 1
        self.compaction_count += 1

    def _generate_summary(self, messages: list[Message]) -> str:
        """
        Generate a summary of messages.

        Note: This is a simple extraction. In production, you'd want to
        use Claude to generate a proper summary.
        """
        summary_parts = [
            f"[Conversation summary - {len(messages)} messages compacted]"
        ]

        # Extract key points from each message
        for msg in messages:
            # Truncate long messages
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            summary_parts.append(f"- {msg.role}: {content}")

        return "\n".join(summary_parts)

    async def generate_ai_summary(
        self,
        messages: list[Message],
        client,  # ClaudeSDKClient
    ) -> str:
        """
        Generate an AI-powered summary of messages.

        Args:
            messages: Messages to summarize
            client: Connected ClaudeSDKClient

        Returns:
            AI-generated summary
        """
        # Build the content to summarize
        content = "\n\n".join(
            f"[{m.role.upper()}]: {m.content}"
            for m in messages
        )

        prompt = f"""Summarize the following conversation excerpt concisely.
Focus on:
1. Key decisions made
2. Important information shared
3. Tasks discussed or completed
4. Any unresolved issues

Conversation:
{content}

Provide a concise summary in bullet points."""

        summary_parts = []
        await client.query(prompt, session_id="summarizer")
        async for msg in client.receive_response():
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        summary_parts.append(block.text)

        return "\n".join(summary_parts)

    def get_context_string(self) -> str:
        """
        Get the full context as a string.

        Returns:
            Formatted context including summary and recent messages
        """
        parts = []

        if self.summary:
            parts.append(f"[Previous conversation summary]\n{self.summary}\n")

        parts.append("[Recent messages]")
        for msg in self.messages:
            parts.append(f"{msg.role.upper()}: {msg.content}")

        return "\n\n".join(parts)

    def get_messages_for_api(self) -> list[dict]:
        """
        Get messages formatted for API calls.

        Returns:
            List of message dictionaries
        """
        messages = []

        # Add summary as system message if exists
        if self.summary:
            messages.append({
                "role": "system",
                "content": f"Previous conversation summary:\n{self.summary}"
            })

        # Add recent messages
        for msg in self.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })

        return messages

    def clear(self) -> None:
        """Clear all context including summary."""
        self.messages.clear()
        self.summary = ""
        self.summary_token_estimate = 0

    def clear_keep_summary(self) -> None:
        """Clear messages but keep the summary."""
        # First compact all current messages into summary
        if self.messages:
            self._compact()
            # Then compact the remaining messages too
            old_messages = self.messages
            self.messages = []
            new_summary = self._generate_summary(old_messages)
            self.summary = f"{self.summary}\n\n---\n\n{new_summary}"
            self.summary_token_estimate = len(self.summary) // 4 + 1

    def get_stats(self) -> dict:
        """Get statistics about the context."""
        return {
            "message_count": len(self.messages),
            "total_processed": self.total_messages_processed,
            "current_tokens": self.current_tokens,
            "max_tokens": self.max_tokens,
            "usage_ratio": self.token_usage_ratio,
            "has_summary": bool(self.summary),
            "compaction_count": self.compaction_count,
        }

    def to_dict(self) -> dict:
        """Serialize the context manager state."""
        return {
            "messages": [m.to_dict() for m in self.messages],
            "summary": self.summary,
            "summary_token_estimate": self.summary_token_estimate,
            "total_messages_processed": self.total_messages_processed,
            "compaction_count": self.compaction_count,
            "max_tokens": self.max_tokens,
            "compact_threshold": self.compact_threshold,
            "keep_recent": self.keep_recent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextManager":
        """Deserialize a context manager from dict."""
        cm = cls(
            max_tokens=data.get("max_tokens"),
            compact_threshold=data.get("compact_threshold", 0.8),
            keep_recent=data.get("keep_recent", 10),
        )
        cm.messages = [Message.from_dict(m) for m in data.get("messages", [])]
        cm.summary = data.get("summary", "")
        cm.summary_token_estimate = data.get("summary_token_estimate", 0)
        cm.total_messages_processed = data.get("total_messages_processed", 0)
        cm.compaction_count = data.get("compaction_count", 0)
        return cm

    def save_to_file(self, path: str) -> None:
        """Save context to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_file(cls, path: str) -> "ContextManager":
        """Load context from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

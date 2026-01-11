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
import math
import os
import re

try:
    import tiktoken
except Exception:
    tiktoken = None


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
        or 0x2F800 <= code <= 0x2FA1F
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _estimate_tokens_text(content: str) -> int:
    if not content:
        return 0
    if tiktoken is not None:
        try:
            encoder = tiktoken.get_encoding("cl100k_base")
            return len(encoder.encode(content))
        except Exception:
            pass
    cjk_count = sum(1 for ch in content if _is_cjk_char(ch))
    non_cjk_count = len(content) - cjk_count
    estimate = cjk_count * 1.8 + non_cjk_count * 0.25
    return max(1, int(math.ceil(estimate)))


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
            self.token_estimate = _estimate_tokens_text(self.content)

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
        auto_save_path: str | None = None,
    ):
        """
        Initialize the context manager.

        Args:
            max_tokens: Maximum tokens to allow (uses model default if None)    
            model: Model name for determining token limits
            compact_threshold: Compact when this % of limit is reached (0.0-1.0)
            keep_recent: Number of recent messages to keep when compacting      
            auto_save_path: Optional path to auto-save and restore context
        """
        self.max_tokens = max_tokens or self.MODEL_LIMITS.get(
            model, self.MODEL_LIMITS["default"]
        )
        self.compact_threshold = compact_threshold
        self.keep_recent = keep_recent
        self.auto_save_path = auto_save_path

        self.messages: list[Message] = []
        self.summary: str = ""
        self.summary_token_estimate: int = 0
        self.total_messages_processed: int = 0
        self.compaction_count: int = 0

        if self.auto_save_path and os.path.exists(self.auto_save_path):
            loaded = self.load_from_file(self.auto_save_path)
            self._restore_state(loaded)

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

        if self.auto_save_path:
            self.save_to_file(self.auto_save_path)

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

        self.summary_token_estimate = _estimate_tokens_text(self.summary)
        self.compaction_count += 1

    def _generate_summary(self, messages: list[Message]) -> str:
        """
        Generate a summary of messages.

        Note: This is a simple extraction. In production, you'd want to
        use Claude to generate a proper summary.
        """
        if not messages:
            return "[Conversation summary - 0 messages]"

        start_time = min(m.timestamp for m in messages).astimezone(timezone.utc)
        end_time = max(m.timestamp for m in messages).astimezone(timezone.utc)
        time_range = (
            f"{start_time.strftime('%Y-%m-%d %H:%M UTC')} to "
            f"{end_time.strftime('%Y-%m-%d %H:%M UTC')}"
        )

        decisions = []
        issues = []
        questions = []
        conclusions = []
        code_blocks = []

        decision_keywords = (
            "decide",
            "decision",
            "we will",
            "will use",
            "choose",
            "selected",
            "adopt",
        )
        issue_keywords = (
            "error",
            "issue",
            "bug",
            "problem",
            "failed",
        )
        conclusion_keywords = (
            "conclusion",
            "result",
            "therefore",
            "so ",
            "resolved",
            "fixed",
            "done",
        )

        def iter_sentences(text: str) -> list[str]:
            parts = re.split(r"[\n]+", text)
            sentences = []
            for part in parts:
                buf = []
                for ch in part:
                    buf.append(ch)
                    code = ord(ch)
                    if ch in ".!?" or code in (0x3002, 0xFF01, 0xFF1F):
                        sentence = "".join(buf).strip()
                        if sentence:
                            sentences.append(sentence)
                        buf = []
                tail = "".join(buf).strip()
                if tail:
                    sentences.append(tail)
            return sentences

        def has_question_mark(text: str) -> bool:
            for ch in text:
                if ch == "?" or ord(ch) == 0xFF1F:
                    return True
            return False

        for msg in messages:
            for block in re.findall(r"```.*?```", msg.content, flags=re.S):
                if block not in code_blocks:
                    code_blocks.append(block)

            lines = msg.content.splitlines()
            if msg.role == "user":
                for line in lines:
                    if has_question_mark(line):
                        questions.append(line.strip())
                    if any(k in line.lower() for k in issue_keywords):
                        issues.append(line.strip())

            for sentence in iter_sentences(msg.content):
                lowered = sentence.lower()
                if any(k in lowered for k in decision_keywords):
                    decisions.append(sentence)
                if msg.role == "assistant" and any(k in lowered for k in conclusion_keywords):
                    conclusions.append(sentence)
                if msg.role != "user" and any(k in lowered for k in issue_keywords):
                    issues.append(sentence)

        def clamp_items(items: list[str], limit: int = 6) -> list[str]:
            seen = []
            for item in items:
                cleaned = item.strip()
                if not cleaned:
                    continue
                if cleaned not in seen:
                    seen.append(cleaned)
                if len(seen) >= limit:
                    break
            return seen

        summary_parts = [
            f"[Conversation summary - {len(messages)} messages from {time_range}]"
        ]

        summary_parts.append("Key decisions:")
        decisions = clamp_items(decisions)
        if decisions:
            summary_parts.extend(f"- {d}" for d in decisions)
        else:
            summary_parts.append("- None noted.")

        summary_parts.append("Issues:")
        issues = clamp_items(issues)
        if issues:
            summary_parts.extend(f"- {i}" for i in issues)
        else:
            summary_parts.append("- None noted.")

        summary_parts.append("Questions:")
        questions = clamp_items(questions)
        if questions:
            summary_parts.extend(f"- {q}" for q in questions)
        else:
            summary_parts.append("- None noted.")

        summary_parts.append("Conclusions:")
        conclusions = clamp_items(conclusions)
        if conclusions:
            summary_parts.extend(f"- {c}" for c in conclusions)
        else:
            summary_parts.append("- None noted.")

        summary_parts.append("Code blocks:")
        trimmed_blocks = []
        for block in code_blocks[:3]:
            if len(block) > 500:
                trimmed_blocks.append(block[:500] + "...")
            else:
                trimmed_blocks.append(block)
        if trimmed_blocks:
            summary_parts.extend(trimmed_blocks)
        else:
            summary_parts.append("- None noted.")

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

    def get_messages_for_api(self) -> tuple[str | None, list[dict]]:
        """
        Get messages formatted for API calls.

        Returns:
            Tuple of system prompt and list of message dictionaries
        """
        system_parts = []

        if self.summary:
            system_parts.append(
                f"Previous conversation summary:\n{self.summary}"
            )

        for msg in self.messages:
            if msg.role == "system":
                system_parts.append(msg.content)

        system_prompt = "\n\n".join(system_parts) if system_parts else None

        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in self.messages
            if msg.role != "system"
        ]

        return system_prompt, messages

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
            self.summary_token_estimate = _estimate_tokens_text(self.summary)

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

    def _restore_state(self, other: "ContextManager") -> None:
        self.messages = other.messages
        self.summary = other.summary
        self.summary_token_estimate = other.summary_token_estimate
        self.total_messages_processed = other.total_messages_processed
        self.compaction_count = other.compaction_count
        self.max_tokens = other.max_tokens
        self.compact_threshold = other.compact_threshold
        self.keep_recent = other.keep_recent

    def save_to_file(self, path: str) -> None:
        """Save context to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_file(cls, path: str) -> "ContextManager":
        """Load context from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

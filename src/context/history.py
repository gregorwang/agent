"""
History management for persistent conversation storage.

This module provides tools for:
- Storing conversation history to disk
- Loading previous conversations
- Searching through history
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass
class HistoryEntry:
    """A single entry in the conversation history."""
    timestamp: datetime
    role: str
    content: str
    session_id: str | None = None
    metadata: dict | None = None

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp.isoformat(),
            "role": self.role,
            "content": self.content,
            "session_id": self.session_id,
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryEntry":
        return cls(
            timestamp=datetime.fromisoformat(data["ts"].replace("Z", "+00:00")),
            role=data["role"],
            content=data["content"],
            session_id=data.get("session_id"),
            metadata=data.get("metadata"),
        )


class HistoryManager:
    """
    Manages persistent conversation history.

    Features:
    - Append-only JSONL storage for efficiency
    - Session-based filtering
    - Search functionality
    - Automatic file rotation
    """

    def __init__(
        self,
        history_path: str | Path = "history.jsonl",
        max_file_size_mb: float = 10.0,
    ):
        """
        Initialize the history manager.

        Args:
            history_path: Path to the history file
            max_file_size_mb: Max file size before rotation
        """
        self.history_path = Path(history_path)
        self.max_file_size = int(max_file_size_mb * 1024 * 1024)

    def append(
        self,
        role: str,
        content: str,
        session_id: str | None = None,
        metadata: dict | None = None,
    ) -> HistoryEntry:
        """
        Append a new entry to the history.

        Args:
            role: The role (user, assistant, system)
            content: The message content
            session_id: Optional session identifier
            metadata: Optional metadata

        Returns:
            The created HistoryEntry
        """
        entry = HistoryEntry(
            timestamp=datetime.now(timezone.utc),
            role=role,
            content=content,
            session_id=session_id,
            metadata=metadata,
        )

        # Check if rotation is needed
        self._maybe_rotate()

        # Append to file
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

        return entry

    def append_user(self, content: str, **kwargs) -> HistoryEntry:
        """Append a user message."""
        return self.append("user", content, **kwargs)

    def append_assistant(self, content: str, **kwargs) -> HistoryEntry:
        """Append an assistant message."""
        return self.append("assistant", content, **kwargs)

    def _maybe_rotate(self) -> None:
        """Rotate the history file if it's too large."""
        if not self.history_path.exists():
            return

        if self.history_path.stat().st_size > self.max_file_size:
            # Create rotated filename
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            rotated_path = self.history_path.with_suffix(f".{timestamp}.jsonl")

            # Rename current file
            self.history_path.rename(rotated_path)

    def iter_entries(
        self,
        session_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        role: str | None = None,
    ) -> Iterator[HistoryEntry]:
        """
        Iterate over history entries with optional filtering.

        Args:
            session_id: Filter by session ID
            since: Only entries after this time
            until: Only entries before this time
            role: Filter by role

        Yields:
            HistoryEntry objects matching the filters
        """
        if not self.history_path.exists():
            return

        with self.history_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = HistoryEntry.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError):
                    continue

                # Apply filters
                if session_id and entry.session_id != session_id:
                    continue
                if since and entry.timestamp < since:
                    continue
                if until and entry.timestamp > until:
                    continue
                if role and entry.role != role:
                    continue

                yield entry

    def get_recent(
        self,
        n: int = 10,
        session_id: str | None = None,
    ) -> list[HistoryEntry]:
        """
        Get the N most recent entries.

        Args:
            n: Number of entries to return
            session_id: Optional session filter

        Returns:
            List of recent entries (most recent last)
        """
        entries = list(self.iter_entries(session_id=session_id))
        return entries[-n:] if len(entries) > n else entries

    def search(
        self,
        query: str,
        session_id: str | None = None,
        max_results: int = 20,
    ) -> list[HistoryEntry]:
        """
        Search history for entries containing the query.

        Args:
            query: Search string (case-insensitive)
            session_id: Optional session filter
            max_results: Maximum number of results

        Returns:
            List of matching entries
        """
        query_lower = query.lower()
        results = []

        for entry in self.iter_entries(session_id=session_id):
            if query_lower in entry.content.lower():
                results.append(entry)
                if len(results) >= max_results:
                    break

        return results

    def get_sessions(self) -> list[str]:
        """
        Get a list of all unique session IDs in history.

        Returns:
            List of session IDs
        """
        sessions = set()
        for entry in self.iter_entries():
            if entry.session_id:
                sessions.add(entry.session_id)
        return sorted(sessions)

    def get_session_summary(self, session_id: str) -> dict:
        """
        Get a summary of a session.

        Args:
            session_id: The session ID

        Returns:
            Dictionary with session statistics
        """
        entries = list(self.iter_entries(session_id=session_id))
        if not entries:
            return {"exists": False}

        return {
            "exists": True,
            "session_id": session_id,
            "message_count": len(entries),
            "first_message": entries[0].timestamp.isoformat(),
            "last_message": entries[-1].timestamp.isoformat(),
            "user_messages": sum(1 for e in entries if e.role == "user"),
            "assistant_messages": sum(1 for e in entries if e.role == "assistant"),
        }

    def export_session(
        self,
        session_id: str,
        output_path: str | Path,
        format: str = "jsonl",
    ) -> None:
        """
        Export a session to a file.

        Args:
            session_id: The session ID to export
            output_path: Path for the output file
            format: Export format (jsonl, json, md)
        """
        entries = list(self.iter_entries(session_id=session_id))
        output_path = Path(output_path)

        if format == "jsonl":
            with output_path.open("w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

        elif format == "json":
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(
                    [e.to_dict() for e in entries],
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

        elif format == "md":
            with output_path.open("w", encoding="utf-8") as f:
                f.write(f"# Session: {session_id}\n\n")
                for entry in entries:
                    f.write(f"## {entry.role.upper()} ({entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')})\n\n")
                    f.write(f"{entry.content}\n\n")
                    f.write("---\n\n")

    def clear(self) -> None:
        """Clear all history."""
        if self.history_path.exists():
            self.history_path.unlink()

    def clear_session(self, session_id: str) -> int:
        """
        Remove all entries for a specific session.

        Args:
            session_id: The session to clear

        Returns:
            Number of entries removed
        """
        if not self.history_path.exists():
            return 0

        # Read all entries
        entries = []
        removed = 0

        for entry in self.iter_entries():
            if entry.session_id == session_id:
                removed += 1
            else:
                entries.append(entry)

        # Rewrite file without the session
        with self.history_path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

        return removed

"""
Session persistence and management.

This module handles:
- Saving and loading session IDs
- Managing multiple sessions
- Session metadata and history
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass
class SessionInfo:
    """Information about a session."""
    session_id: str
    created_at: datetime
    last_used: datetime
    name: str | None = None
    description: str | None = None
    message_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
            "name": self.name,
            "description": self.description,
            "message_count": self.message_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionInfo":
        return cls(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used=datetime.fromisoformat(data["last_used"]),
            name=data.get("name"),
            description=data.get("description"),
            message_count=data.get("message_count", 0),
            metadata=data.get("metadata", {}),
        )


class SessionManager:
    """
    Manages session persistence and lifecycle.

    Features:
    - Save and load current session ID
    - Track multiple sessions
    - Session metadata and naming
    - Session forking
    """

    def __init__(
        self,
        session_path: str | Path = "session.json",
        sessions_dir: str | Path | None = None,
    ):
        """
        Initialize the session manager.

        Args:
            session_path: Path to current session file
            sessions_dir: Directory for session metadata (optional)
        """
        self.session_path = Path(session_path)
        self.sessions_dir = Path(sessions_dir) if sessions_dir else None

        if self.sessions_dir:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self._sessions_cache: dict[str, SessionInfo] = {}
        self._load_sessions_cache()

    def _load_sessions_cache(self) -> None:
        """Load sessions metadata into cache."""
        if not self.sessions_dir:
            return

        sessions_file = self.sessions_dir / "sessions.json"
        if sessions_file.exists():
            try:
                data = json.loads(sessions_file.read_text(encoding="utf-8"))
                self._sessions_cache = {
                    sid: SessionInfo.from_dict(info)
                    for sid, info in data.items()
                }
            except (json.JSONDecodeError, KeyError):
                self._sessions_cache = {}

    def _save_sessions_cache(self) -> None:
        """Save sessions metadata cache to disk."""
        if not self.sessions_dir:
            return

        sessions_file = self.sessions_dir / "sessions.json"
        data = {
            sid: info.to_dict()
            for sid, info in self._sessions_cache.items()
        }
        sessions_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # -------------------------------------------------------------------------
    # Current Session Management
    # -------------------------------------------------------------------------

    def get_current_session_id(self) -> str | None:
        """
        Get the current active session ID.

        Returns:
            Session ID or None if no active session
        """
        if not self.session_path.exists():
            return None

        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
            return data.get("session_id")
        except (json.JSONDecodeError, KeyError):
            return None

    def set_current_session_id(self, session_id: str) -> None:
        """
        Set the current active session ID.

        Args:
            session_id: The session ID to set as current
        """
        data = {"session_id": session_id}

        # Preserve any additional data in the file
        if self.session_path.exists():
            try:
                existing = json.loads(self.session_path.read_text(encoding="utf-8"))
                existing["session_id"] = session_id
                data = existing
            except json.JSONDecodeError:
                pass

        self.session_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Update session info if tracking
        if session_id in self._sessions_cache:
            self._sessions_cache[session_id].last_used = datetime.now(timezone.utc)
            self._save_sessions_cache()

    def clear_current_session(self) -> None:
        """Clear the current session (start fresh)."""
        if self.session_path.exists():
            self.session_path.unlink()

    # -------------------------------------------------------------------------
    # Session Lifecycle
    # -------------------------------------------------------------------------

    def create_session(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """
        Create a new session.

        Args:
            name: Optional human-readable name
            description: Optional description

        Returns:
            The new session ID
        """
        # Generate a unique session ID
        timestamp = datetime.now(timezone.utc)
        session_id = f"session-{timestamp.strftime('%Y%m%d-%H%M%S')}-{id(timestamp) % 10000:04d}"

        # Create session info
        info = SessionInfo(
            session_id=session_id,
            created_at=timestamp,
            last_used=timestamp,
            name=name,
            description=description,
        )

        # Store in cache
        self._sessions_cache[session_id] = info
        self._save_sessions_cache()

        # Set as current
        self.set_current_session_id(session_id)

        return session_id

    def fork_session(
        self,
        source_session_id: str | None = None,
        name: str | None = None,
    ) -> str:
        """
        Fork an existing session to create a new branch.

        Args:
            source_session_id: Session to fork from (current if None)
            name: Optional name for the forked session

        Returns:
            The new forked session ID
        """
        source = source_session_id or self.get_current_session_id()
        if not source:
            return self.create_session(name=name)

        # Create new session with fork metadata
        new_id = self.create_session(
            name=name or f"Fork of {source[:20]}",
            description=f"Forked from session: {source}",
        )

        # Store fork relationship in metadata
        if new_id in self._sessions_cache:
            self._sessions_cache[new_id].metadata["forked_from"] = source
            self._save_sessions_cache()

        return new_id

    def get_session_info(self, session_id: str) -> SessionInfo | None:
        """
        Get information about a specific session.

        Args:
            session_id: The session ID

        Returns:
            SessionInfo or None if not found
        """
        return self._sessions_cache.get(session_id)

    def update_session(
        self,
        session_id: str,
        name: str | None = None,
        description: str | None = None,
        increment_messages: bool = False,
    ) -> None:
        """
        Update session metadata.

        Args:
            session_id: The session ID
            name: New name (if provided)
            description: New description (if provided)
            increment_messages: Whether to increment message count
        """
        if session_id not in self._sessions_cache:
            # Create entry if it doesn't exist
            self._sessions_cache[session_id] = SessionInfo(
                session_id=session_id,
                created_at=datetime.now(timezone.utc),
                last_used=datetime.now(timezone.utc),
            )

        info = self._sessions_cache[session_id]
        info.last_used = datetime.now(timezone.utc)

        if name is not None:
            info.name = name
        if description is not None:
            info.description = description
        if increment_messages:
            info.message_count += 1

        self._save_sessions_cache()

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: The session ID to delete

        Returns:
            True if deleted, False if not found
        """
        if session_id not in self._sessions_cache:
            return False

        del self._sessions_cache[session_id]
        self._save_sessions_cache()

        # Clear current session if it was the deleted one
        if self.get_current_session_id() == session_id:
            self.clear_current_session()

        return True

    # -------------------------------------------------------------------------
    # Session Listing and Search
    # -------------------------------------------------------------------------

    def list_sessions(
        self,
        limit: int = 20,
        sort_by: str = "last_used",
    ) -> list[SessionInfo]:
        """
        List all tracked sessions.

        Args:
            limit: Maximum number to return
            sort_by: Field to sort by (last_used, created_at, name)

        Returns:
            List of SessionInfo objects
        """
        sessions = list(self._sessions_cache.values())

        if sort_by == "last_used":
            sessions.sort(key=lambda s: s.last_used, reverse=True)
        elif sort_by == "created_at":
            sessions.sort(key=lambda s: s.created_at, reverse=True)
        elif sort_by == "name":
            sessions.sort(key=lambda s: s.name or s.session_id)

        return sessions[:limit]

    def get_recent_sessions(self, n: int = 5) -> list[SessionInfo]:
        """
        Get the N most recently used sessions.

        Args:
            n: Number of sessions to return

        Returns:
            List of recent sessions
        """
        return self.list_sessions(limit=n, sort_by="last_used")

    def search_sessions(self, query: str) -> list[SessionInfo]:
        """
        Search sessions by name or description.

        Args:
            query: Search string (case-insensitive)

        Returns:
            List of matching sessions
        """
        query_lower = query.lower()
        results = []

        for info in self._sessions_cache.values():
            if (info.name and query_lower in info.name.lower()) or \
               (info.description and query_lower in info.description.lower()) or \
               query_lower in info.session_id.lower():
                results.append(info)

        return results

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_or_create_session(self) -> str:
        """
        Get the current session or create a new one.

        Returns:
            Session ID (existing or new)
        """
        current = self.get_current_session_id()
        if current:
            return current
        return self.create_session()

    def ensure_session(self, session_id: str | None = None) -> str:
        """
        Ensure a valid session exists.

        Args:
            session_id: Preferred session ID (uses current if None)

        Returns:
            Valid session ID
        """
        if session_id:
            self.set_current_session_id(session_id)
            return session_id
        return self.get_or_create_session()

    def export_sessions(self, output_path: str | Path) -> None:
        """
        Export all session metadata to a file.

        Args:
            output_path: Path for the export file
        """
        output_path = Path(output_path)
        data = {
            sid: info.to_dict()
            for sid, info in self._sessions_cache.items()
        }
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def import_sessions(self, input_path: str | Path) -> int:
        """
        Import session metadata from a file.

        Args:
            input_path: Path to the import file

        Returns:
            Number of sessions imported
        """
        input_path = Path(input_path)
        data = json.loads(input_path.read_text(encoding="utf-8"))

        imported = 0
        for sid, info_data in data.items():
            if sid not in self._sessions_cache:
                self._sessions_cache[sid] = SessionInfo.from_dict(info_data)
                imported += 1

        self._save_sessions_cache()
        return imported

"""
Session Transcript Storage.

Stores conversation history for each session in separate JSONL files,
following Claude Code's standard format.

Each session has a file: <session_id>.jsonl
Each line is a JSON object: {"role": "...", "content": "...", "timestamp": "...", ...}
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass
class TranscriptMessage:
    """A single message in a session transcript."""
    role: str  # "user", "assistant", "tool_use", "tool_result", "system"
    content: str
    timestamp: str
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        result = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptMessage":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
        )


class SessionTranscript:
    """
    Manages session transcript files in JSONL format.
    
    Each session has a separate file containing the full conversation history.
    This matches Claude Code's storage format.
    """
    
    def __init__(self, transcripts_dir: str | Path):
        """
        Initialize the transcript manager.
        
        Args:
            transcripts_dir: Directory to store transcript files
        """
        self.transcripts_dir = Path(transcripts_dir)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
    
    def get_transcript_path(self, session_id: str) -> Path:
        """Get the path to a session's transcript file."""
        # Sanitize session_id for filesystem
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        return self.transcripts_dir / f"{safe_id}.jsonl"
    
    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """
        Append a message to a session's transcript.
        
        Args:
            session_id: The session ID
            role: Message role (user, assistant, tool_use, tool_result, system)
            content: Message content
            metadata: Optional metadata (tool name, etc.)
        """
        transcript_path = self.get_transcript_path(session_id)
        
        message = TranscriptMessage(
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        
        with transcript_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
    
    def load_messages(self, session_id: str) -> list[TranscriptMessage]:
        """
        Load all messages from a session's transcript.
        
        Args:
            session_id: The session ID
            
        Returns:
            List of TranscriptMessage objects
        """
        transcript_path = self.get_transcript_path(session_id)
        
        if not transcript_path.exists():
            return []
        
        messages = []
        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        messages.append(TranscriptMessage.from_dict(data))
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines
        
        return messages
    
    def iter_messages(self, session_id: str) -> Iterator[TranscriptMessage]:
        """
        Iterate over messages in a session's transcript (memory-efficient).
        
        Args:
            session_id: The session ID
            
        Yields:
            TranscriptMessage objects
        """
        transcript_path = self.get_transcript_path(session_id)
        
        if not transcript_path.exists():
            return
        
        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        yield TranscriptMessage.from_dict(data)
                    except json.JSONDecodeError:
                        continue
    
    def get_message_count(self, session_id: str) -> int:
        """Get the number of messages in a session's transcript."""
        transcript_path = self.get_transcript_path(session_id)
        
        if not transcript_path.exists():
            return 0
        
        count = 0
        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    
    def transcript_exists(self, session_id: str) -> bool:
        """Check if a transcript file exists for a session."""
        return self.get_transcript_path(session_id).exists()
    
    def delete_transcript(self, session_id: str) -> bool:
        """
        Delete a session's transcript file.
        
        Returns:
            True if deleted, False if not found
        """
        transcript_path = self.get_transcript_path(session_id)
        
        if transcript_path.exists():
            transcript_path.unlink()
            return True
        return False
    
    def list_transcripts(self) -> list[str]:
        """List all session IDs that have transcripts."""
        session_ids = []
        for path in self.transcripts_dir.glob("*.jsonl"):
            session_ids.append(path.stem)
        return session_ids
    
    def get_formatted_history(
        self,
        session_id: str,
        max_messages: int | None = None,
    ) -> str:
        """
        Get formatted conversation history for display or injection.
        
        Args:
            session_id: The session ID
            max_messages: Maximum messages to include (None = all)
            
        Returns:
            Formatted string of conversation history
        """
        messages = self.load_messages(session_id)
        
        if max_messages:
            messages = messages[-max_messages:]
        
        lines = []
        for msg in messages:
            if msg.role == "user":
                lines.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                lines.append(f"Assistant: {msg.content}")
            elif msg.role == "tool_use":
                tool_name = msg.metadata.get("tool_name", "unknown")
                lines.append(f"[Tool Call: {tool_name}]")
            elif msg.role == "tool_result":
                lines.append(f"[Tool Result]: {msg.content[:200]}...")
        
        return "\n\n".join(lines)

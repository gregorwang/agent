"""
Chatlog Loader - JSONL file loading and indexing

Loads cleaned_chatlog.jsonl and provides efficient access to messages.
"""

import os
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ChatMessage:
    """Represents a single chat message."""
    line_number: int  # 1-indexed line number in file
    content: str  # Full content including sender
    timestamp: str  # Original timestamp string
    sender: str = ""  # Extracted sender name
    message: str = ""  # Extracted message content
    topics: List[str] = field(default_factory=list)
    sentiment: str = "neutral"
    facts: Dict[str, Any] = field(default_factory=dict)
    information_density: str = "unknown"
    
    def __post_init__(self):
        """Extract sender and message from content."""
        if ": " in self.content:
            parts = self.content.split(": ", 1)
            self.sender = parts[0]
            self.message = parts[1] if len(parts) > 1 else ""
        else:
            self.sender = ""
            self.message = self.content
    
    def format_simple(self) -> str:
        """Format message for output (no metadata)."""
        return f"[{self.timestamp}] {self.content}"
    
    def format_with_line(self) -> str:
        """Format message with line number."""
        return f"#{self.line_number} [{self.timestamp}] {self.content}"


class ChatlogLoader:
    """
    Loads and indexes chatlog JSONL files.
    
    Features:
    - Lazy loading with caching
    - Sender-based indexing
    - Topic-based indexing
    """
    
    def __init__(self, file_path: Optional[str] = None):
        """
        Initialize loader.
        
        Args:
            file_path: Path to JSONL file. If None, uses default path.
        """
        if file_path is None:
            # Default to cleaned_chatlog.jsonl in project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            file_path = os.path.join(project_root, "cleaned_chatlog.jsonl")
        
        self.file_path = file_path
        self._messages: Optional[List[ChatMessage]] = None
        self._sender_index: Dict[str, List[int]] = {}  # sender -> [line_numbers]
        self._loaded = False
    
    @property
    def is_loaded(self) -> bool:
        """Check if file is loaded."""
        return self._loaded
    
    @property
    def message_count(self) -> int:
        """Get total message count."""
        if not self._loaded:
            self.load()
        return len(self._messages) if self._messages else 0
    
    @property
    def senders(self) -> List[str]:
        """Get list of unique senders."""
        if not self._loaded:
            self.load()
        return list(self._sender_index.keys())
    
    def load(self) -> bool:
        """
        Load the JSONL file.
        
        Returns:
            True if successful, False otherwise.
        """
        if not os.path.exists(self.file_path):
            print(f"Chatlog file not found: {self.file_path}")
            return False
        
        self._messages = []
        self._sender_index = {}
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        
                        # Extract metadata
                        metadata = data.get("metadata", {})
                        raw_topics = metadata.get("topics", [])
                        topics = [
                            t.strip()
                            for t in raw_topics
                            if isinstance(t, str) and t.strip()
                        ]

                        msg = ChatMessage(
                            line_number=line_num,
                            content=data.get("content", ""),
                            timestamp=data.get("timestamp", ""),
                            topics=topics,
                            sentiment=metadata.get("sentiment", "neutral"),
                            facts=metadata.get("facts", {}),
                            information_density=metadata.get(
                                "information_density", "unknown"
                            ),
                        )
                        
                        self._messages.append(msg)
                        
                        # Index by sender
                        if msg.sender:
                            if msg.sender not in self._sender_index:
                                self._sender_index[msg.sender] = []
                            self._sender_index[msg.sender].append(line_num)
                    
                    except json.JSONDecodeError:
                        continue
            
            self._loaded = True
            print(f"Loaded {len(self._messages)} messages from chatlog")
            return True
            
        except Exception as e:
            print(f"Error loading chatlog: {e}")
            return False
    
    def get_message(self, line_number: int) -> Optional[ChatMessage]:
        """Get message by line number (1-indexed)."""
        if not self._loaded:
            self.load()
        
        if not self._messages:
            return None
        
        # Convert to 0-indexed
        idx = line_number - 1
        if 0 <= idx < len(self._messages):
            return self._messages[idx]
        return None
    
    def get_messages_by_sender(self, sender: str) -> List[ChatMessage]:
        """Get all messages from a specific sender."""
        if not self._loaded:
            self.load()
        
        result = []
        for name, line_numbers in self._sender_index.items():
            if sender.lower() in name.lower():
                for ln in line_numbers:
                    msg = self.get_message(ln)
                    if msg:
                        result.append(msg)
        
        return sorted(result, key=lambda m: m.line_number)
    
    def get_all_messages(self) -> List[ChatMessage]:
        """Get all messages."""
        if not self._loaded:
            self.load()
        return self._messages or []
    
    def get_context_window(
        self,
        center_line: int,
        before: int = 5,
        after: int = 5
    ) -> List[ChatMessage]:
        """
        Get messages around a center line.
        
        Args:
            center_line: Center line number (1-indexed)
            before: Number of messages before
            after: Number of messages after
            
        Returns:
            List of messages in the window
        """
        if not self._loaded:
            self.load()
        
        if not self._messages:
            return []
        
        # Convert to 0-indexed
        center_idx = center_line - 1
        start_idx = max(0, center_idx - before)
        end_idx = min(len(self._messages), center_idx + after + 1)
        
        return self._messages[start_idx:end_idx]
    
    def search_content(self, keyword: str, case_sensitive: bool = False) -> List[int]:
        """
        Search for keyword in message content.
        
        Args:
            keyword: Keyword to search
            case_sensitive: Whether to match case
            
        Returns:
            List of matching line numbers
        """
        if not self._loaded:
            self.load()
        
        if not self._messages:
            return []
        
        results = []
        search_term = keyword if case_sensitive else keyword.lower()
        
        for msg in self._messages:
            content = msg.content if case_sensitive else msg.content.lower()
            if search_term in content:
                results.append(msg.line_number)
        
        return results
    
    def search_topics(self, keywords: List[str]) -> List[int]:
        """
        Search by topic metadata.
        
        Args:
            keywords: Topics to search for (fuzzy match)
            
        Returns:
            List of matching line numbers
        """
        if not self._loaded:
            self.load()
        
        if not self._messages:
            return []
        
        results = []
        keywords_lower = [k.lower() for k in keywords]
        
        for msg in self._messages:
            for topic in msg.topics:
                topic_lower = topic.lower()
                for keyword in keywords_lower:
                    if keyword in topic_lower or topic_lower in keyword:
                        results.append(msg.line_number)
                        break
                else:
                    continue
                break
        
        return results
    
    def search_facts(self, fact_keys: List[str]) -> List[int]:
        """
        Search for messages containing specific facts.
        
        Args:
            fact_keys: Fact keys to search for (e.g., "收入", "工资")
            
        Returns:
            List of matching line numbers
        """
        if not self._loaded:
            self.load()
        
        if not self._messages:
            return []
        
        results = []
        keys_lower = [k.lower() for k in fact_keys]
        
        for msg in self._messages:
            if msg.facts:  # Has non-empty facts dict
                for fact_key in msg.facts.keys():
                    for search_key in keys_lower:
                        if search_key in fact_key.lower():
                            results.append(msg.line_number)
                            break
                    else:
                        continue
                    break
        
        return results

    def search_sentiment(self, sentiment: str) -> List[int]:
        """
        Search for messages with a specific sentiment.

        Args:
            sentiment: Sentiment label to match

        Returns:
            List of matching line numbers
        """
        if not self._loaded:
            self.load()

        if not self._messages:
            return []

        target = sentiment.lower()
        return [
            msg.line_number
            for msg in self._messages
            if (msg.sentiment or "").lower() == target
        ]

    def search_information_density(self, density: str) -> List[int]:
        """
        Search for messages with a specific information density.

        Args:
            density: Density label to match

        Returns:
            List of matching line numbers
        """
        if not self._loaded:
            self.load()

        if not self._messages:
            return []

        target = density.lower()
        return [
            msg.line_number
            for msg in self._messages
            if (msg.information_density or "").lower() == target
        ]
    
    def get_high_density_messages(self) -> List[int]:
        """
        Get messages with high information density.
        
        Returns:
            List of line numbers for high/medium density messages
        """
        if not self._loaded:
            self.load()
        
        if not self._messages:
            return []
        
        results = []
        for msg in self._messages:
            # Check if metadata has information_density field
            # Need to get original data for this
            pass
        
        # For now, return messages with non-empty facts
        for msg in self._messages:
            if msg.facts:
                results.append(msg.line_number)
        
        return results
    
    def comprehensive_search(
        self, 
        keywords: List[str],
        include_content: bool = True,
        include_topics: bool = True,
        include_facts: bool = True
    ) -> List[int]:
        """
        Comprehensive search across content, topics, and facts.
        
        Args:
            keywords: Keywords to search
            include_content: Search in message content
            include_topics: Search in topic metadata
            include_facts: Search in facts metadata
            
        Returns:
            Deduplicated list of matching line numbers
        """
        all_results: set = set()
        
        for keyword in keywords:
            if include_content:
                all_results.update(self.search_content(keyword))
            
        if include_topics:
            all_results.update(self.search_topics(keywords))
        
        if include_facts:
            all_results.update(self.search_facts(keywords))
        
        return sorted(all_results)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the loaded chatlog."""
        if not self._loaded:
            self.load()

        return {
            "file_path": self.file_path,
            "total_messages": len(self._messages) if self._messages else 0,
            "unique_senders": list(self._sender_index.keys()),
            "sender_message_counts": {
                k: len(v) for k, v in self._sender_index.items()
            }
        }

    def get_unique_topics(self) -> List[str]:
        """Get unique topic labels from metadata."""
        if not self._loaded:
            self.load()

        topics = set()
        for msg in self._messages or []:
            for topic in msg.topics:
                if topic:
                    topics.add(topic)
        return sorted(topics)


# Global loader instance
_chatlog_loader: Optional[ChatlogLoader] = None


def get_chatlog_loader(file_path: Optional[str] = None) -> ChatlogLoader:
    """Get or create the global ChatlogLoader instance."""
    global _chatlog_loader
    if _chatlog_loader is None:
        _chatlog_loader = ChatlogLoader(file_path)
    return _chatlog_loader

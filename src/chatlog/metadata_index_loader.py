"""
Metadata Index Loader - Fast O(1) topic-based search

Uses pre-built inverted index for efficient topic matching.
"""

import os
import json
from typing import Dict, List, Set, Any, Optional


class MetadataIndexLoader:
    """
    Loads pre-built metadata index for fast topic-based search.
    
    Uses O(1) lookups instead of linear scans through all messages.
    """
    
    def __init__(self, index_path: str = None, chatlog_path: str = None):
        """
        Initialize index loader.
        
        Args:
            index_path: Path to pre-built index JSON
            chatlog_path: Path to chatlog JSONL (for on-demand loading)
        """
        if index_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            )))
            index_path = os.path.join(base_dir, "cleaned_chatlog_index.json")
        
        if chatlog_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            )))
            chatlog_path = os.path.join(base_dir, "cleaned_chatlog.jsonl")
        
        self.index_path = index_path
        self.chatlog_path = chatlog_path
        
        # Index data
        self._topic_index: Dict[str, List[int]] = {}
        self._sentiment_index: Dict[str, List[int]] = {}
        self._fact_keys_index: Dict[str, List[int]] = {}
        self._info_density_index: Dict[str, List[int]] = {}
        self._available_topics: List[str] = []
        self._line_count: int = 0
        self._loaded = False
    
    def load_index(self) -> bool:
        """
        Load pre-built index from JSON file.
        
        Returns:
            True if successful, False otherwise.
        """
        if self._loaded:
            return True
        
        if not os.path.exists(self.index_path):
            print(f"[INDEX] Index file not found: {self.index_path}")
            print("[INDEX] Run metadata_indexer.py to generate it")
            return False
        
        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._topic_index = data.get("topic_index", {})
            self._sentiment_index = data.get("sentiment_index", {})
            self._fact_keys_index = data.get("fact_keys_index", {})
            self._info_density_index = data.get("info_density_index", {})
            self._available_topics = data.get("available_topics", [])
            self._line_count = data.get("line_count", 0)
            self._loaded = True
            
            print(f"[INDEX] Loaded index: {len(self._available_topics)} topics, {self._line_count} messages")
            return True
            
        except Exception as e:
            print(f"[INDEX] Error loading index: {e}")
            return False
    
    @property
    def is_loaded(self) -> bool:
        return self._loaded
    
    @property
    def available_topics(self) -> List[str]:
        """Get list of all available topics."""
        if not self._loaded:
            self.load_index()
        return self._available_topics
    
    def search_by_topic_exact(self, topic: str) -> List[int]:
        """
        Exact match search for a topic.
        
        Args:
            topic: Topic to search (case-sensitive exact match)
            
        Returns:
            List of matching line numbers
        """
        if not self._loaded:
            self.load_index()
        
        return self._topic_index.get(topic, [])
    
    def search_by_topics(self, topics: List[str]) -> List[int]:
        """
        Search for multiple topics (union).
        
        Args:
            topics: List of topics to search
            
        Returns:
            Deduplicated list of matching line numbers, sorted
        """
        if not self._loaded:
            self.load_index()
        
        result_set: Set[int] = set()
        for topic in topics:
            result_set.update(self._topic_index.get(topic, []))
        
        return sorted(result_set)
    
    def search_by_topic_fuzzy(self, query: str) -> List[int]:
        """
        Fuzzy match search for topics containing query.
        
        Args:
            query: Substring to search for in topic names
            
        Returns:
            Deduplicated list of matching line numbers
        """
        if not self._loaded:
            self.load_index()
        
        query_lower = query.lower()
        result_set: Set[int] = set()
        
        for topic, line_nums in self._topic_index.items():
            if query_lower in topic.lower():
                result_set.update(line_nums)
        
        return sorted(result_set)
    
    def find_matching_topics(self, query: str, limit: int = 10) -> List[str]:
        """
        Find topics that match a query (for topic selection).
        
        Args:
            query: Substring to search
            limit: Maximum number of topics to return
            
        Returns:
            List of matching topic names
        """
        if not self._loaded:
            self.load_index()
        
        query_lower = query.lower()
        matches = []
        
        for topic in self._available_topics:
            if query_lower in topic.lower():
                matches.append(topic)
                if len(matches) >= limit:
                    break
        
        return matches
    
    def search_by_sentiment(self, sentiment: str) -> List[int]:
        """Search by sentiment label."""
        if not self._loaded:
            self.load_index()
        return self._sentiment_index.get(sentiment, [])
    
    def search_by_fact_key(self, key: str) -> List[int]:
        """Search by fact key (e.g., "工资", "收入")."""
        if not self._loaded:
            self.load_index()
        return self._fact_keys_index.get(key, [])
    
    def search_by_info_density(self, density: str) -> List[int]:
        """Search by information density."""
        if not self._loaded:
            self.load_index()
        return self._info_density_index.get(density, [])
    
    def get_high_value_messages(self) -> List[int]:
        """Get messages with high information density."""
        if not self._loaded:
            self.load_index()
        
        result_set: Set[int] = set()
        result_set.update(self._info_density_index.get("high", []))
        result_set.update(self._info_density_index.get("medium", []))
        return sorted(result_set)
    
    def get_messages_by_lines(
        self, 
        line_numbers: List[int],
        context_before: int = 0,
        context_after: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Load specific messages from chatlog by line numbers.
        
        Args:
            line_numbers: Line numbers to load (1-indexed)
            context_before: Lines of context to include before
            context_after: Lines of context to include after
            
        Returns:
            List of message dicts with content, timestamp, etc.
        """
        if not line_numbers:
            return []
        
        # Expand line numbers with context
        expanded = set()
        for ln in line_numbers:
            for offset in range(-context_before, context_after + 1):
                expanded.add(max(1, ln + offset))
        
        target_lines = sorted(expanded)
        target_set = set(target_lines)
        
        results = []
        try:
            with open(self.chatlog_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, start=1):
                    if line_num in target_set:
                        line = line.strip()
                        if line:
                            try:
                                record = json.loads(line)
                                record["line_number"] = line_num
                                record["is_match"] = line_num in line_numbers
                                results.append(record)
                            except json.JSONDecodeError:
                                continue
                    
                    # Early exit if we've passed all targets
                    if line_num > max(target_lines):
                        break
        except Exception as e:
            print(f"[INDEX] Error loading messages: {e}")
        
        return results


# Global instance
_index_loader: Optional[MetadataIndexLoader] = None


def get_index_loader() -> MetadataIndexLoader:
    """Get or create global MetadataIndexLoader instance."""
    global _index_loader
    if _index_loader is None:
        _index_loader = MetadataIndexLoader()
    return _index_loader

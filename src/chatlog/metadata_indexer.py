"""
Metadata Indexer - Build inverted index from chatlog metadata

Creates metadata_index.json with:
- topic_index: topic -> [line_numbers]
- sentiment_index: sentiment -> [line_numbers]
- fact_keys_index: fact_key -> [line_numbers]
- available_topics: list of all unique topics
"""

import os
import json
from typing import Dict, List, Set, Any
from collections import defaultdict


class MetadataIndexer:
    """Builds inverted index from chatlog JSONL metadata."""
    
    def __init__(self, chatlog_path: str = None):
        """Initialize indexer with chatlog path."""
        if chatlog_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            )))
            chatlog_path = os.path.join(base_dir, "cleaned_chatlog.jsonl")
        
        self.chatlog_path = chatlog_path
        self.index_path = chatlog_path.replace(".jsonl", "_index.json")
        
        # Index structures
        self.topic_index: Dict[str, List[int]] = defaultdict(list)
        self.sentiment_index: Dict[str, List[int]] = defaultdict(list)
        self.fact_keys_index: Dict[str, List[int]] = defaultdict(list)
        self.info_density_index: Dict[str, List[int]] = defaultdict(list)
        self.available_topics: Set[str] = set()
        self.line_count = 0
    
    def build_index(self) -> bool:
        """
        Build inverted index from chatlog JSONL.
        
        Returns:
            True if successful, False otherwise.
        """
        if not os.path.exists(self.chatlog_path):
            print(f"[INDEXER] Error: Chatlog not found: {self.chatlog_path}")
            return False
        
        print(f"[INDEXER] Building index from: {self.chatlog_path}")
        
        try:
            with open(self.chatlog_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        record = json.loads(line)
                        metadata = record.get("metadata", {})
                        
                        # Index topics
                        topics = metadata.get("topics", [])
                        if isinstance(topics, list):
                            for topic in topics:
                                if topic and isinstance(topic, str):
                                    topic = topic.strip()
                                    self.topic_index[topic].append(line_num)
                                    self.available_topics.add(topic)
                        
                        # Index sentiment
                        sentiment = metadata.get("sentiment", "")
                        if sentiment:
                            self.sentiment_index[sentiment].append(line_num)
                        
                        # Index fact keys
                        facts = metadata.get("facts", {})
                        if isinstance(facts, dict):
                            for key in facts.keys():
                                self.fact_keys_index[key].append(line_num)
                        
                        # Index information density
                        info_density = metadata.get("information_density", "")
                        if info_density:
                            self.info_density_index[info_density].append(line_num)
                        
                        self.line_count = line_num
                        
                    except json.JSONDecodeError:
                        continue
            
            print(f"[INDEXER] Indexed {self.line_count} messages")
            print(f"[INDEXER] Found {len(self.available_topics)} unique topics")
            return True
            
        except Exception as e:
            print(f"[INDEXER] Error building index: {e}")
            return False
    
    def save_index(self) -> bool:
        """
        Save index to JSON file.
        
        Returns:
            True if successful, False otherwise.
        """
        index_data = {
            "topic_index": dict(self.topic_index),
            "sentiment_index": dict(self.sentiment_index),
            "fact_keys_index": dict(self.fact_keys_index),
            "info_density_index": dict(self.info_density_index),
            "available_topics": sorted(self.available_topics),
            "line_count": self.line_count
        }
        
        try:
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            
            print(f"[INDEXER] Index saved to: {self.index_path}")
            print(f"[INDEXER] Index size: {os.path.getsize(self.index_path) / 1024:.1f} KB")
            return True
            
        except Exception as e:
            print(f"[INDEXER] Error saving index: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get indexing statistics."""
        return {
            "total_lines": self.line_count,
            "unique_topics": len(self.available_topics),
            "unique_sentiments": len(self.sentiment_index),
            "unique_fact_keys": len(self.fact_keys_index),
            "top_topics": sorted(
                [(t, len(lines)) for t, lines in self.topic_index.items()],
                key=lambda x: x[1],
                reverse=True
            )[:20]
        }


def build_and_save_index(chatlog_path: str = None) -> bool:
    """Convenience function to build and save index."""
    indexer = MetadataIndexer(chatlog_path)
    if indexer.build_index():
        if indexer.save_index():
            stats = indexer.get_stats()
            print(f"\n[INDEXER] Stats:")
            print(f"  Total lines: {stats['total_lines']}")
            print(f"  Unique topics: {stats['unique_topics']}")
            print(f"  Unique sentiments: {stats['unique_sentiments']}")
            print(f"  Unique fact keys: {stats['unique_fact_keys']}")
            print(f"\n[INDEXER] Top 10 topics:")
            for topic, count in stats['top_topics'][:10]:
                print(f"    {topic}: {count} messages")
            return True
    return False


if __name__ == "__main__":
    # Run indexer directly
    build_and_save_index()

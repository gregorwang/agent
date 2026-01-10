"""
Memory Storage Module for BENEDICTJUN Agent

Provides structured storage for long-term user memories including
preferences, facts, opinions, and attitudes.
"""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any


class MemoryCategory(str, Enum):
    """Categories for memory classification."""
    PREFERENCE = "preference"  # User preferences (coding style, format, etc.)
    FACT = "fact"              # Objective facts (name, job, location)
    OPINION = "opinion"        # Subjective opinions on topics
    ATTITUDE = "attitude"      # Values, attitudes, tendencies


@dataclass
class Memory:
    """A single memory entry."""
    id: str
    category: MemoryCategory
    content: str
    keywords: List[str] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "conversation"  # conversation, explicit, import
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Optional metadata
    topic: Optional[str] = None  # For opinions
    key: Optional[str] = None    # For preferences (key-value)
    value: Optional[str] = None  # For preferences
    aspect: Optional[str] = None # For attitudes
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: dict) -> "Memory":
        """Create from dictionary."""
        if isinstance(data.get("category"), str):
            data["category"] = MemoryCategory(data["category"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def matches_keywords(self, query_keywords: List[str]) -> float:
        """Calculate match score based on keyword overlap."""
        if not query_keywords or not self.keywords:
            # Fallback to content matching
            query_lower = " ".join(query_keywords).lower()
            content_lower = self.content.lower()
            if query_lower in content_lower or content_lower in query_lower:
                return 0.5
            return 0.0
        
        query_set = set(kw.lower() for kw in query_keywords)
        memory_set = set(kw.lower() for kw in self.keywords)
        
        if not memory_set:
            return 0.0
        
        overlap = len(query_set & memory_set)
        return overlap / len(memory_set)


@dataclass
class UserProfile:
    """Core user profile that's always available."""
    name: Optional[str] = None
    language: str = "zh-CN"
    timezone: Optional[str] = None
    occupation: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    def to_context_string(self) -> str:
        """Convert to a short context string for injection."""
        parts = []
        if self.name:
            parts.append(f"用户名称: {self.name}")
        if self.occupation:
            parts.append(f"职业: {self.occupation}")
        if self.language:
            parts.append(f"语言偏好: {self.language}")
        return "; ".join(parts) if parts else "暂无用户基本信息"


@dataclass
class MemoryConflict:
    """A detected memory conflict pending user resolution."""
    id: str
    existing_memory_id: str
    existing_content: str
    new_content: str
    category: MemoryCategory
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "MemoryConflict":
        if isinstance(data.get("category"), str):
            data["category"] = MemoryCategory(data["category"])
        return cls(**data)


class MemoryStorage:
    """
    Manages persistent memory storage.
    
    Storage location: ~/.benedictjun/memories.json
    """
    
    DEFAULT_PATH = Path.home() / ".benedictjun" / "memories.json"
    
    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize memory storage."""
        self.storage_path = storage_path or self.DEFAULT_PATH
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._profile: UserProfile = UserProfile()
        self._memories: Dict[str, Memory] = {}
        self._conflicts: List[MemoryConflict] = []
        
        self._load()
    
    def _load(self) -> None:
        """Load memories from disk."""
        if not self.storage_path.exists():
            return
        
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            
            # Load profile
            if "profile" in data:
                self._profile = UserProfile.from_dict(data["profile"])
            
            # Load memories
            for mem_data in data.get("memories", []):
                try:
                    mem = Memory.from_dict(mem_data)
                    self._memories[mem.id] = mem
                except Exception:
                    continue
            
            # Load conflicts
            for conflict_data in data.get("conflicts", []):
                try:
                    self._conflicts.append(MemoryConflict.from_dict(conflict_data))
                except Exception:
                    continue
                    
        except (json.JSONDecodeError, Exception):
            # Start fresh if file is corrupted
            pass
    
    def _save(self) -> None:
        """Save memories to disk."""
        data = {
            "profile": self._profile.to_dict(),
            "memories": [m.to_dict() for m in self._memories.values()],
            "conflicts": [c.to_dict() for c in self._conflicts],
            "updated_at": datetime.now().isoformat()
        }
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    # ═══════════════════════════════════════════════════════════════
    # Profile Management
    # ═══════════════════════════════════════════════════════════════
    
    def get_profile(self) -> UserProfile:
        """Get the user profile."""
        return self._profile
    
    def update_profile(self, **kwargs) -> None:
        """Update user profile fields."""
        for key, value in kwargs.items():
            if hasattr(self._profile, key):
                setattr(self._profile, key, value)
        self._save()
    
    # ═══════════════════════════════════════════════════════════════
    # Memory CRUD
    # ═══════════════════════════════════════════════════════════════
    
    def add_memory(
        self,
        category: MemoryCategory,
        content: str,
        keywords: Optional[List[str]] = None,
        confidence: float = 1.0,
        source: str = "conversation",
        **extra
    ) -> Memory:
        """Add a new memory."""
        # Auto-extract keywords if not provided
        if keywords is None:
            keywords = self._extract_keywords(content)
        
        memory = Memory(
            id=str(uuid.uuid4())[:8],
            category=category,
            content=content,
            keywords=keywords,
            confidence=confidence,
            source=source,
            **extra
        )
        
        self._memories[memory.id] = memory
        self._save()
        return memory
    
    def get_memory(self, memory_id: str) -> Optional[Memory]:
        """Get a memory by ID."""
        return self._memories.get(memory_id)
    
    def update_memory(self, memory_id: str, **updates) -> Optional[Memory]:
        """Update a memory."""
        memory = self._memories.get(memory_id)
        if not memory:
            return None
        
        for key, value in updates.items():
            if hasattr(memory, key):
                setattr(memory, key, value)
        
        memory.updated_at = datetime.now().isoformat()
        self._save()
        return memory
    
    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory."""
        if memory_id in self._memories:
            del self._memories[memory_id]
            self._save()
            return True
        return False
    
    def clear_all(self) -> int:
        """Clear all memories. Returns count of deleted memories."""
        count = len(self._memories)
        self._memories.clear()
        self._conflicts.clear()
        self._save()
        return count
    
    # ═══════════════════════════════════════════════════════════════
    # Memory Retrieval
    # ═══════════════════════════════════════════════════════════════
    
    def list_memories(
        self,
        category: Optional[MemoryCategory] = None,
        limit: int = 50
    ) -> List[Memory]:
        """List memories, optionally filtered by category."""
        memories = list(self._memories.values())
        
        if category:
            memories = [m for m in memories if m.category == category]
        
        # Sort by updated_at descending
        memories.sort(key=lambda m: m.updated_at, reverse=True)
        
        return memories[:limit]
    
    def search_by_keywords(
        self,
        query: str,
        limit: int = 5,
        min_score: float = 0.1
    ) -> List[tuple]:
        """
        Search memories by keyword matching.
        
        Returns list of (memory, score) tuples sorted by relevance.
        """
        # Extract keywords from query
        query_keywords = self._extract_keywords(query)
        
        if not query_keywords:
            return []
        
        results = []
        for memory in self._memories.values():
            score = memory.matches_keywords(query_keywords)
            
            # Boost score based on content match
            query_lower = query.lower()
            content_lower = memory.content.lower()
            if query_lower in content_lower:
                score += 0.3
            elif any(kw in content_lower for kw in query_keywords):
                score += 0.1
            
            if score >= min_score:
                results.append((memory, score))
        
        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text (simple implementation)."""
        # Common stop words
        stop_words = {
            "的", "是", "在", "我", "有", "和", "就", "不", "人", "都",
            "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
            "会", "着", "没有", "看", "好", "自己", "这", "the", "a", "an",
            "is", "are", "was", "were", "be", "been", "being", "have", "has",
            "had", "do", "does", "did", "will", "would", "could", "should",
            "i", "you", "he", "she", "it", "we", "they", "my", "your", "his",
            "her", "its", "our", "their", "this", "that", "these", "those",
            "what", "which", "who", "whom", "where", "when", "why", "how",
            "and", "or", "but", "if", "because", "as", "until", "while",
            "for", "with", "about", "against", "between", "into", "through",
            "during", "before", "after", "above", "below", "to", "from",
            "up", "down", "in", "out", "on", "off", "over", "under", "again",
        }
        
        # Simple tokenization
        import re
        tokens = re.findall(r'\b[\w\u4e00-\u9fff]+\b', text.lower())
        
        # Filter stop words and short tokens
        keywords = [
            t for t in tokens 
            if t not in stop_words and len(t) > 1
        ]
        
        return keywords[:10]  # Limit to 10 keywords
    
    # ═══════════════════════════════════════════════════════════════
    # Conflict Management
    # ═══════════════════════════════════════════════════════════════
    
    def detect_conflict(
        self,
        category: MemoryCategory,
        new_content: str,
        key: Optional[str] = None
    ) -> Optional[MemoryConflict]:
        """
        Check if new memory conflicts with existing ones.
        
        For preferences with the same key, or facts/opinions with
        very similar content.
        """
        for memory in self._memories.values():
            if memory.category != category:
                continue
            
            # For preferences, check key match
            if category == MemoryCategory.PREFERENCE and key:
                if memory.key == key and memory.value != new_content:
                    conflict = MemoryConflict(
                        id=str(uuid.uuid4())[:8],
                        existing_memory_id=memory.id,
                        existing_content=f"{memory.key}: {memory.value}",
                        new_content=f"{key}: {new_content}",
                        category=category
                    )
                    self._conflicts.append(conflict)
                    self._save()
                    return conflict
            
            # For other categories, check content similarity
            else:
                # Simple overlap check
                existing_keywords = set(self._extract_keywords(memory.content))
                new_keywords = set(self._extract_keywords(new_content))
                
                if existing_keywords and new_keywords:
                    overlap = len(existing_keywords & new_keywords)
                    similarity = overlap / min(len(existing_keywords), len(new_keywords))
                    
                    if similarity > 0.7 and memory.content != new_content:
                        conflict = MemoryConflict(
                            id=str(uuid.uuid4())[:8],
                            existing_memory_id=memory.id,
                            existing_content=memory.content,
                            new_content=new_content,
                            category=category
                        )
                        self._conflicts.append(conflict)
                        self._save()
                        return conflict
        
        return None
    
    def get_conflicts(self) -> List[MemoryConflict]:
        """Get all pending conflicts."""
        return self._conflicts.copy()
    
    def resolve_conflict(
        self,
        conflict_id: str,
        action: str  # "replace", "keep_both", "ignore"
    ) -> bool:
        """
        Resolve a conflict.
        
        Actions:
        - replace: Delete old memory, add new one
        - keep_both: Keep both memories
        - ignore: Discard new memory, keep old
        """
        conflict = None
        for c in self._conflicts:
            if c.id == conflict_id:
                conflict = c
                break
        
        if not conflict:
            return False
        
        if action == "replace":
            # Delete old, add new
            self.delete_memory(conflict.existing_memory_id)
            self.add_memory(
                category=conflict.category,
                content=conflict.new_content,
                source="conflict_resolution"
            )
        elif action == "keep_both":
            # Just add the new one
            self.add_memory(
                category=conflict.category,
                content=conflict.new_content,
                source="conflict_resolution"
            )
        # For "ignore", we just remove the conflict
        
        self._conflicts.remove(conflict)
        self._save()
        return True
    
    # ═══════════════════════════════════════════════════════════════
    # Statistics
    # ═══════════════════════════════════════════════════════════════
    
    def get_stats(self) -> dict:
        """Get memory statistics."""
        by_category = {}
        for cat in MemoryCategory:
            count = sum(1 for m in self._memories.values() if m.category == cat)
            by_category[cat.value] = count
        
        return {
            "total_memories": len(self._memories),
            "by_category": by_category,
            "pending_conflicts": len(self._conflicts),
            "has_profile": self._profile.name is not None,
            "storage_path": str(self.storage_path)
        }


# Global instance
_storage: Optional[MemoryStorage] = None


def get_memory_storage(storage_path: Optional[Path] = None) -> MemoryStorage:
    """Get or create the global MemoryStorage instance."""
    global _storage
    if _storage is None:
        _storage = MemoryStorage(storage_path)
    return _storage

"""
Chatlog Searcher - Multi-keyword search with context expansion

Features:
- Multi-keyword parallel search
- Context window expansion (before/after N messages)
- Deduplication and merging of overlapping windows
- Person-focused filtering
"""

from typing import List, Set, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from .loader import ChatlogLoader, ChatMessage, get_chatlog_loader


@dataclass
class SearchResult:
    """Result of a chatlog search."""
    messages: List[ChatMessage] = field(default_factory=list)
    matched_keywords: Set[str] = field(default_factory=set)
    total_chars: int = 0
    matched_line_keywords: Dict[int, Set[str]] = field(default_factory=dict)
    
    def format_output(self, include_line_numbers: bool = False) -> str:
        """
        Format messages for output.
        
        Args:
            include_line_numbers: Whether to include line numbers
            
        Returns:
            Formatted string of all messages
        """
        if not self.messages:
            return "未找到相关聊天记录。"
        
        lines = []
        for msg in self.messages:
            if include_line_numbers:
                lines.append(msg.format_with_line())
            else:
                lines.append(msg.format_simple())
        
        return "\n".join(lines)
    
    def get_summary(self) -> str:
        """Get a summary of the search result."""
        return (
            f"找到 {len(self.messages)} 条相关消息，"
            f"匹配关键词: {', '.join(self.matched_keywords)}，"
            f"总字符数: {self.total_chars}"
        )


class ChatlogSearcher:
    """
    Intelligent chatlog searcher with context awareness.
    
    Features:
    - Multi-keyword search
    - Context window (configurable before/after)
    - Deduplication
    - Person filtering
    """
    
    def __init__(
        self,
        loader: Optional[ChatlogLoader] = None,
        context_before: int = 5,
        context_after: int = 5
    ):
        """
        Initialize searcher.
        
        Args:
            loader: ChatlogLoader instance
            context_before: Messages to include before match
            context_after: Messages to include after match
        """
        self.loader = loader or get_chatlog_loader()
        self.context_before = context_before
        self.context_after = context_after
    
    def search(
        self,
        keywords: List[str],
        target_person: Optional[str] = None,
        max_results: int = 100
    ) -> SearchResult:
        """
        Search chatlog with multiple keywords.
        
        Args:
            keywords: List of keywords to search
            target_person: Optional person to prioritize
            max_results: Maximum number of messages to return
            
        Returns:
            SearchResult with matched messages
        """
        if not self.loader.is_loaded:
            self.loader.load()
        
        # Collect all matching line numbers
        matched_lines: Dict[int, Set[str]] = {}  # line_number -> set of matched keywords
        
        for keyword in keywords:
            if not keyword.strip():
                continue
            
            # Use comprehensive search (content + topics + facts metadata)
            matching = self.loader.comprehensive_search(
                [keyword], 
                include_content=True,
                include_topics=True,
                include_facts=True
            )
            for line_num in matching:
                if line_num not in matched_lines:
                    matched_lines[line_num] = set()
                matched_lines[line_num].add(keyword)
        
        # If target person specified, also search for their messages
        if target_person:
            person_messages = self.loader.get_messages_by_sender(target_person)
            for msg in person_messages:
                if msg.line_number not in matched_lines:
                    matched_lines[msg.line_number] = set()
                matched_lines[msg.line_number].add(f"发送者:{target_person}")
        
        if not matched_lines:
            return SearchResult()
        
        # Expand context windows for each match
        all_line_numbers: Set[int] = set()
        for line_num in matched_lines.keys():
            # Get context window
            start = max(1, line_num - self.context_before)
            end = line_num + self.context_after
            
            for ln in range(start, end + 1):
                all_line_numbers.add(ln)
        
        # Sort and deduplicate
        sorted_lines = sorted(all_line_numbers)
        
        # Limit results
        if len(sorted_lines) > max_results:
            # Prioritize lines that matched keywords directly
            direct_matches = sorted(matched_lines.keys())
            
            # Start with direct matches and their immediate context
            priority_lines: Set[int] = set()
            for line_num in direct_matches:
                start = max(1, line_num - 2)  # Smaller context for priority
                end = line_num + 2
                for ln in range(start, end + 1):
                    priority_lines.add(ln)
                    if len(priority_lines) >= max_results:
                        break
                if len(priority_lines) >= max_results:
                    break
            
            sorted_lines = sorted(priority_lines)
        
        # Collect messages
        messages: List[ChatMessage] = []
        for line_num in sorted_lines:
            msg = self.loader.get_message(line_num)
            if msg:
                messages.append(msg)
        
        # Calculate total chars
        total_chars = sum(len(msg.content) for msg in messages)
        
        # Collect matched keywords
        all_keywords: Set[str] = set()
        for kw_set in matched_lines.values():
            all_keywords.update(kw_set)
        
        return SearchResult(
            messages=messages,
            matched_keywords=all_keywords,
            total_chars=total_chars,
            matched_line_keywords=matched_lines
        )

    def search_by_metadata(
        self,
        metadata: Dict[str, Any],
        keywords: Optional[List[str]] = None,
        target_person: Optional[str] = None,
        max_results: int = 100
    ) -> SearchResult:
        """
        Search using metadata fields (topics, facts, sentiment, information_density).

        Args:
            metadata: Query metadata dict
            keywords: Optional keywords derived from metadata
            target_person: Optional person to prioritize
            max_results: Maximum number of messages to return

        Returns:
            SearchResult with matched messages
        """
        if not self.loader.is_loaded:
            self.loader.load()

        keywords = keywords or []
        topics = metadata.get("topics") or []
        facts = metadata.get("facts") or {}
        sentiment = metadata.get("sentiment") or ""
        info_density = metadata.get("information_density") or ""

        matched_lines: Dict[int, Set[str]] = {}

        if topics:
            for line_num in self.loader.search_topics(topics):
                matched_lines.setdefault(line_num, set()).add("topic")

        if facts:
            for line_num in self.loader.search_facts(list(facts.keys())):
                matched_lines.setdefault(line_num, set()).add("fact")

        if keywords:
            for keyword in keywords:
                if not keyword.strip():
                    continue
                for line_num in self.loader.search_content(keyword):
                    matched_lines.setdefault(line_num, set()).add(keyword)

        if sentiment:
            sentiment_lines = set(self.loader.search_sentiment(sentiment))
            matched_lines = {
                ln: kw for ln, kw in matched_lines.items() if ln in sentiment_lines
            }

        if info_density:
            density_lines = set(
                self.loader.search_information_density(info_density)
            )
            matched_lines = {
                ln: kw for ln, kw in matched_lines.items() if ln in density_lines
            }

        if target_person:
            person_messages = self.loader.get_messages_by_sender(target_person)
            for msg in person_messages:
                matched_lines.setdefault(msg.line_number, set()).add(
                    f"发送者:{target_person}"
                )

        if not matched_lines:
            return SearchResult()

        all_line_numbers: Set[int] = set()
        for line_num in matched_lines.keys():
            start = max(1, line_num - self.context_before)
            end = line_num + self.context_after
            for ln in range(start, end + 1):
                all_line_numbers.add(ln)

        sorted_lines = sorted(all_line_numbers)

        if len(sorted_lines) > max_results:
            direct_matches = sorted(matched_lines.keys())
            priority_lines: Set[int] = set()
            for line_num in direct_matches:
                start = max(1, line_num - 2)
                end = line_num + 2
                for ln in range(start, end + 1):
                    priority_lines.add(ln)
                    if len(priority_lines) >= max_results:
                        break
                if len(priority_lines) >= max_results:
                    break
            sorted_lines = sorted(priority_lines)

        messages: List[ChatMessage] = []
        for line_num in sorted_lines:
            msg = self.loader.get_message(line_num)
            if msg:
                messages.append(msg)

        total_chars = sum(len(msg.content) for msg in messages)

        all_keywords: Set[str] = set()
        for kw_set in matched_lines.values():
            all_keywords.update(kw_set)

        return SearchResult(
            messages=messages,
            matched_keywords=all_keywords,
            total_chars=total_chars,
            matched_line_keywords=matched_lines
        )
    
    def search_person_context(
        self,
        person: str,
        keywords: List[str],
        max_results: int = 100
    ) -> SearchResult:
        """
        Search focusing on a specific person with additional keywords.
        
        Prioritizes messages from/to the person while also including
        keyword matches.
        
        Args:
            person: Person to focus on
            keywords: Additional keywords
            max_results: Maximum messages
            
        Returns:
            SearchResult
        """
        # Get all messages from this person
        person_messages = self.loader.get_messages_by_sender(person)
        person_lines = {msg.line_number for msg in person_messages}
        
        # Also search keywords
        keyword_result = self.search(keywords, target_person=None, max_results=max_results * 2)
        keyword_lines = {msg.line_number for msg in keyword_result.messages}
        
        # Combine: person messages + keyword matches involving person
        combined_lines: Set[int] = set()
        
        # Add all person messages (with smaller context)
        for line_num in person_lines:
            start = max(1, line_num - 2)
            end = line_num + 2
            for ln in range(start, end + 1):
                combined_lines.add(ln)
        
        # Add keyword matches
        combined_lines.update(keyword_lines)
        
        # Sort and limit
        sorted_lines = sorted(combined_lines)[:max_results]
        
        # Collect messages
        messages: List[ChatMessage] = []
        for line_num in sorted_lines:
            msg = self.loader.get_message(line_num)
            if msg:
                messages.append(msg)
        
        total_chars = sum(len(msg.content) for msg in messages)
        
        return SearchResult(
            messages=messages,
            matched_keywords=keyword_result.matched_keywords | {f"person:{person}"},
            total_chars=total_chars,
            matched_line_keywords=keyword_result.matched_line_keywords
        )
    
    def get_conversation_segments(
        self,
        result: SearchResult,
        gap_threshold: int = 10
    ) -> List[List[ChatMessage]]:
        """
        Split search result into conversation segments.
        
        Messages with line number gaps > threshold are split into
        separate segments.
        
        Args:
            result: SearchResult to segment
            gap_threshold: Max line gap before splitting
            
        Returns:
            List of message segments
        """
        if not result.messages:
            return []
        
        segments: List[List[ChatMessage]] = []
        current_segment: List[ChatMessage] = [result.messages[0]]
        
        for i in range(1, len(result.messages)):
            prev_msg = result.messages[i - 1]
            curr_msg = result.messages[i]
            
            if curr_msg.line_number - prev_msg.line_number > gap_threshold:
                # Start new segment
                segments.append(current_segment)
                current_segment = [curr_msg]
            else:
                current_segment.append(curr_msg)
        
        if current_segment:
            segments.append(current_segment)
        
        return segments
    
    def format_segmented_output(
        self,
        result: SearchResult,
        gap_threshold: int = 10
    ) -> str:
        """
        Format result with segment separators.
        
        Args:
            result: SearchResult
            gap_threshold: Gap threshold for segmentation
            
        Returns:
            Formatted string with segment separators
        """
        if result.matched_line_keywords:
            return self.format_context_windows(result)

        segments = self.get_conversation_segments(result, gap_threshold)

        if not segments:
            return "未找到相关聊天记录。"

        output_parts = []
        for i, segment in enumerate(segments):
            if i > 0:
                output_parts.append("\n--- 对话片段分隔 ---\n")

            for msg in segment:
                output_parts.append(msg.format_simple())

        return "\n".join(output_parts)

    def format_context_windows(
        self,
        result: SearchResult,
        max_windows: int = 50
    ) -> str:
        """Format output as hit-centered context windows."""
        if not result.matched_line_keywords:
            return "未找到相关聊天记录。"

        matched_lines = sorted(result.matched_line_keywords.keys())
        output_parts: List[str] = []

        for idx, line_num in enumerate(matched_lines[:max_windows], 1):
            start = max(1, line_num - self.context_before)
            end = line_num + self.context_after

            output_parts.append(
                f"--- 命中窗口 {idx} (行 {line_num}, ±{self.context_before}/{self.context_after}) ---"
            )

            for ln in range(start, end + 1):
                msg = self.loader.get_message(ln)
                if not msg:
                    continue
                sender = msg.sender or "未知"
                content = msg.message or msg.content
                tag = "命中" if ln == line_num else "上下文"
                confidence = "高" if ln == line_num else "中"
                output_parts.append(
                    f"[{msg.timestamp}] {sender}: {content} (行{msg.line_number} {tag} 置信度:{confidence})"
                )

        return "\n".join(output_parts)

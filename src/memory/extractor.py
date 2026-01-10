"""
Memory Extractor for BENEDICTJUN Agent

Extracts memories from conversations using GPT-5-nano (Poe API).
Runs asynchronously after conversations to identify and store
user preferences, facts, opinions, and attitudes.
"""

import json
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from .storage import (
    MemoryStorage,
    MemoryCategory,
    Memory,
    get_memory_storage
)
from .poe_client import PoeClient, get_poe_client


# ═══════════════════════════════════════════════════════════════════════════════
# Extraction Prompt Template
# ═══════════════════════════════════════════════════════════════════════════════

EXTRACTION_PROMPT = """你是一个**长期记忆**提取助手。你的任务是从对话中提取值得**永久记住**的用户个人信息。

## 对话内容
{conversation}

## ⚠️ 重要：只提取长期有效的信息

### ✅ 应该提取的内容（长期有效）
- **身份信息**: 姓名、职业、居住地、家乡、年龄等
- **稳定偏好**: 编程语言偏好、工具选择、代码风格、学习方法等
- **持久态度**: 人生价值观、长期目标、自我认知等
- **重要关系**: 朋友/家人的名字、重要人物等
- **长期事实**: 拥有的网站、创建的项目、擅长的技能等

### ❌ 不应该提取的内容（临时信息）
- **操作请求**: "帮我读取文件"、"搜索xxx"、"运行这个命令" → 这是给AI的指令，不是用户属性
- **对话元描述**: "涉及钱财问题"、"用户询问关于xxx"、"讨论了某话题" → 这是在描述对话本身
- **临时行为**: "正在考虑是否借钱"、"想要查询某信息" → 这是一次性的行为
- **AI的回答**: 任何来自助手/AI的内容
- **模糊/不完整信息**: "涉及某事但未给出具体信息" → 没有具体内容就不要记录

### 判断标准
问自己：**"这条信息明天、下个月、明年还会有效吗？"**
- 如果是 → 提取
- 如果否 → 不提取

## 类别说明
- **preferences**: 用户的长期偏好（编码风格、工具选择、学习偏好等）
- **facts**: 长期有效的客观事实（身份、地点、拥有物、关系等）
- **opinions**: 用户对事物的稳定看法
- **attitudes**: 长期的态度和价值观

## 输出格式
请以 JSON 格式输出。如果某类别没有发现**长期有效的**信息，返回空数组。
如果完全没有值得**永久记录**的信息，返回空对象 {{}}

```json
{{
  "profile_updates": {{
    "name": "用户姓名（如有）",
    "occupation": "职业（如有）"
  }},
  "preferences": [
    {{"key": "偏好名称", "value": "偏好值", "confidence": 0.9}}
  ],
  "facts": [
    {{"content": "事实描述", "keywords": ["关键词1", "关键词2"]}}
  ],
  "opinions": [
    {{"topic": "讨论主题", "content": "用户的观点"}}
  ],
  "attitudes": [
    {{"aspect": "方面", "attitude": "态度描述"}}
  ]
}}
```

只输出 JSON，不要其他解释。"""


@dataclass
class ExtractionResult:
    """Result of memory extraction."""
    profile_updates: Dict[str, str]
    preferences: List[Dict[str, Any]]
    facts: List[Dict[str, Any]]
    opinions: List[Dict[str, Any]]
    attitudes: List[Dict[str, Any]]
    raw_response: str
    
    @property
    def has_content(self) -> bool:
        """Check if any memories were extracted."""
        return bool(
            self.profile_updates or
            self.preferences or
            self.facts or
            self.opinions or
            self.attitudes
        )
    
    @property
    def total_count(self) -> int:
        """Total number of extracted items."""
        return (
            len(self.preferences) +
            len(self.facts) +
            len(self.opinions) +
            len(self.attitudes)
        )


class MemoryExtractor:
    """
    Extracts memories from conversations using a small LLM.
    
    Uses GPT-5-nano via Poe API for cost-effective extraction.
    """
    
    def __init__(
        self,
        poe_client: Optional[PoeClient] = None,
        storage: Optional[MemoryStorage] = None
    ):
        """Initialize the extractor."""
        self.poe = poe_client or get_poe_client()
        self.storage = storage or get_memory_storage()
    
    async def extract_from_conversation(
        self,
        conversation: str,
        auto_save: bool = True
    ) -> Optional[ExtractionResult]:
        """
        Extract memories from a conversation.
        
        Args:
            conversation: The conversation text to analyze
            auto_save: Whether to automatically save extracted memories
            
        Returns:
            ExtractionResult with extracted memories, or None on error
        """
        if not self.poe.is_configured:
            return None
        
        # Build prompt
        prompt = EXTRACTION_PROMPT.format(conversation=conversation)
        
        # Call Poe API
        response = await self.poe.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,  # Lower temperature for more consistent extraction
            max_tokens=1500
        )
        
        if not response:
            return None
        
        # Parse response
        result = self._parse_response(response)
        
        if result and result.has_content and auto_save:
            self._save_extracted_memories(result)
        
        return result
    
    def _parse_response(self, response: str) -> Optional[ExtractionResult]:
        """Parse the JSON response from the extraction model."""
        try:
            # Try to extract JSON from response
            # Handle cases where model includes markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    return None
            
            data = json.loads(json_str)
            
            # Handle empty response
            if not data:
                return ExtractionResult(
                    profile_updates={},
                    preferences=[],
                    facts=[],
                    opinions=[],
                    attitudes=[],
                    raw_response=response
                )
            
            return ExtractionResult(
                profile_updates=data.get("profile_updates", {}),
                preferences=data.get("preferences", []),
                facts=data.get("facts", []),
                opinions=data.get("opinions", []),
                attitudes=data.get("attitudes", []),
                raw_response=response
            )
            
        except json.JSONDecodeError as e:
            print(f"Failed to parse extraction response: {e}")
            return None
        except Exception as e:
            print(f"Extraction parsing error: {e}")
            return None
    
    def _save_extracted_memories(self, result: ExtractionResult) -> int:
        """
        Save extracted memories to storage.
        
        Returns the number of memories saved.
        """
        saved_count = 0
        
        # Update profile if provided
        if result.profile_updates:
            self.storage.update_profile(**result.profile_updates)
        
        # Save preferences
        for pref in result.preferences:
            if "key" in pref and "value" in pref:
                # Check for conflicts
                conflict = self.storage.detect_conflict(
                    MemoryCategory.PREFERENCE,
                    pref["value"],
                    key=pref["key"]
                )
                
                if not conflict:
                    self.storage.add_memory(
                        category=MemoryCategory.PREFERENCE,
                        content=f"{pref['key']}: {pref['value']}",
                        key=pref["key"],
                        value=pref["value"],
                        confidence=pref.get("confidence", 0.8),
                        source="extraction",
                        keywords=[pref["key"]]
                    )
                    saved_count += 1
        
        # Save facts
        for fact in result.facts:
            if "content" in fact:
                conflict = self.storage.detect_conflict(
                    MemoryCategory.FACT,
                    fact["content"]
                )
                
                if not conflict:
                    self.storage.add_memory(
                        category=MemoryCategory.FACT,
                        content=fact["content"],
                        keywords=fact.get("keywords", []),
                        source="extraction"
                    )
                    saved_count += 1
        
        # Save opinions
        for opinion in result.opinions:
            if "content" in opinion:
                conflict = self.storage.detect_conflict(
                    MemoryCategory.OPINION,
                    opinion["content"]
                )
                
                if not conflict:
                    self.storage.add_memory(
                        category=MemoryCategory.OPINION,
                        content=opinion["content"],
                        topic=opinion.get("topic"),
                        keywords=[opinion.get("topic", "")] if opinion.get("topic") else [],
                        source="extraction"
                    )
                    saved_count += 1
        
        # Save attitudes
        for att in result.attitudes:
            if "attitude" in att:
                content = f"{att.get('aspect', 'general')}: {att['attitude']}"
                
                conflict = self.storage.detect_conflict(
                    MemoryCategory.ATTITUDE,
                    content
                )
                
                if not conflict:
                    self.storage.add_memory(
                        category=MemoryCategory.ATTITUDE,
                        content=content,
                        aspect=att.get("aspect"),
                        keywords=[att.get("aspect", "")] if att.get("aspect") else [],
                        source="extraction"
                    )
                    saved_count += 1
        
        return saved_count
    
    async def extract_and_report(
        self,
        conversation: str
    ) -> str:
        """
        Extract memories and return a human-readable report.
        
        Args:
            conversation: The conversation to analyze
            
        Returns:
            A formatted string report of extracted memories
        """
        result = await self.extract_from_conversation(conversation, auto_save=True)
        
        if not result:
            return "❌ 记忆提取失败（API 错误或未配置）"
        
        if not result.has_content:
            return "✓ 分析完成，无需记录的新信息"
        
        lines = [f"✓ 提取了 {result.total_count} 条记忆："]
        
        if result.profile_updates:
            lines.append(f"  📋 用户资料更新: {result.profile_updates}")
        
        if result.preferences:
            lines.append(f"  ⚙️ 偏好: {len(result.preferences)} 条")
        
        if result.facts:
            lines.append(f"  📌 事实: {len(result.facts)} 条")
        
        if result.opinions:
            lines.append(f"  💭 观点: {len(result.opinions)} 条")
        
        if result.attitudes:
            lines.append(f"  🎯 态度: {len(result.attitudes)} 条")
        
        # Check for conflicts
        conflicts = self.storage.get_conflicts()
        if conflicts:
            lines.append(f"\n⚠️ 检测到 {len(conflicts)} 个冲突，请使用 /memory conflicts 查看")
        
        return "\n".join(lines)


# Global instance
_extractor: Optional[MemoryExtractor] = None


def get_memory_extractor() -> MemoryExtractor:
    """Get or create the global MemoryExtractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = MemoryExtractor()
    return _extractor

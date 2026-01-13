"""
Chatlog Cleaner - Small model based cleaning and keyword expansion

Uses Poe API with Gemini-2.5-Flash-Lite for:
- Keyword expansion from user questions
- Result cleaning when data exceeds threshold
"""

import os
import json
import asyncio
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Reuse existing Poe client
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from memory.poe_client import PoeClient, PoeConfig
except ImportError:
    PoeClient = None
    PoeConfig = None



@dataclass
class CleanerConfig:
    """Configuration for chatlog cleaner."""
    model: str = "Gemini-2.5-Flash-Lite"  # Fast and cheap model
    min_keywords: int = 10
    max_keywords: int = 20
    min_topics: int = 10
    max_topics: int = 20
    char_threshold: int = 1500  # Trigger cleaning if above this (reduced from 3000)
    target_chars: int = 800  # Target size after cleaning (reduced from 2000)
    timeout: int = 30


class ChatlogCleaner:
    """
    Cleans and processes chatlog search results using small models.
    
    Features:
    - Keyword expansion from questions
    - Result size reduction
    - Relevance filtering
    """
    
    def __init__(self, config: Optional[CleanerConfig] = None):
        """Initialize cleaner."""
        self.config = config or CleanerConfig()
        
        # Get model from env if set
        env_model = os.getenv("CHATLOG_CLEANER_MODEL")
        if env_model:
            self.config.model = env_model
        
        self._poe_client: Optional[PoeClient] = None
    
    def _get_poe_client(self) -> Optional["PoeClient"]:
        """Get or create Poe client."""
        if PoeClient is None:
            print("Poe client not available")
            return None
        
        if self._poe_client is None:
            api_key = os.getenv("POE_API_KEY", "")
            if not api_key:
                print("POE_API_KEY not configured")
                return None
            
            poe_config = PoeConfig(
                api_key=api_key,
                model=self.config.model,
                timeout=self.config.timeout
            )
            self._poe_client = PoeClient(poe_config)
        
        return self._poe_client
    
    async def expand_keywords(
        self,
        question: str,
        target_person: Optional[str] = None,
        available_topics: Optional[List[str]] = None
    ) -> List[str]:
        """
        Expand a question into multiple search keywords.

        Args:
            question: User's question
            target_person: Optional person the question is about

        Returns:
            List of keywords for searching
        """
        keywords, _ = await self.expand_query(
            question, target_person, available_topics
        )
        return keywords

    async def expand_query(
        self,
        question: str,
        target_person: Optional[str] = None,
        available_topics: Optional[List[str]] = None
    ) -> tuple[List[str], Dict[str, Any]]:
        """
        Expand a question into keywords and query metadata.
        """
        client = self._get_poe_client()

        if client is None or not client.is_configured:
            metadata = self._fallback_metadata_classification(question, available_topics)
            if self._is_borrow_question(question):
                metadata["topics"] = self._inject_borrow_topics(
                    metadata.get("topics", []),
                    available_topics
                )
            metadata["topics"] = self._ensure_topic_coverage(
                question=question,
                target_person=target_person,
                keywords=self._fallback_keyword_extraction(
                    question, target_person, available_topics
                ),
                topics=metadata.get("topics", []),
                available_topics=available_topics
            )
            return (
                self._fallback_keyword_extraction(
                    question, target_person, available_topics
                ),
                metadata,
            )

        person_hint = f"\n目标人物: {target_person}" if target_person else ""
        topics_hint = ""
        if available_topics:
            topics_preview = ", ".join(available_topics[:50])
            topics_hint = f"\n可用话题标签(只能从中选择): {topics_preview}"

        prompt = f"""根据用户问题，生成用于检索聊天记录的查询信息。

输出 JSON 对象，包含：
1) keywords: 关键词数组，长度 {self.config.min_keywords}-{self.config.max_keywords}，数量由模型自行决定
2) metadata: {{
    \"topics\": 话题标签数组，
    \"sentiment\": 情感标签（positive/neutral/negative），
    \"facts\": 事实键值对（可为空对象），
    \"information_density\": 信息密度（low/medium/high）
}}

要求：
- keywords 必须与 metadata 一致，覆盖最关键的检索点
- 不要扩写无关场景
- 【禁止】生成具体职业名称（如：保安/搬运/医生/护士），除非用户问题明确提及
- 【禁止】生成具体数字（如：4000/5000/6000），除非用户问题明确提及
- 每个关键词尽量简短（2-4个字）
        - 如果是借钱/信任类问题，关键词必须覆盖：工资、职业、消费习惯、资产、历史信誉、评价
        - 话题标签必须只从“可用话题标签”中选择，且优先选择：借贷/金钱/工资/职业/消费习惯/评价/信誉等相关话题
        - 输出必须是 JSON，不要其他文字

  用户问题: {question}{person_hint}{topics_hint}"""

        try:
            response = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model,
                temperature=0.3,
                max_tokens=300
            )

            if response:
                response = response.strip()
                start_idx = response.find("{")
                end_idx = response.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    json_str = response[start_idx:end_idx + 1]
                    payload = json.loads(json_str)
                    keywords = payload.get("keywords", [])
                    metadata = payload.get("metadata", {})

                    if isinstance(keywords, list):
                        keywords = [
                            k.strip()
                            for k in keywords
                            if isinstance(k, str) and k.strip()
                        ]
                    else:
                        keywords = []

                    if target_person and target_person not in keywords:
                        keywords.insert(0, target_person)

                    keywords = keywords[:self.config.max_keywords]
                    if len(keywords) < self.config.min_keywords:
                        keywords = self._fallback_keyword_extraction(
                            question, target_person, available_topics
                        )[:self.config.max_keywords]

                    metadata = self._normalize_metadata(metadata, available_topics)
                    if self._is_borrow_question(question):
                        metadata["topics"] = self._inject_borrow_topics(
                            metadata.get("topics", []),
                            available_topics
                        )
                    metadata["topics"] = self._ensure_topic_coverage(
                        question=question,
                        target_person=target_person,
                        keywords=keywords,
                        topics=metadata.get("topics", []),
                        available_topics=available_topics
                    )
                    return keywords, metadata

        except Exception as e:
            print(f"Query expansion error: {e}")

        metadata = self._fallback_metadata_classification(question, available_topics)
        if self._is_borrow_question(question):
            metadata["topics"] = self._inject_borrow_topics(
                metadata.get("topics", []),
                available_topics
            )
        metadata["topics"] = self._ensure_topic_coverage(
            question=question,
            target_person=target_person,
            keywords=self._fallback_keyword_extraction(
                question, target_person, available_topics
            ),
            topics=metadata.get("topics", []),
            available_topics=available_topics
        )
        return (
            self._fallback_keyword_extraction(
                question, target_person, available_topics
            ),
            metadata,
        )

    async def plan_evidence_dimensions(
        self,
        question: str,
        target_person: Optional[str] = None,
        available_topics: Optional[List[str]] = None,
        max_dimensions: int = 4,
    ) -> Dict[str, Any]:
        client = self._get_poe_client()
        if client is None or not client.is_configured:
            return self._fallback_dimension_plan(
                question, target_person, available_topics, max_dimensions
            )

        person_hint = f"\n目标人物: {target_person}" if target_person else ""
        topics_hint = ""
        if available_topics:
            topics_preview = ", ".join(available_topics[:30])
            # Changed from restrictive "只能从中选择" to flexible "作参考"
            topics_hint = f"\n话题标签示例（作参考，可推理相关话题）: {topics_preview}"

        prompt = f"""为用户问题生成“证据维度计划”。输出 JSON 对象，包含：
1) question_type: 问题类型（persona_on_topic / decision / comparison / summary / analysis）
2) dimensions: 维度数组，每个维度包含：
   - name: 维度名称
   - intent: 该维度想证明什么
   - topic_seeds: 话题种子（必须来自可用话题标签）
   - keyword_seeds: 关键词种子（简短）
   - semantic_queries: 语义召回查询（短句）
   - counter_queries: 反证召回查询（短句）
   - min_evidence: 最少证据条数

要求：
- 维度数量 <= {max_dimensions}
- topic_seeds 与 keyword_seeds 不超过 8 个
- semantic_queries 与 counter_queries 不超过 4 条
- 输出必须是 JSON，不要其他文字

用户问题: {question}{person_hint}{topics_hint}"""

        try:
            response = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model,
                temperature=0.2,
                max_tokens=600,
            )
            if response:
                response = response.strip()
                start_idx = response.find("{")
                end_idx = response.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    json_str = response[start_idx:end_idx + 1]
                    payload = json.loads(json_str)
                    if isinstance(payload, dict) and payload.get("dimensions"):
                        payload["method"] = "llm"
                        payload["model"] = self.config.model
                        return payload
        except Exception as e:
            print(f"Dimension plan error: {e}")

        return self._fallback_dimension_plan(
            question, target_person, available_topics, max_dimensions
        )

    def _fallback_keyword_extraction(
        self,
        question: str,
        target_person: Optional[str] = None,
        available_topics: Optional[List[str]] = None
    ) -> List[str]:
        """
        Fallback keyword extraction without API.
        
        Uses simple heuristics to extract keywords.
        """
        # Remove common stop words
        stop_words = {
            "的", "了", "是", "在", "我", "你", "他", "她", "它",
            "这", "那", "有", "和", "与", "或", "但", "如果", "因为",
            "所以", "可以", "应该", "需要", "想要", "能够", "不", "没有",
            "吗", "呢", "啊", "吧", "嘛", "呀", "哦", "哈", "嗯",
            "一个", "什么", "怎么", "为什么", "哪里", "谁", "多少",
            "给", "跟", "让", "被", "把", "对", "从", "到", "向"
        }
        
        keywords = []

        # Add target person
        if target_person:
            keywords.append(target_person)

        if "借" in question or "借钱" in question:
            keywords.extend(["工资", "职业", "消费习惯", "资产", "信誉", "评价"])

        # Extract other words from question
        for char_group in question.replace("，", " ").replace("。", " ").replace("？", " ").split():
            if len(char_group) >= 2 and char_group not in stop_words:
                if char_group not in keywords:
                    keywords.append(char_group)
        
        # Add topic-derived hints when available
        if available_topics:
            preferred = [
                "借贷", "金钱", "工资", "职业", "消费习惯", "消费",
                "评价", "个人评价", "人品评价", "人物评价", "资产评价"
            ]
            for item in preferred:
                if item in available_topics and item not in keywords:
                    keywords.append(item)

        # Deduplicate and limit
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        return unique_keywords[:self.config.max_keywords]

    def _fallback_dimension_plan(
        self,
        question: str,
        target_person: Optional[str],
        available_topics: Optional[List[str]],
        max_dimensions: int,
    ) -> Dict[str, Any]:
        question_type = "analysis"
        if any(term in question for term in ("看法", "态度", "评价", "印象", "喜欢", "择偶", "恋爱", "婚姻")):
            question_type = "persona_on_topic"
        elif any(term in question for term in ("对比", "比较", "区别")):
            question_type = "comparison"
        elif any(term in question for term in ("总结", "概括", "回顾")):
            question_type = "summary"

        dims: List[Dict[str, Any]] = []
        if question_type == "persona_on_topic":
            dims = [
                {
                    "name": "经济与阶级线索",
                    "intent": "从收入、工作压力、消费与资产看婚恋现实约束",
                    "topic_seeds": ["工资", "职业", "消费", "房", "车", "资产"],
                    "keyword_seeds": ["工资", "房贷", "消费", "工作强度"],
                    "semantic_queries": ["工资多少", "买房压力", "消费习惯", "经济压力"],
                    "counter_queries": ["经济宽裕", "不在乎钱", "消费自由"],
                    "min_evidence": 4,
                },
                {
                    "name": "恋爱史与择偶偏好",
                    "intent": "通过恋爱经历与择偶标准还原偏好",
                    "topic_seeds": ["恋爱", "相亲", "对象", "分手", "结婚"],
                    "keyword_seeds": ["前任", "分手", "择偶", "喜欢"],
                    "semantic_queries": ["分手原因", "喜欢什么样的女生", "谈恋爱看重什么"],
                    "counter_queries": ["不想谈", "不婚", "单身"],
                    "min_evidence": 4,
                },
                {
                    "name": "性别议题态度",
                    "intent": "观察对女权、彩礼、婚姻分工的价值观",
                    "topic_seeds": ["女权", "彩礼", "AA", "婚姻", "男女"],
                    "keyword_seeds": ["女权", "彩礼", "AA", "婚后分工"],
                    "semantic_queries": ["女权怎么看", "彩礼合理吗", "AA制"],
                    "counter_queries": ["支持女权", "尊重女性", "反对刻板印象"],
                    "min_evidence": 6,
                },
                {
                    "name": "语言与潜台词",
                    "intent": "从称呼与玩笑判断尊重程度或刻板印象",
                    "topic_seeds": ["称呼", "评价", "玩笑", "女生", "性格"],
                    "keyword_seeds": ["绿茶", "捞女", "颜值", "独立", "作"],
                    "semantic_queries": ["评价女生", "身材颜值", "独立 vs 作"],
                    "counter_queries": ["尊重", "平等", "理解女性"],
                    "min_evidence": 6,
                },
            ]
        elif self._is_borrow_question(question):
            dims = [
                {
                    "name": "收入与职业稳定",
                    "intent": "收入与职业信息支撑信用与还款能力判断",
                    "topic_seeds": ["工资", "职业", "收入", "工作"],
                    "keyword_seeds": ["工资", "月薪", "年终"],
                    "semantic_queries": ["收入情况", "工作稳定", "工资发放"],
                    "counter_queries": ["收入不稳定", "没工作", "拖欠工资"],
                    "min_evidence": 4,
                },
                {
                    "name": "消费与资产状况",
                    "intent": "消费习惯与资产线索判断资金压力",
                    "topic_seeds": ["消费", "资产", "房", "车"],
                    "keyword_seeds": ["买房", "房贷", "消费", "信用卡"],
                    "semantic_queries": ["消费习惯", "资产情况", "资金压力"],
                    "counter_queries": ["节省", "有积蓄", "资产充足"],
                    "min_evidence": 3,
                },
                {
                    "name": "借还记录与信誉",
                    "intent": "历史借还行为体现信誉与还款意愿",
                    "topic_seeds": ["借贷", "金钱", "还钱", "欠款"],
                    "keyword_seeds": ["借钱", "还钱", "欠款", "催"],
                    "semantic_queries": ["借钱经历", "还款时间", "信誉评价"],
                    "counter_queries": ["按时还", "守信用", "已还清"],
                    "min_evidence": 4,
                },
            ]
        else:
            dims = [
                {
                    "name": "事实与事件",
                    "intent": "找出与问题相关的关键事实与事件线索",
                    "topic_seeds": self._extract_terms(question)[:6],
                    "keyword_seeds": self._fallback_keyword_extraction(
                        question, target_person, available_topics
                    )[:6],
                    "semantic_queries": [question],
                    "counter_queries": [f"与{question}相反的说法"],
                    "min_evidence": 3,
                },
                {
                    "name": "观点与态度",
                    "intent": "观察相关观点、评价或价值判断",
                    "topic_seeds": ["观点", "看法", "评价", "态度"],
                    "keyword_seeds": ["认为", "觉得", "态度"],
                    "semantic_queries": [f"{question} 的看法"],
                    "counter_queries": [f"不同意见 关于 {question}"],
                    "min_evidence": 3,
                },
                {
                    "name": "行为与决策",
                    "intent": "从行为或选择中推断倾向",
                    "topic_seeds": ["行为", "选择", "决定"],
                    "keyword_seeds": ["做法", "选择", "决定"],
                    "semantic_queries": [f"{question} 的行为"],
                    "counter_queries": [f"与{question}相反的行为"],
                    "min_evidence": 3,
                },
            ]

        cleaned_dims: List[Dict[str, Any]] = []
        allowed_topics = [t.strip() for t in (available_topics or []) if t.strip()]
        for dim in dims[:max_dimensions]:
            topic_seeds = dim.get("topic_seeds", [])
            if allowed_topics and topic_seeds:
                filtered = []
                for seed in topic_seeds:
                    for topic in allowed_topics:
                        if seed and seed in topic and topic not in filtered:
                            filtered.append(topic)
                dim["topic_seeds"] = filtered[:8]
            cleaned_dims.append(dim)

        return {
            "question_type": question_type,
            "dimensions": cleaned_dims,
            "method": "rule_based",
            "model": None,
        }

    def _fallback_metadata_classification(
        self,
        question: str,
        available_topics: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Fallback metadata classification without API.
        """
        topics = []
        if "借" in question or "借钱" in question:
            topics.append("借贷")
        if "问" in question or "询问" in question:
            topics.append("询问")

        return self._normalize_metadata({
            "topics": topics,
            "sentiment": "neutral",
            "facts": {},
            "information_density": "low",
        }, available_topics)

    def _normalize_metadata(
        self,
        metadata: Dict[str, Any],
        available_topics: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Normalize metadata fields for consistent downstream use.
        """
        topics = metadata.get("topics", []) or []
        if isinstance(topics, str):
            topics = [topics]
        topics = [t.strip() for t in topics if isinstance(t, str) and t.strip()]
        if available_topics:
            allowed = {t.strip() for t in available_topics if t.strip()}
            topics = [t for t in topics if t in allowed]

        facts = metadata.get("facts", {}) or {}
        if not isinstance(facts, dict):
            facts = {}

        sentiment = metadata.get("sentiment", "neutral") or "neutral"
        info_density = metadata.get("information_density", "low") or "low"

        return {
            "topics": topics,
            "sentiment": sentiment,
            "facts": facts,
            "information_density": info_density,
        }

    def _is_borrow_question(self, question: str) -> bool:
        """Detect borrow/credit-related questions for topic biasing."""
        triggers = ("借", "借钱", "借款", "还款", "还钱", "欠钱", "信用", "信誉", "信任")
        return any(t in question for t in triggers)

    def _inject_borrow_topics(
        self,
        topics: List[str],
        available_topics: Optional[List[str]] = None
    ) -> List[str]:
        """Ensure borrow-related topic coverage when available."""
        if not available_topics:
            return topics

        topic_set = set(topics)
        available_set = {t.strip() for t in available_topics if t.strip()}
        desired = [
            "借贷",
            "金钱",
            "工资",
            "职业",
            "消费习惯",
            "消费",
            "评价",
            "个人评价",
            "人品评价",
            "人物评价",
            "资产评价",
        ]
        for item in desired:
            if item in available_set and item not in topic_set:
                topics.append(item)
                topic_set.add(item)
        return topics

    def _ensure_topic_coverage(
        self,
        question: str,
        target_person: Optional[str],
        keywords: List[str],
        topics: List[str],
        available_topics: Optional[List[str]]
    ) -> List[str]:
        """Ensure topics stay within available topics and meet size targets."""
        if not available_topics:
            return topics[: self.config.max_topics]

        allowed = [t.strip() for t in available_topics if t.strip()]
        topic_list: List[str] = []
        for item in topics:
            if item in allowed and item not in topic_list:
                topic_list.append(item)

        if target_person and target_person in allowed and target_person not in topic_list:
            topic_list.insert(0, target_person)

        terms: List[str] = []
        for item in keywords:
            if item and item not in terms:
                terms.append(item)
        terms.extend(self._extract_terms(question))

        for term in terms:
            if len(topic_list) >= self.config.max_topics:
                break
            term_lower = term.lower()
            for topic in allowed:
                if len(topic_list) >= self.config.max_topics:
                    break
                if topic in topic_list:
                    continue
                if term_lower and term_lower in topic.lower():
                    topic_list.append(topic)

        min_count = min(self.config.min_topics, len(allowed))
        if len(topic_list) < min_count:
            for topic in allowed:
                if len(topic_list) >= min_count:
                    break
                if topic not in topic_list:
                    topic_list.append(topic)

        return topic_list[: self.config.max_topics]

    def _extract_terms(self, question: str) -> List[str]:
        """Extract simple CJK terms for topic matching."""
        import re

        terms = re.findall(r"[\u4e00-\u9fff]{2,}", question)
        unique_terms: List[str] = []
        for term in terms:
            if term not in unique_terms:
                unique_terms.append(term)
        return unique_terms
    

    async def entity_attribution(
        self,
        formatted_text: str,
        target_person: str,
        question: str
    ) -> tuple[str, dict]:
        """
        Two-stage Chain-of-Thought entity attribution.
        
        Stage 1: Analyze each message to determine who is being discussed
        Stage 2: Filter to keep only messages about the target person
        
        This is a UNIVERSAL method that works for any query type.
        
        Args:
            formatted_text: Raw chat messages
            target_person: The person we want information about
            question: Original user question for context
            
        Returns:
            Tuple of (filtered_text, attribution_stats)
        """
        client = self._get_poe_client()
        
        if client is None or not client.is_configured:
            return formatted_text, {"skipped": True, "reason": "no_api"}
        
        if not target_person:
            return formatted_text, {"skipped": True, "reason": "no_target_person"}
        
        # Stage 1: Entity Attribution Analysis (CoT reasoning)
        stage1_prompt = f"""【任务】实体归因分析

你需要分析以下聊天记录，判断每条消息讨论的是哪个人物。

目标人物：{target_person}
用户问题：{question}

【分析规则】
1. 对于每条消息，判断其讨论的主体是谁
2. 注意代词"他/她/你/我"的指代对象
3. 数字（工资、年龄、金额）属于哪个人
4. 职业、习惯、评价描述的是谁

【输出格式】
对每条消息输出一行，格式：
<行号>|<讨论主体>|<保留/排除>|<原因>

示例：
1|{target_person}|保留|直接描述目标人物的工资
2|高峰|排除|讨论的是高峰的职业而非{target_person}
3|{target_person}|保留|目标人物自述消费习惯
4|不确定|排除|代词指代不明确

聊天记录：
{formatted_text[:4000]}

直接输出分析结果（每行一条）："""

        try:
            stage1_response = await client.chat(
                messages=[{"role": "user", "content": stage1_prompt}],
                model=self.config.model,
                temperature=0.1,
                max_tokens=2000
            )
            
            if not stage1_response:
                return formatted_text, {"skipped": True, "reason": "stage1_empty"}
            
            # Parse Stage 1 results
            keep_lines = set()
            exclude_lines = set()
            attribution_details = []
            
            for line in stage1_response.strip().split('\n'):
                line = line.strip()
                if not line or '|' not in line:
                    continue
                parts = line.split('|')
                if len(parts) >= 3:
                    try:
                        line_num = int(re.sub(r'[^0-9]', '', parts[0]))
                        subject = parts[1].strip()
                        action = parts[2].strip()
                        reason = parts[3].strip() if len(parts) > 3 else ""
                        
                        if '保留' in action or 'keep' in action.lower():
                            keep_lines.add(line_num)
                        else:
                            exclude_lines.add(line_num)
                        
                        attribution_details.append({
                            "line": line_num,
                            "subject": subject,
                            "action": action,
                            "reason": reason
                        })
                    except (ValueError, IndexError):
                        continue
            
            # Stage 2: Filter the original text
            if not keep_lines:
                # If no lines to keep, return original (fallback)
                return formatted_text, {
                    "skipped": False,
                    "stage1_parsed": len(attribution_details),
                    "keep_count": 0,
                    "exclude_count": len(exclude_lines),
                    "fallback": True
                }
            
            # Filter messages
            original_lines = formatted_text.split('\n')
            filtered_lines = []
            message_line_num = 0
            
            for line in original_lines:
                # Check if this is a message line (has timestamp pattern)
                if re.match(r'.*\[\d{4}-\d{2}-\d{2}.*\].*', line) or re.match(r'.*\[\d{2}:\d{2}.*\].*', line):
                    message_line_num += 1
                    if message_line_num in keep_lines:
                        filtered_lines.append(line)
                elif line.strip() == '---' or line.startswith('##') or line.startswith('**'):
                    # Keep separators and headers
                    filtered_lines.append(line)
                elif filtered_lines and not re.match(r'.*\[.*\].*', line):
                    # Keep continuation lines if previous message was kept
                    filtered_lines.append(line)
            
            filtered_text = '\n'.join(filtered_lines)
            
            stats = {
                "skipped": False,
                "stage1_parsed": len(attribution_details),
                "keep_count": len(keep_lines),
                "exclude_count": len(exclude_lines),
                "original_chars": len(formatted_text),
                "filtered_chars": len(filtered_text)
            }
            
            return filtered_text if filtered_text.strip() else formatted_text, stats
            
        except Exception as e:
            print(f"Entity attribution error: {e}")
            return formatted_text, {"skipped": True, "reason": str(e)}

    async def clean_results(
        self,
        formatted_text: str,
        question: str,
        target_person: Optional[str] = None,
        force: bool = False
    ) -> str:
        """
        Clean/compress search results if too large.
        
        Args:
            formatted_text: Raw formatted search results
            question: Original user question
            target_person: Optional target person
            
        Returns:
            Cleaned/compressed text
        """
        # Stage 0: Entity attribution if target person specified
        if target_person:
            formatted_text, attr_stats = await self.entity_attribution(
                formatted_text, target_person, question
            )
            if not attr_stats.get("skipped"):
                print(f"[ENTITY ATTRIBUTION] ✓ 保留 {attr_stats.get('keep_count', 0)} 条 | 排除 {attr_stats.get('exclude_count', 0)} 条")
        
        # Check if cleaning needed
        if not force and len(formatted_text) <= self.config.char_threshold:
            return formatted_text
        
        client = self._get_poe_client()
        
        if client is None or not client.is_configured:
            # Fallback: just truncate
            return self._truncate_text(formatted_text)
        
        person_hint = f"关于「{target_person}」" if target_person else ""
        
        prompt = f"""你是一个聊天记录筛选助手。请从以下聊天记录中筛选出与问题最相关的**原始对话片段**。

用户问题: {question}
{person_hint}

【重要规则】：
1. 必须输出**原始的聊天记录格式**，保持 "[时间戳] 发送者: 内容" 的格式
2. 不要写分析、不要写总结、不要写评论，只输出筛选后的原始对话
3. 保留能体现人物性格、消费习惯、工作、财务状况的对话
4. 如果没有直接相关内容，选择最能侧面反映相关信息的对话
5. 保持对话上下文连贯（不要单独抽取一句话）
6. 用 "---" 分隔不同时间段的对话片段
7. 输出控制在{self.config.target_chars}字以内
7.1 如果存在“命中窗口”标题，必须保留该窗口内的所有行，不要删减上下文

【实体识别规则 - 非常重要】：
8. 如果指定了目标人物，必须判断每条消息讨论的是谁
9. 当消息提到工资、职业、消费等信息时，必须确认这是在描述目标人物本人
10. 如果上下文显示是在讨论其他人，则排除这些消息
11. 模糊指代（"他"/"她"/"那个人"）需要结合上下文判断，不确定时排除
12. 示例：如果目标是"冯天奇"，但对话在讨论"高峰"的工资，则不应包含

聊天记录：
{formatted_text}

直接输出筛选后的聊天记录（保持原格式）："""

        try:
            response = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model,
                temperature=0.2,
                max_tokens=self.config.target_chars + 500
            )
            
            if response and len(response.strip()) > 50:
                return response.strip()
        
        except Exception as e:
            print(f"Result cleaning error: {e}")
        
        # Fallback
        return self._truncate_text(formatted_text)
    
    def _truncate_text(self, text: str) -> str:
        """Simple truncation fallback."""
        if len(text) <= self.config.target_chars:
            return text
        
        # Try to truncate at a line break
        truncated = text[:self.config.target_chars]
        last_newline = truncated.rfind('\n')
        
        if last_newline > self.config.target_chars * 0.7:
            truncated = truncated[:last_newline]
        
        return truncated + "\n\n... (内容过多，已截断)"
    
    async def extract_highlights(
        self,
        formatted_text: str,
        question: str,
        target_person: Optional[str] = None
    ) -> str:
        """
        Extract and highlight key parts related to question, even for small data.
        
        Args:
            formatted_text: The formatted search results
            question: Original user question
            target_person: Optional target person
            
        Returns:
            Text with key parts highlighted using ⭐ markers
        """
        client = self._get_poe_client()
        
        if client is None or not client.is_configured:
            # Fallback: return original text
            return formatted_text
        
        person_hint = f"关于「{target_person}」" if target_person else ""
        
        prompt = f"""从以下对话记录中找出与问题最相关的关键句子。
在每个关键对话行前面加上 "⭐ " 标记。保持原始时间戳格式不变。

用户问题: {question}
{person_hint}

【规则】:
1. 只添加⭐标记，不要删除或修改任何原始内容
2. 标记能够体现：性格、消费习惯、工作、财务状况、信用相关的对话
3. 最多标记10个关键行
4. 保持对话的时间戳和格式完整

对话记录:
{formatted_text}

直接输出标注后的完整对话记录："""

        try:
            response = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model,
                temperature=0.2,
                max_tokens=len(formatted_text) + 500
            )
            
            if response and len(response.strip()) > 50:
                return response.strip()
        
        except Exception as e:
            print(f"Highlight extraction error: {e}")
        
        # Fallback
        return formatted_text
    
    async def compress_messages(
        self,
        messages: List[Dict[str, Any]],
        question: str,
        target_person: Optional[str] = None,
        max_output_messages: int = 30,
        compression_ratio: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        Intelligently compress messages using small model.
        
        Instead of simple truncation, this method:
        1. Groups similar/repetitive messages
        2. Extracts key points from verbose messages
        3. Preserves high-value evidence while compressing low-value content
        
        This allows returning MORE effective messages within the same token budget.
        
        Args:
            messages: List of message dicts with line, time, sender, content, snippet
            question: User question for relevance scoring
            target_person: Target person for filtering
            max_output_messages: Maximum messages to return
            compression_ratio: Target compression (0.5 = 50% of original size)
            
        Returns:
            Compressed message list with added 'compressed' and 'relevance' fields
        """
        if not messages:
            return []
        
        client = self._get_poe_client()
        
        if client is None or not client.is_configured:
            # Fallback: return top N messages as-is
            return messages[:max_output_messages]
        
        # Step 1: Score each message for relevance using small model
        scored_messages = []
        batch_size = 20
        
        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            batch_text = "\n".join([
                f"[{idx + i}] {m.get('sender', '?')}: {m.get('content', '')[:200]}"
                for idx, m in enumerate(batch)
            ])
            
            person_hint = f"关于「{target_person}」" if target_person else ""
            
            score_prompt = f"""为以下消息评估与问题的相关性（0-10分）。
问题: {question}
{person_hint}

【评分规则】:
- 10分: 直接回答问题的关键证据
- 7-9分: 相关性格/习惯/态度的一手证据
- 4-6分: 间接相关，可提供背景
- 1-3分: 弱相关
- 0分: 完全无关或讨论其他人

消息:
{batch_text}

输出格式（每行一个）:
[编号] 分数 原因简述

只输出评分结果:"""

            try:
                response = await client.chat(
                    messages=[{"role": "user", "content": score_prompt}],
                    model=self.config.model,
                    temperature=0.1,
                    max_tokens=500,
                )
                
                if response:
                    for line in response.strip().split('\n'):
                        match = re.match(r'\[(\d+)\]\s*(\d+)', line)
                        if match:
                            idx = int(match.group(1))
                            score = int(match.group(2))
                            if 0 <= idx < len(batch):
                                batch[idx]['relevance'] = min(10, max(0, score))
            except Exception as e:
                print(f"Message scoring error: {e}")
            
            for m in batch:
                if 'relevance' not in m:
                    m['relevance'] = 5  # Default middle score
                scored_messages.append(m)
        
        # Step 2: Sort by relevance and select top messages
        scored_messages.sort(key=lambda m: m.get('relevance', 0), reverse=True)
        selected = scored_messages[:max_output_messages]
        
        # Step 3: Compress verbose messages (those with long content)
        for m in selected:
            content = m.get('content', '')
            if len(content) > 200 and m.get('relevance', 0) < 8:
                # Compress low-relevance verbose messages
                compressed = await self._compress_single_message(
                    content, 
                    question, 
                    target_person,
                    max_chars=int(len(content) * compression_ratio)
                )
                m['original_content'] = content
                m['content'] = compressed
                m['compressed'] = True
            else:
                m['compressed'] = False
        
        # Sort back by time for coherent reading
        selected.sort(key=lambda m: m.get('time', ''))
        
        return selected
    
    async def _compress_single_message(
        self, 
        content: str, 
        question: str,
        target_person: Optional[str],
        max_chars: int = 100
    ) -> str:
        """Compress a single verbose message to key points."""
        client = self._get_poe_client()
        
        if client is None or not client.is_configured:
            return content[:max_chars] + "…"
        
        person_hint = f"（关于{target_person}）" if target_person else ""
        
        prompt = f"""将以下消息压缩到{max_chars}字以内，保留与问题相关的关键信息{person_hint}。
问题: {question}

原消息: {content}

压缩后（直接输出，不要解释）:"""

        try:
            response = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.model,
                temperature=0.1,
                max_tokens=max_chars + 50,
            )
            
            if response and len(response.strip()) > 10:
                return response.strip()[:max_chars]
        except Exception as e:
            print(f"Single message compression error: {e}")
        
        return content[:max_chars] + "…"
    
    async def generate_evidence_matrix(
        self,
        dimension_evidence: List[Dict[str, Any]],
        question: str,
        target_person: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate structured evidence matrix from dimension evidence.
        
        This is Step 4 from re.md - produces structured analysis output:
        - Per-dimension conclusion
        - Evidence list with snippets
        - Reasoning chain
        - Counter-evidence / gaps
        - Confidence score
        
        Args:
            dimension_evidence: List of dimension outputs from retrieve_evidence
            question: Original user question
            target_person: Target person
            
        Returns:
            Structured evidence matrix dict
        """
        client = self._get_poe_client()
        
        if client is None or not client.is_configured:
            # Fallback: return simple structure
            return self._fallback_evidence_matrix(dimension_evidence, question, target_person)
        
        # Prepare evidence text for analysis
        evidence_text = ""
        for dim in dimension_evidence:
            name = dim.get('name', '未命名')
            evidence_list = dim.get('evidence', [])
            counter_list = dim.get('counter_evidence', [])
            
            evidence_text += f"\n## 维度: {name}\n"
            evidence_text += f"意图: {dim.get('intent', '')}\n"
            evidence_text += "证据:\n"
            for e in evidence_list[:5]:
                evidence_text += f"- [{e.get('line')}] {e.get('sender', '?')}: {e.get('snippet', '')}\n"
            
            if counter_list:
                evidence_text += "反证:\n"
                for c in counter_list[:3]:
                    evidence_text += f"- [{c.get('line')}] {c.get('snippet', '')}\n"
        
        person_hint = f"目标人物: {target_person}\n" if target_person else ""
        
        matrix_prompt = f"""基于以下证据，为每个维度生成「证据矩阵」分析。

问题: {question}
{person_hint}
{evidence_text}

输出 JSON 格式:
{{
  "dimensions": [
    {{
      "name": "维度名称",
      "conclusion": "1-2句结论",
      "key_evidence": [
        {{"line": 行号, "snippet": "关键片段", "weight": "高/中/低"}}
      ],
      "reasoning_chain": "证据如何支持结论的推理链",
      "counter_evidence": [{{"snippet": "反例", "note": "为何不动摇结论"}}],
      "gaps": ["缺失的关键信息"],
      "confidence": "高/中/低"
    }}
  ],
  "overall_conclusion": "综合结论",
  "evidence_quality": "证据质量评估"
}}

只输出 JSON:"""

        try:
            response = await client.chat(
                messages=[{"role": "user", "content": matrix_prompt}],
                model=self.config.model,
                temperature=0.2,
                max_tokens=1500,
            )
            
            if response:
                response = response.strip()
                start_idx = response.find('{')
                end_idx = response.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_str = response[start_idx:end_idx + 1]
                    matrix = json.loads(json_str)
                    if isinstance(matrix, dict):
                        matrix['method'] = 'llm'
                        matrix['model'] = self.config.model
                        return matrix
        except Exception as e:
            print(f"Evidence matrix generation error: {e}")
        
        return self._fallback_evidence_matrix(dimension_evidence, question, target_person)
    
    def _fallback_evidence_matrix(
        self,
        dimension_evidence: List[Dict[str, Any]],
        question: str,
        target_person: Optional[str],
    ) -> Dict[str, Any]:
        """Fallback evidence matrix without LLM."""
        dimensions = []
        for dim in dimension_evidence:
            evidence = dim.get('evidence', [])[:3]
            counter = dim.get('counter_evidence', [])
            
            dimensions.append({
                "name": dim.get('name', '未命名'),
                "conclusion": f"基于 {len(evidence)} 条证据",
                "key_evidence": [
                    {"line": e.get('line'), "snippet": e.get('snippet', ''), "weight": "中"}
                    for e in evidence
                ],
                "reasoning_chain": "需要 LLM 分析",
                "counter_evidence": [
                    {"snippet": c.get('snippet', ''), "note": "待分析"}
                    for c in counter[:2]
                ],
                "gaps": dim.get('gaps', []),
                "confidence": "中" if evidence else "低",
            })
        
        return {
            "dimensions": dimensions,
            "overall_conclusion": f"关于「{question}」的多维度分析",
            "evidence_quality": "rule_based",
            "method": "rule_based",
            "model": None,
        }
    
    async def close(self):
        """Close the Poe client."""
        if self._poe_client:
            await self._poe_client.close()


# Synchronous wrapper for non-async contexts
def expand_keywords_sync(
    question: str,
    target_person: Optional[str] = None,
    config: Optional[CleanerConfig] = None
) -> List[str]:
    """Synchronous wrapper for keyword expansion."""
    cleaner = ChatlogCleaner(config)
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        return loop.run_until_complete(
            cleaner.expand_keywords(question, target_person)
        )
    finally:
        loop.run_until_complete(cleaner.close())


def clean_results_sync(
    formatted_text: str,
    question: str,
    target_person: Optional[str] = None,
    config: Optional[CleanerConfig] = None,
    force: bool = False
) -> str:
    """Synchronous wrapper for result cleaning."""
    cleaner = ChatlogCleaner(config)
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        return loop.run_until_complete(
            cleaner.clean_results(
                formatted_text,
                question,
                target_person,
                force=force
            )
        )
    finally:
        loop.run_until_complete(cleaner.close())

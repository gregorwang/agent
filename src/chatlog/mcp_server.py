"""
Chatlog MCP Server for BENEDICTJUN Agent

Provides MCP tools for intelligent chatlog retrieval:
- get_chatlog_stats: Get statistics about loaded chatlog
- search_person: Search messages from a specific person
- atomic tools for topic/keyword/semantic retrieval
"""

import os
import re
import json
import time
import uuid
import asyncio
from typing import Optional, Dict, Any, List, Tuple

from claude_agent_sdk import tool, create_sdk_mcp_server

from .loader import ChatlogLoader, get_chatlog_loader
from .searcher import ChatlogSearcher, SearchResult
from .cleaner import ChatlogCleaner, CleanerConfig
from .metadata_index_loader import MetadataIndexLoader, get_index_loader
from .semantic_index import get_semantic_index


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Tool Definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Global instances
_chatlog_loader: Optional[ChatlogLoader] = None
_chatlog_searcher: Optional[ChatlogSearcher] = None
_chatlog_cleaner: Optional[ChatlogCleaner] = None

_CHATLOG_MAX_RETURN_CHARS = int(os.getenv("CHATLOG_MAX_RETURN_CHARS", "6000"))  # 提升：有压缩可以返回更多
_CHATLOG_INDEX_MAX_RESULTS = int(os.getenv("CHATLOG_INDEX_MAX_RESULTS", "200"))
_CHATLOG_INDEX_CONTEXT_BEFORE = int(os.getenv("CHATLOG_INDEX_CONTEXT_BEFORE", "2"))
_CHATLOG_INDEX_CONTEXT_AFTER = int(os.getenv("CHATLOG_INDEX_CONTEXT_AFTER", "2"))
_CHATLOG_MAX_MESSAGES = int(os.getenv("CHATLOG_MAX_MESSAGES", "200"))
_CHATLOG_MAX_CONTENT_CHARS = int(os.getenv("CHATLOG_MAX_CONTENT_CHARS", "500"))
_CHATLOG_MAX_TOOL_CHARS = int(os.getenv("CHATLOG_MAX_TOOL_CHARS", "15000"))  # 提升：工具返回上限
_CHATLOG_MAX_LIST_ITEMS = int(os.getenv("CHATLOG_MAX_LIST_ITEMS", "80"))  # 提升：列表项上限
_CHATLOG_MAX_EVIDENCE_MESSAGES = int(os.getenv("CHATLOG_MAX_EVIDENCE_MESSAGES", "80"))  # 提升：40→80
_CHATLOG_MAX_EVIDENCE_PER_DIM = int(os.getenv("CHATLOG_MAX_EVIDENCE_PER_DIM", "25"))  # 提升：10→25
_CHATLOG_EVIDENCE_SNIPPET_CHARS = int(os.getenv("CHATLOG_EVIDENCE_SNIPPET_CHARS", "150"))  # 稍微放宽
_CHATLOG_EVIDENCE_CACHE_SIZE = int(os.getenv("CHATLOG_EVIDENCE_CACHE_SIZE", "20"))
_CHATLOG_LOAD_CONTEXT_BEFORE = int(os.getenv("CHATLOG_LOAD_CONTEXT_BEFORE", "2"))  # 提升：上下文
_CHATLOG_LOAD_CONTEXT_AFTER = int(os.getenv("CHATLOG_LOAD_CONTEXT_AFTER", "2"))  # 提升：上下文
_CHATLOG_LOAD_MAX_MESSAGES = int(os.getenv("CHATLOG_LOAD_MAX_MESSAGES", "60"))  # 提升：20→60
_CHATLOG_SNIPPET_CHARS = int(os.getenv("CHATLOG_SNIPPET_CHARS", "150"))  # 稍微放宽

_EVIDENCE_STORE: Dict[str, Dict[str, Any]] = {}
_EVIDENCE_STORE_ORDER: List[str] = []


def _cap_text(text: str, max_chars: int) -> str:
    """Cap tool output to prevent context overflow."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...(已截断)"

def _approx_tokens(chars: int) -> int:
    if chars <= 0:
        return 0
    return max(1, int(chars / 3.6))

def _log_tool_payload(tool_name: str, payload: Dict[str, Any], chars: int) -> None:
    """Log tool result with token estimation and alert for large payloads."""
    approx_tokens = _approx_tokens(chars)
    threshold_chars = int(os.getenv("CHATLOG_TOOL_ALERT_CHARS", "12000"))
    
    # Extract field sizes
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    key_sizes: Dict[str, int] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                key_sizes[k] = len(json.dumps(v, ensure_ascii=False))
            except (TypeError, ValueError):
                key_sizes[k] = 0
    
    largest_key = max(key_sizes.items(), key=lambda x: x[1], default=("", 0))
    
    if chars > threshold_chars:
        print(f"[TOOL ALERT] ⚠️ {tool_name}: {chars} chars (~{approx_tokens} tokens) OVER THRESHOLD")
        if largest_key[0]:
            print(f"  └─ Largest field: '{largest_key[0]}' = {largest_key[1]} chars")
        print(f"  └─ Fields: {list(key_sizes.keys())}")
    else:
        print(f"[TOOL] {tool_name}: {chars} chars (~{approx_tokens} tokens)")

def _truncate_list(items: List[Any], limit: int, cursor_prefix: str) -> Tuple[List[Any], int, Optional[str]]:
    if limit <= 0:
        return [], len(items), f"{cursor_prefix}#offset=0"
    if len(items) <= limit:
        return items, 0, None
    omitted = len(items) - limit
    next_cursor = f"{cursor_prefix}#offset={limit}"
    return items[:limit], omitted, next_cursor

def _build_snippet(text: str, max_chars: int) -> str:
    if not isinstance(text, str):
        return ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"

# Slim data limits for preventing token explosion
_SLIM_MAX_LIST = int(os.getenv("CHATLOG_SLIM_MAX_LIST", "50"))
_SLIM_MAX_SNIPPET = int(os.getenv("CHATLOG_SLIM_MAX_SNIPPET", "200"))

def _slim_data(data: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    """
    Recursively slim down data structure to prevent token explosion.
    
    - Lists: truncated to _SLIM_MAX_LIST items with omitted_count
    - Long strings: truncated to _SLIM_MAX_SNIPPET chars
    - Nested dicts: recursively processed
    """
    if depth > 5:  # Prevent infinite recursion
        return data
    
    slimmed: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, list):
            limited, omitted, cursor = _truncate_list(
                value, _SLIM_MAX_LIST, f"field:{key}"
            )
            # Slim each item if it's a dict
            slimmed_list = []
            for item in limited:
                if isinstance(item, dict):
                    slimmed_list.append(_slim_data(item, depth + 1))
                elif isinstance(item, str) and len(item) > _SLIM_MAX_SNIPPET:
                    slimmed_list.append(_build_snippet(item, _SLIM_MAX_SNIPPET))
                else:
                    slimmed_list.append(item)
            slimmed[key] = slimmed_list
            if omitted > 0:
                slimmed[f"_{key}_omitted"] = omitted
                slimmed[f"_{key}_cursor"] = cursor
        elif isinstance(value, str) and len(value) > _SLIM_MAX_SNIPPET:
            slimmed[key] = _build_snippet(value, _SLIM_MAX_SNIPPET)
        elif isinstance(value, dict):
            slimmed[key] = _slim_data(value, depth + 1)
        else:
            slimmed[key] = value
    return slimmed


def _store_evidence(payload: Dict[str, Any]) -> str:
    evidence_id = f"evi_{uuid.uuid4().hex[:12]}"
    _EVIDENCE_STORE[evidence_id] = payload
    _EVIDENCE_STORE_ORDER.append(evidence_id)
    if len(_EVIDENCE_STORE_ORDER) > _CHATLOG_EVIDENCE_CACHE_SIZE:
        expired = _EVIDENCE_STORE_ORDER.pop(0)
        _EVIDENCE_STORE.pop(expired, None)
    return evidence_id

def _get_evidence(evidence_id: str) -> Optional[Dict[str, Any]]:
    if not evidence_id:
        return None
    return _EVIDENCE_STORE.get(evidence_id)

def _build_response(
    ok: bool,
    data: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    is_error: bool = False,
    tool_name: str = "unknown",
    slim: bool = True,
) -> Dict[str, Any]:
    """Build standardized tool response with automatic data slimming."""
    meta = meta or {}
    meta.setdefault("tool", tool_name)
    
    # Apply data slimming before serialization to prevent token explosion
    if slim and isinstance(data, dict):
        data = _slim_data(data)
    
    payload = {
        "ok": ok,
        "data": data,
        "meta": meta
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    _log_tool_payload(tool_name, payload, len(text))
    if len(text) > _CHATLOG_MAX_TOOL_CHARS:
        meta["truncated"] = True
        meta["max_chars"] = _CHATLOG_MAX_TOOL_CHARS
        payload["meta"] = meta
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        text = _cap_text(text, _CHATLOG_MAX_TOOL_CHARS)
    return {
        "content": [{"type": "text", "text": text}],
        **({"is_error": True} if is_error else {})
    }


def _success(
    data: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    tool_name: str = "unknown"
) -> Dict[str, Any]:
    return _build_response(True, data, meta=meta, is_error=False, tool_name=tool_name)


def _error(
    message: str,
    meta: Optional[Dict[str, Any]] = None,
    tool_name: str = "unknown"
) -> Dict[str, Any]:
    payload = {"error": message}
    return _build_response(False, payload, meta=meta, is_error=True, tool_name=tool_name)


def _parse_sender_content(content: str) -> Tuple[str, str]:
    if ": " in content:
        sender, body = content.split(": ", 1)
        return sender, body
    return "", content


def _extract_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract structured payload from a tool result."""
    if not result or "content" not in result or not result["content"]:
        return {}
    text = result["content"][0].get("text", "")
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {"data": payload}


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: List[str] = []
        for item in value:
            if isinstance(item, str) and "," in item:
                items.extend([p.strip() for p in item.replace("，", ",").split(",") if p.strip()])
            elif isinstance(item, str):
                items.append(item.strip())
            else:
                items.append(str(item))
        return [i for i in items if i]
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("，", ",").split(",")]
        return [p for p in parts if p]
    return [str(value)]


def _coerce_int_list(value: Any) -> List[int]:
    raw_items = _coerce_list(value)
    cleaned: List[int] = []
    for item in raw_items:
        try:
            cleaned.append(int(item))
        except (TypeError, ValueError):
            continue
    return cleaned


def _infer_task_type(question: str) -> str:
    """Infer a high-level task type from the question."""
    if not question:
        return "analysis"
    q = question.lower()
    decision_cues = ("该不该", "要不要", "是否应该", "能不能", "值得不", "should i", "should we")
    compare_cues = ("对比", "比较", "哪个", "更好", "区别", "difference")
    cause_cues = ("为什么", "原因", "导致", "因为", "why")
    plan_cues = ("什么时候", "时间", "安排", "计划", "日程", "when")
    summary_cues = ("总结", "概括", "回顾", "梳理", "总结一下", "summarize", "summary")
    retrieval_cues = ("有没有", "找", "查找", "搜索", "哪里", "look up", "find")

    if any(cue in q for cue in decision_cues):
        return "decision"
    if any(cue in q for cue in compare_cues):
        return "comparison"
    if any(cue in q for cue in cause_cues):
        return "attribution"
    if any(cue in q for cue in plan_cues):
        return "planning"
    if any(cue in q for cue in summary_cues):
        return "summary"
    if any(cue in q for cue in retrieval_cues):
        return "retrieval"
    return "analysis"


def _task_sub_questions(task_type: str) -> List[str]:
    if task_type == "decision":
        return [
            "相关历史事件与证据有哪些？",
            "正向/负向信号各是什么？",
            "关键信息缺口或不确定性是什么？",
        ]
    if task_type == "comparison":
        return [
            "对比对象的关键差异是什么？",
            "有哪些直接证据支持差异？",
            "需要补充哪些信息？",
        ]
    if task_type == "attribution":
        return [
            "相关事件链条是什么？",
            "可能的原因或触发因素有哪些？",
            "哪些证据支持或反驳？",
        ]
    if task_type == "planning":
        return [
            "历史承诺或时间点是什么？",
            "可行的安排窗口是什么？",
            "潜在冲突或风险是什么？",
        ]
    if task_type == "summary":
        return [
            "关键事件与人物有哪些？",
            "主要变化或转折是什么？",
            "需要保留的证据点有哪些？",
        ]
    if task_type == "retrieval":
        return [
            "明确的关键词/话题是什么？",
            "是否需要人物或时间过滤？",
            "是否需要上下文窗口？",
        ]
    return [
        "关键事实与证据有哪些？",
        "是否存在模式或趋势？",
        "需要补充哪些信息？",
    ]



def _get_loader() -> ChatlogLoader:
    """Create a fresh ChatlogLoader (no caching)."""
    return ChatlogLoader()


def _get_searcher(loader: ChatlogLoader) -> ChatlogSearcher:
    """Create a fresh ChatlogSearcher (no caching)."""
    return ChatlogSearcher(
        loader=loader,
        context_before=int(os.getenv("CHATLOG_CONTEXT_BEFORE", "2")),
        context_after=int(os.getenv("CHATLOG_CONTEXT_AFTER", "2"))
    )


def _get_cleaner() -> ChatlogCleaner:
    """Get the chatlog cleaner instance."""
    global _chatlog_cleaner
    if _chatlog_cleaner is None:
        config = CleanerConfig(
            model=os.getenv("CHATLOG_CLEANER_MODEL", "Gemini-2.5-Flash-Lite"),
            char_threshold=int(os.getenv("CHATLOG_CHAR_THRESHOLD", "3000")),
            target_chars=int(os.getenv("CHATLOG_TARGET_CHARS", "2000"))
        )
        _chatlog_cleaner = ChatlogCleaner(config)
    return _chatlog_cleaner


# Internal implementations (undecorated, for sync use)

async def _query_chatlog_indexed_impl(args: dict) -> dict:
    """
    Optimized query implementation using pre-built metadata index.
    
    Uses O(1) topic lookups instead of linear scans.
    Returns compact results to avoid context explosion.
    """
    import time
    import datetime
    
    query_start_time = time.time()
    
    def log(msg: str, phase: str = ""):
        """Log with millisecond timestamp."""
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        phase_str = f" [{phase}]" if phase else ""
        print(f"[CHATLOG INDEX] [{ts}]{phase_str} {msg}")
    
    question = args.get("question", "")
    target_person = args.get("target_person")
    max_results = min(int(args.get("max_results", 20)), _CHATLOG_INDEX_MAX_RESULTS)
    
    log(f"🚀 开始索引查询", "START")
    log(f"📝 问题: '{question}' (人物: {target_person or '无'})")
    
    if not question:
        return {"content": [{"type": "text", "text": "错误：请提供查询问题。"}]}
    
    # Load index (fast, O(1) lookups)
    index_loader = get_index_loader()
    if not index_loader.load_index():
        log("⚠️ 索引未找到，回退到旧实现", "FALLBACK")
        return await _query_chatlog_impl(args)
    
    log(
        f"✓ 索引已加载: {len(index_loader.available_topics)} 话题 | 文件: {index_loader.index_path}"
    )
    
    # Step 1: Use cleaner to identify topics from question
    cleaner = _get_cleaner()
    poe_client = cleaner._get_poe_client()
    
    keywords = []
    if poe_client and poe_client.is_configured:
        log(f"🔑 使用小模型识别话题: {cleaner.config.model}")
        start = time.time()
        keywords, query_metadata = await cleaner.expand_query(
            question, target_person, index_loader.available_topics
        )
        selected_topics = query_metadata.get("topics", [])
        log(f"   ✓ 可用话题标签数: {len(index_loader.available_topics)}", "TOPICS")
        log(
            f"   ✓ 识别话题({len(selected_topics)}): {', '.join(selected_topics) if selected_topics else '无'}",
            "TOPICS"
        )
        log(f"   ✓ 关键词({len(keywords)}): {', '.join(keywords)}", "KEYWORDS")
        log(f"   ✓ 扩展耗时: {time.time()-start:.2f}s")
    else:
        log("⚠️ Poe API未配置，使用模糊匹配")
        # Fallback: fuzzy match topics based on question keywords
        selected_topics = []
        if "借" in question or "钱" in question:
            for topic in ("借贷", "金钱"):
                if topic in index_loader.available_topics:
                    selected_topics.append(topic)
        if target_person and target_person in index_loader.available_topics:
            selected_topics.append(target_person)
        keywords = cleaner._fallback_keyword_extraction(
            question, target_person, index_loader.available_topics
        )
        selected_topics = cleaner._ensure_topic_coverage(
            question=question,
            target_person=target_person,
            keywords=keywords,
            topics=selected_topics,
            available_topics=index_loader.available_topics
        )
        log(f"   ✓ 可用话题标签数: {len(index_loader.available_topics)}", "TOPICS")
        log(
            f"   ✓ 识别话题({len(selected_topics)}): {', '.join(selected_topics) if selected_topics else '无'}",
            "TOPICS"
        )
        log(f"   ✓ 关键词({len(keywords)}): {', '.join(keywords)}", "KEYWORDS")
    
    # Step 2: Search by topics using index (O(1) per topic)
    log("🔍 Step 2: 索引搜索...", "SEARCH")
    start = time.time()

    matched_lines = set()

    # Search by selected topics
    log(f"   ✓ 使用话题检索: {len(selected_topics)} 个", "SEARCH")
    for topic in selected_topics:
        lines = index_loader.search_by_topic_exact(topic)
        matched_lines.update(lines[:max_results])
    
    # Only search by selected topics (keywords are used for topic selection only)

    # Semantic recall (optional, uses local embeddings cache)
    sem_weight = float(os.getenv("CHATLOG_SEM_WEIGHT", "0.6"))
    kw_weight = float(os.getenv("CHATLOG_KW_WEIGHT", "0.4"))
    weight_sum = sem_weight + kw_weight if (sem_weight + kw_weight) > 0 else 1.0
    sem_weight /= weight_sum
    kw_weight /= weight_sum
    sem_top_k = int(os.getenv("CHATLOG_SEM_TOP_K", "100"))  # 提升：有压缩可以召回更多
    semantic_scores: Dict[int, float] = {}

    semantic_index = get_semantic_index()
    if semantic_index.is_available():
        log("   ✓ 语义检索: 已启用", "SEARCH")
        semantic_matches = semantic_index.search(question, top_k=sem_top_k)
        for line_num, score in semantic_matches:
            # Normalize cosine (-1..1) -> (0..1)
            semantic_scores[line_num] = max(0.0, min(1.0, (score + 1.0) / 2.0))
        log(
            f"   ✓ 语义命中: {len(semantic_scores)} 条 | top_k={sem_top_k}",
            "SEARCH"
        )
    else:
        log("   ⚠️ 语义检索: 未启用 (缺少 embeddings 缓存)", "SEARCH")

    log(f"   ✓ 匹配消息: {len(matched_lines)} 条 ({time.time()-start:.2f}s)")
    
    if not matched_lines and not semantic_scores:
        log("⚠️ 未找到匹配消息", "RESULT")
        return {
            "content": [{
                "type": "text",
                "text": f"未找到与「{question}」相关的聊天记录。\n搜索话题: {', '.join(selected_topics)}"
            }]
        }
    
    # Step 3: Load messages with context (only matched lines)
    log("📄 Step 3: 加载消息...", "LOAD")
    start = time.time()
    
    combined_lines = set(matched_lines) | set(semantic_scores.keys())
    if not combined_lines:
        combined_lines = set(matched_lines)

    def _score(line_num: int) -> float:
        score = 0.0
        if line_num in matched_lines:
            score += kw_weight * 1.0
        if line_num in semantic_scores:
            score += sem_weight * semantic_scores[line_num]
        return score

    scored_lines = sorted(combined_lines, key=lambda ln: (_score(ln), -ln), reverse=True)
    sorted_lines = scored_lines[:max_results]
    messages = index_loader.get_messages_by_lines(
        sorted_lines,
        context_before=_CHATLOG_INDEX_CONTEXT_BEFORE,
        context_after=_CHATLOG_INDEX_CONTEXT_AFTER
    )
    
    log(f"   ✓ 加载消息: {len(messages)} 条 ({time.time()-start:.2f}s)")
    
    # Step 4: Format raw results for cleaning (hit-centered windows)
    log("📦 Step 4: 格式化结果...", "FORMAT")

    message_map = {msg.get("line_number"): msg for msg in messages}
    filtered_samples: List[str] = []
    def _window_mentions_other_person(line_num: int) -> bool:
        if not target_person:
            return False
        start = max(1, line_num - _CHATLOG_INDEX_CONTEXT_BEFORE)
        end = line_num + _CHATLOG_INDEX_CONTEXT_AFTER
        persons = set()
        for ln in range(start, end + 1):
            msg = message_map.get(ln)
            if not msg:
                continue
            facts = (msg.get("metadata") or {}).get("facts") or {}
            for key in ("人物", "对象", "主体", "人"):
                val = facts.get(key)
                if isinstance(val, str) and val.strip():
                    persons.add(val.strip())
        if not persons:
            return False
        if target_person not in persons:
            if len(filtered_samples) < 3:
                filtered_samples.append(
                    f"行{line_num} persons={', '.join(sorted(persons))}"
                )
            return True
        return False

    if target_person:
        filtered_lines = [
            ln for ln in sorted_lines if not _window_mentions_other_person(ln)
        ]
        if filtered_lines:
            log(
                f"   ✓ 命中窗口过滤(基于facts): {len(sorted_lines)} -> {len(filtered_lines)}",
                "FORMAT"
            )
            if filtered_samples:
                log(
                    "   ✓ 过滤示例: " + " | ".join(filtered_samples),
                    "FORMAT"
                )
            sorted_lines = filtered_lines

    result_parts = []
    result_parts.append(f"## 查询: {question}")
    result_parts.append(f"话题: {', '.join(selected_topics) if selected_topics else '无'}")
    result_parts.append(f"匹配: {len(sorted_lines)} 条 | 返回: {len(messages)} 条")
    result_parts.append(f"关键词: {', '.join(keywords[:20]) if keywords else '无'}")

    for idx, line_num in enumerate(sorted_lines, 1):
        start = max(1, line_num - _CHATLOG_INDEX_CONTEXT_BEFORE)
        end = line_num + _CHATLOG_INDEX_CONTEXT_AFTER
        result_parts.append(
            f"--- 命中窗口 {idx} (行 {line_num}, ±{_CHATLOG_INDEX_CONTEXT_BEFORE}/{_CHATLOG_INDEX_CONTEXT_AFTER}) ---"
        )
        for ln in range(start, end + 1):
            msg = message_map.get(ln)
            if not msg:
                continue
            raw = msg.get("content", "")
            sender = "未知"
            body = raw
            if ": " in raw:
                sender, body = raw.split(": ", 1)
            ts = msg.get("timestamp", "")[:19]
            tag = "命中" if msg.get("is_match") else "上下文"
            confidence = "高" if msg.get("is_match") else "中"
            result_parts.append(
                f"[{ts}] {sender}: {body} (行{ln} {tag} 置信度:{confidence})"
            )

    raw_text = "\n".join(result_parts)

    # Step 5: Second-pass selection (skip if already window-formatted)
    log("🧹 Step 5: 二次筛选清洗...", "CLEAN")
    if target_person:
        raw_text, attr_stats = await cleaner.entity_attribution(
            raw_text,
            target_person,
            question
        )
        if not attr_stats.get("skipped"):
            log(
                f"   ✓ 实体归因: 保留 {attr_stats.get('keep_count', 0)} 条 | "
                f"排除 {attr_stats.get('exclude_count', 0)} 条",
                "CLEAN"
            )
    if "命中窗口" in raw_text:
        cleaned = raw_text
        log("   跳过清洗：已包含命中窗口上下文(已做实体归因)", "CLEAN")
    else:
        if poe_client and poe_client.is_configured:
            log(f"   调用 {cleaner.config.model} 进行二次筛选...", "CLEAN")
        else:
            log("   使用简单截断 (Poe未配置)", "CLEAN")
        cleaned = await cleaner.clean_results(
            formatted_text=raw_text,
            question=question,
            target_person=target_person,
            force=True
        )
    log(f"   ✓ 清洗后: {len(cleaned)} 字符", "CLEAN")

    result_text = _cap_text(cleaned, _CHATLOG_MAX_RETURN_CHARS)
    
    total_time = time.time() - query_start_time
    log(f"✅ 查询完成，准备返回给 Agent", "DONE")
    log(f"⏱️ 总耗时: {total_time:.2f}s | 返回字符: {len(result_text)}", "TIMING")

    return {
        "content": [{"type": "text", "text": result_text}]
    }


async def _query_chatlog_composed_impl(args: dict) -> dict:
    """Compose atomic tools to answer a chatlog query."""
    import datetime

    def log(msg: str, phase: str = ""):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        phase_str = f" [{phase}]" if phase else ""
        print(f"[CHATLOG MCP] [{ts}]{phase_str} {msg}")

    question = args.get("question", "")
    target_person = args.get("target_person")
    requested_max = args.get("max_results", 100)
    max_results = min(max(1, int(requested_max)), _CHATLOG_INDEX_MAX_RESULTS)

    if not question:
        return {
            "content": [{"type": "text", "text": "错误：请提供查询问题。"}],
            "is_error": True,
        }

    query_start_time = time.time()
    log(f"🚀 开始组合查询", "START")
    log(f"📝 收到查询: '{question}' (人物: {target_person or '无'}, 限制: {max_results})")

    index_loader = get_index_loader()
    if not index_loader.load_index():
        log("⚠️ 索引未找到，回退到旧实现", "FALLBACK")
        return await _query_chatlog_impl(args)

    cleaner = _get_cleaner()
    poe_client = cleaner._get_poe_client()
    llm_available = bool(poe_client and poe_client.is_configured)

    log("🔑 Step 1: 查询扩展", "EXPAND")
    available_topics = index_loader.available_topics
    if llm_available:
        keywords, metadata = await cleaner.expand_query(
            question, target_person, available_topics
        )
        method = "llm"
    else:
        keywords = cleaner._fallback_keyword_extraction(
            question, target_person, available_topics
        )
        metadata = cleaner._fallback_metadata_classification(
            question, available_topics
        )
        metadata["topics"] = cleaner._ensure_topic_coverage(
            question=question,
            target_person=target_person,
            keywords=keywords,
            topics=metadata.get("topics", []),
            available_topics=available_topics,
        )
        method = "rule_based"
    topics = metadata.get("topics", []) or []
    log(f"   ✓ method: {method} | keywords: {len(keywords)} | topics: {len(topics)}", "EXPAND")

    log("🔍 Step 2: 话题索引检索 + 语义检索(并行)", "SEARCH")

    async def _search_topics() -> set[int]:
        lines: set[int] = set()
        for topic in topics:
            lines.update(index_loader.search_by_topic_exact(topic))
        return lines

    async def _search_semantic() -> Dict[int, float]:
        semantic_index = get_semantic_index()
        if not semantic_index.is_available():
            log("   ⚠️ 语义检索未启用 (缺少 embeddings 缓存)", "SEARCH")
            return {}
        log("   ✓ 语义检索启用", "SEARCH")
        sem_top_k = int(os.getenv("CHATLOG_SEM_TOP_K", "100"))  # 提升：有压缩可以召回更多
        semantic_matches = await asyncio.to_thread(
            semantic_index.search,
            question,
            top_k=sem_top_k
        )
        scores: Dict[int, float] = {}
        for line_num, score in semantic_matches:
            scores[line_num] = max(0.0, min(1.0, (score + 1.0) / 2.0))
        return scores

    matched_lines, semantic_scores = await asyncio.gather(
        _search_topics(),
        _search_semantic()
    )

    sem_weight = float(os.getenv("CHATLOG_SEM_WEIGHT", "0.6"))
    kw_weight = float(os.getenv("CHATLOG_KW_WEIGHT", "0.4"))
    weight_sum = sem_weight + kw_weight if (sem_weight + kw_weight) > 0 else 1.0
    sem_weight /= weight_sum
    kw_weight /= weight_sum

    if not matched_lines and not semantic_scores:
        log("⚠️ 未找到匹配消息", "RESULT")
        return {
            "content": [{
                "type": "text",
                "text": f"未找到与「{question}」相关的聊天记录。"
            }]
        }

    def _score(line_num: int) -> float:
        score = 0.0
        if line_num in matched_lines:
            score += kw_weight
        if line_num in semantic_scores:
            score += sem_weight * semantic_scores[line_num]
        return score

    combined_lines = set(matched_lines) | set(semantic_scores.keys())
    ranked_lines = sorted(combined_lines, key=lambda ln: (_score(ln), -ln), reverse=True)
    ranked_lines = ranked_lines[:max_results]

    log(f"📄 Step 3: 加载消息 (命中: {len(ranked_lines)})", "LOAD")
    messages = index_loader.get_messages_by_lines(
        ranked_lines,
        context_before=_CHATLOG_INDEX_CONTEXT_BEFORE,
        context_after=_CHATLOG_INDEX_CONTEXT_AFTER,
    )

    formatted_messages: List[Dict[str, Any]] = []
    for msg in messages:
        raw = msg.get("content", "")
        sender, body = _parse_sender_content(raw)
        formatted_messages.append({
            "line": msg.get("line_number"),
            "time": (msg.get("timestamp") or "")[:19],
            "sender": sender or "未知",
            "content": body,
            "is_match": bool(msg.get("is_match")),
        })

    if target_person:
        if llm_available:
            filter_result = await _filter_by_person_impl({
                "messages": formatted_messages,
                "target_person": target_person,
                "use_llm": True,
            })
        else:
            filter_result = await _filter_by_person_impl({
                "messages": formatted_messages,
                "target_person": target_person,
                "use_llm": False,
            })
        if filter_result.get("content"):
            try:
                payload = json.loads(filter_result["content"][0]["text"])
                formatted_messages = payload.get("data", {}).get("filtered_messages", formatted_messages)
            except (ValueError, KeyError, TypeError):
                pass

    log("🧾 Step 4: 格式化输出", "FORMAT")
    formatted_lines = []
    for m in formatted_messages:
        tag = "✓" if m.get("is_match") else ""
        line = f"[{m.get('time', '')}] {m.get('sender', '未知')}: {m.get('content', '')} {tag}".strip()
        formatted_lines.append(line)

    header = [
        "## 聊天记录检索结果",
        f"**问题**: {question}",
    ]
    if target_person:
        header.append(f"**目标人物**: {target_person}")
    header.append(f"**话题**: {', '.join(topics) if topics else '无'}")
    header.append(f"**关键词**: {', '.join(keywords) if keywords else '无'}")
    header.append(f"**命中消息**: {len(ranked_lines)}")
    header.append("---")

    combined_text = "\n".join(header + formatted_lines)
    if len(combined_text) > cleaner.config.char_threshold:
        log("🧹 Step 5: 清洗压缩", "CLEAN")
        combined_text = await cleaner.clean_results(
            formatted_text=combined_text,
            question=question,
            target_person=target_person,
            force=True,
        )

    result_text = _cap_text(combined_text, _CHATLOG_MAX_RETURN_CHARS)
    total_time = time.time() - query_start_time
    log(f"✅ 查询完成，耗时 {total_time:.2f}s | 返回字符: {len(result_text)}", "DONE")
    return {"content": [{"type": "text", "text": result_text}]}

async def _query_chatlog_impl(args: dict) -> dict:
    """Internal implementation of query_chatlog."""
    import time
    import datetime
    
    query_start_time = time.time()  # Track total query time
    
    def log(msg: str, phase: str = ""):
        """Add log entry with millisecond timestamp."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        phase_str = f" [{phase}]" if phase else ""
        print(f"[CHATLOG MCP] [{timestamp}]{phase_str} {msg}")
    
    question = args.get("question", "")
    target_person = args.get("target_person")
    # Enforce a reasonable minimum max_results to avoid excessive outputs
    requested_max = args.get("max_results", 100)
    max_results = min(max(1, int(requested_max)), 100)  # Cap to avoid huge output
    
    log(f"🚀 开始查询循环", "START")
    log(f"📝 收到查询: '{question}' (人物: {target_person or '无'}, 限制: {max_results})")
    
    if not question:
        return {
            "content": [{"type": "text", "text": "错误：请提供查询问题。"}]
        }
    
    loader = _get_loader()
    searcher = _get_searcher(loader)
    cleaner = _get_cleaner()

    log("📂 正在加载聊天记录...")
    start = time.time()
    if not loader.load():
        return {
            "content": [{
                "type": "text",
                "text": f"错误：无法加载聊天记录文件 {loader.file_path}"
            }]
        }
    log(f"✓ 加载完成: {loader.message_count} 条消息 ({time.time()-start:.2f}s)")
    
    try:
        # Step 1: Expand query
        log("🔑 Step 1: 元数据与关键词扩展...")
        start = time.time()
        
        # Check if Poe is configured
        poe_client = cleaner._get_poe_client()
        if poe_client and poe_client.is_configured:
            log(f"   使用小模型: {cleaner.config.model}")
        else:
            log("   ⚠️ Poe API未配置，使用规则fallback")
        
        available_topics = loader.get_unique_topics()
        keywords, query_metadata = await cleaner.expand_query(
            question, target_person, available_topics
        )
        topics = query_metadata.get("topics", [])
        log(f"   ✓ 搜索关键词: {', '.join(keywords)}", "KEYWORDS")
        log(f"   ✓ 话题标签: {', '.join(topics) if topics else '无'}", "TOPICS")
        log(
            f"   ✓ 情感: {query_metadata.get('sentiment')}, "
            f"信息密度: {query_metadata.get('information_density')}"
        )
        log(f"   ✓ 可用话题标签数: {len(available_topics)}")
        log(f"   ✓ 扩展耗时: {time.time()-start:.2f}s")
        
        if not keywords:
            result_text = "错误：无法从问题中提取关键词。"
            log(f"❌ 查询失败: 无法提取关键词", "ERROR")
            return {
                "content": [{"type": "text", "text": result_text}]
            }
        
        # Step 2: Search with metadata
        log("🔍 Step 2: 元数据搜索...")
        start = time.time()

        if target_person:
            result = searcher.search_by_metadata(
                metadata=query_metadata,
                keywords=keywords,
                target_person=target_person,
                max_results=max_results
            )
        else:
            result = searcher.search_by_metadata(
                metadata=query_metadata,
                keywords=keywords,
                target_person=None,
                max_results=max_results
            )
        
        log(f"   ✓ 匹配消息: {len(result.messages)} 条")
        log(f"   上下文窗口: ±{searcher.context_before}/{searcher.context_after} 条")
        log(f"   搜索耗时: {time.time()-start:.2f}s")
        
        if not result.messages:
            result_text = f"未找到与「{question}」相关的聊天记录。\n搜索关键词: {', '.join(keywords)}"
            log(f"⚠️ 未找到匹配消息", "RESULT")
            return {
                "content": [{"type": "text", "text": result_text}]
            }
        
        # Step 3: Format results
        log("📄 Step 3: 格式化结果...")
        start = time.time()
        formatted = searcher.format_segmented_output(result, gap_threshold=10)
        original_len = len(formatted)
        log(f"   原始大小: {original_len} 字符")
        log(f"   格式化耗时: {time.time()-start:.2f}s")
        
        # Step 4: Second-pass selection (skip if already window-formatted)
        log("🧹 Step 4: 二次筛选清洗...")
        start = time.time()

        if target_person:
            formatted, attr_stats = await cleaner.entity_attribution(
                formatted,
                target_person,
                question
            )
            if not attr_stats.get("skipped"):
                log(
                    f"   ✓ 实体归因: 保留 {attr_stats.get('keep_count', 0)} 条 | "
                    f"排除 {attr_stats.get('exclude_count', 0)} 条"
                )
        if "命中窗口" in formatted:
            cleaned = formatted
            log("   跳过清洗：已包含命中窗口上下文(已做实体归因)")
        else:
            if poe_client and poe_client.is_configured:
                log(f"   调用 {cleaner.config.model} 进行二次筛选...")
            else:
                log("   使用简单截断 (Poe未配置)")

            cleaned = await cleaner.clean_results(
                formatted_text=formatted,
                question=question,
                target_person=target_person,
                force=True
            )
        log(f"   ✓ 清洗后: {len(cleaned)} 字符 ({time.time()-start:.2f}s)")

        
        # Build response header
        header = f"## 聊天记录检索结果\n\n"
        header += f"**问题**: {question}\n"
        if target_person:
            header += f"**目标人物**: {target_person}\n"
        header += f"**搜索关键词**: {', '.join(keywords)}\n"
        header += (
            f"**查询元数据**: topics={query_metadata.get('topics', [])}, "
            f"sentiment={query_metadata.get('sentiment')}, "
            f"information_density={query_metadata.get('information_density')}\n"
        )
        header += f"**找到消息数**: {len(result.messages)}\n"
        header += f"**原始大小**: {original_len} 字符\n"
        header += f"**最终大小**: {len(cleaned)} 字符\n"
        header += f"---\n\n"
        
        # Log completion (no footer in return to reduce agent context)
        total_time = time.time() - query_start_time
        log(f"📦 正在包装结果...", "WRAP")
        log(f"✅ 查询完成，准备返回给 Agent", "DONE")
        log(f"⏱️ 总耗时: {total_time:.2f}s", "TIMING")
        
        # Return without operation logs to reduce agent context size
        final_text = _cap_text(header + cleaned, _CHATLOG_MAX_RETURN_CHARS)
        return {
            "content": [{
                "type": "text",
                "text": final_text
            }]
        }
        
    except Exception as e:
        log(f"❌ 错误: {str(e)}", "ERROR")
        import traceback
        log(f"   {traceback.format_exc()}")
        return {
            "content": [{
                "type": "text",
                "text": f"查询错误: {str(e)}"
            }]
        }



async def _get_chatlog_stats_impl(args: dict) -> dict:
    """Internal implementation of get_chatlog_stats."""
    loader = _get_loader()
    
    if not loader.is_loaded:
        if not loader.load():
            return _error(
                f"错误：无法加载聊天记录文件 {loader.file_path}",
                meta={"source": "stats"},
                tool_name="get_chatlog_stats"
            )
    
    stats = loader.get_stats()

    data = {
        "stats": stats,
    }
    meta = {
        "available": True,
        "source": "stats",
    }
    return _success(data, meta=meta, tool_name="get_chatlog_stats")


async def _list_topics_impl(args: dict) -> dict:
    started = time.time()
    limit = min(int(args.get("limit", _CHATLOG_MAX_LIST_ITEMS)), _CHATLOG_MAX_LIST_ITEMS)
    pattern = (args.get("pattern") or "").strip()

    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error(
            "无法加载索引",
            meta={
                "available": False,
                "source": "index",
                "timing_ms": int((time.time() - started) * 1000)
            },
            tool_name="list_topics"
        )

    topics = index_loader.available_topics
    if pattern:
        pattern_lower = pattern.lower()
        topics = [t for t in topics if pattern_lower in t.lower()]

    topics_sorted = sorted(topics)
    limited, omitted_count, next_cursor = _truncate_list(
        topics_sorted,
        limit,
        cursor_prefix=f"topics:{pattern or 'all'}"
    )
    data = {
        "topics": limited,
        "total_count": len(index_loader.available_topics),
        "returned_count": len(limited),
        "omitted_count": omitted_count,
        "next_cursor": next_cursor,
        "pattern": pattern or None,
    }
    meta = {
        "available": True,
        "source": "index",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="list_topics")


async def _search_by_topics_impl(args: dict) -> dict:
    started = time.time()
    topics = _coerce_list(args.get("topics"))
    max_results = min(int(args.get("max_results", _CHATLOG_MAX_LIST_ITEMS)), 500)

    if not topics:
        return _error(
            "请提供至少一个话题",
            meta={"source": "index"},
            tool_name="search_by_topics"
        )

    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error(
            "无法加载索引",
            meta={
                "available": False,
                "source": "index",
                "timing_ms": int((time.time() - started) * 1000)
            },
            tool_name="search_by_topics"
        )

    all_lines: set[int] = set()
    breakdown: Dict[str, int] = {}
    for topic in topics:
        lines = index_loader.search_by_topic_exact(topic)
        breakdown[topic] = len(lines)
        all_lines.update(lines)

    line_numbers = sorted(all_lines)
    limited, omitted_count, next_cursor = _truncate_list(
        line_numbers,
        max_results,
        cursor_prefix="topics"
    )
    data = {
        "line_numbers": limited,
        "total_matches": len(all_lines),
        "topic_breakdown": breakdown,
        "omitted_count": omitted_count,
        "next_cursor": next_cursor,
    }
    meta = {
        "available": True,
        "source": "index",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="search_by_topics")


async def _search_by_keywords_impl(args: dict) -> dict:
    started = time.time()
    keywords = _coerce_list(args.get("keywords"))
    target_person = args.get("target_person")
    max_results = min(int(args.get("max_results", _CHATLOG_MAX_LIST_ITEMS)), 500)
    match_all = bool(args.get("match_all", False))

    if not keywords:
        return _error(
            "请提供至少一个关键词",
            meta={"source": "scan"},
            tool_name="search_by_keywords"
        )

    loader = _get_loader()
    if not loader.load():
        return _error(
            "无法加载聊天记录",
            meta={
                "available": False,
                "source": "scan",
                "timing_ms": int((time.time() - started) * 1000)
            },
            tool_name="search_by_keywords"
        )

    normalized_keywords = [k.lower() for k in keywords if isinstance(k, str)]
    keyword_hits = {k: 0 for k in normalized_keywords}
    matched_lines: List[int] = []

    target_lower = target_person.lower() if isinstance(target_person, str) else None

    for msg in loader.get_all_messages():
        if target_lower and target_lower not in (msg.sender or "").lower():
            continue
        content_lower = msg.content.lower()
        matches = [kw for kw in normalized_keywords if kw and kw in content_lower]
        if (match_all and len(matches) == len(normalized_keywords)) or (not match_all and matches):
            matched_lines.append(msg.line_number)
            for kw in matches:
                keyword_hits[kw] += 1

    limited, omitted_count, next_cursor = _truncate_list(
        matched_lines,
        max_results,
        cursor_prefix="keywords"
    )
    data = {
        "line_numbers": limited,
        "total_matches": len(matched_lines),
        "keyword_breakdown": keyword_hits,
        "person_filter": target_person,
        "match_all": match_all,
        "omitted_count": omitted_count,
        "next_cursor": next_cursor,
    }
    meta = {
        "available": True,
        "source": "scan",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="search_by_keywords")


async def _load_messages_impl(args: dict) -> dict:
    started = time.time()
    line_numbers = _coerce_int_list(args.get("line_numbers"))
    context_before = min(
        int(args.get("context_before", _CHATLOG_LOAD_CONTEXT_BEFORE)),
        5,
    )
    context_after = min(
        int(args.get("context_after", _CHATLOG_LOAD_CONTEXT_AFTER)),
        5,
    )
    include_metadata = bool(args.get("include_metadata", False))
    max_messages = min(
        int(args.get("max_messages", _CHATLOG_LOAD_MAX_MESSAGES)),
        200,
    )
    max_content_chars = min(
        int(args.get("max_content_chars", _CHATLOG_MAX_CONTENT_CHARS)),
        2000
    )
    snippet_chars = min(
        int(args.get("snippet_chars", _CHATLOG_SNIPPET_CHARS)),
        500,
    )
    fields = args.get("fields") or ["line", "time", "sender", "content"]

    if not line_numbers:
        return _error(
            "请提供行号列表",
            meta={"source": "index"},
            tool_name="load_messages"
        )

    context_span = max(1, context_before + context_after + 1)
    max_lines = max(1, int(max_messages / context_span))
    cleaned_lines = line_numbers[:max_lines]
    if not cleaned_lines:
        return _error(
            "行号格式无效",
            meta={"source": "index"},
            tool_name="load_messages"
        )

    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error(
            "无法加载索引",
            meta={
                "available": False,
                "source": "index",
                "timing_ms": int((time.time() - started) * 1000)
            },
            tool_name="load_messages"
        )

    messages = index_loader.get_messages_by_lines(
        cleaned_lines,
        context_before=context_before,
        context_after=context_after,
    )
    limited_messages, omitted_count, next_cursor = _truncate_list(
        messages,
        max_messages,
        cursor_prefix="messages"
    )
    truncated = omitted_count > 0
    result = []
    normalized_fields = [f for f in fields if isinstance(f, str) and f.strip()]
    if "line" not in normalized_fields:
        normalized_fields.insert(0, "line")
    for msg in limited_messages:
        raw = msg.get("content", "")
        sender, body = _parse_sender_content(raw)
        if max_content_chars > 0 and len(body) > max_content_chars:
            body = body[:max_content_chars] + "…"
        snippet = _build_snippet(body, snippet_chars)
        item = {
            "line": msg.get("line_number"),
            "time": (msg.get("timestamp") or "")[:19],
            "sender": sender or "未知",
            "content": snippet,
            "is_match": bool(msg.get("is_match")),
        }
        if include_metadata:
            item["metadata"] = msg.get("metadata", {})
        if "topics" in msg:
            item["topics"] = msg.get("topics")
        item = {k: v for k, v in item.items() if k in normalized_fields or k == "metadata"}
        result.append(item)

    data = {
        "messages": result,
        "count": len(result),
        "context": f"±{context_before}/{context_after}",
        "truncated": truncated,
        "omitted_count": omitted_count,
        "next_cursor": next_cursor,
        "max_messages": max_messages,
        "max_content_chars": max_content_chars,
        "snippet_chars": snippet_chars,
        "fields": normalized_fields,
    }
    meta = {
        "available": True,
        "source": "index",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="load_messages")


async def _expand_query_impl(args: dict) -> dict:
    started = time.time()
    question = args.get("question", "")
    target_person = args.get("target_person")
    use_llm = bool(args.get("use_llm", True))

    if not question:
        return _error(
            "请提供问题",
            meta={"source": "llm"},
            tool_name="expand_query"
        )

    index_loader = get_index_loader()
    available_topics = index_loader.available_topics if index_loader.load_index() else []
    # Only pass first 50 topics as preview to LLM to prevent token explosion
    # Full available_topics list (1771+) would consume ~8k tokens
    topics_preview = available_topics[:50] if available_topics else []

    cleaner = _get_cleaner()
    poe_client = cleaner._get_poe_client()
    llm_available = bool(poe_client and poe_client.is_configured)

    if use_llm and llm_available:
        keywords, metadata = await cleaner.expand_query(
            question, target_person, topics_preview  # Pass preview, not full list
        )
        # Server-side filtering: ensure LLM-suggested topics exist in available_topics
        llm_topics = metadata.get("topics", [])
        metadata["topics"] = [t for t in llm_topics if t in available_topics]
        method = "llm"
        model = cleaner.config.model
        llm_used = True
    else:
        keywords = cleaner._fallback_keyword_extraction(
            question, target_person, available_topics
        )
        metadata = cleaner._fallback_metadata_classification(
            question, available_topics
        )
        metadata["topics"] = cleaner._ensure_topic_coverage(
            question=question,
            target_person=target_person,
            keywords=keywords,
            topics=metadata.get("topics", []),
            available_topics=available_topics,
        )
        method = "rule_based"
        model = None
        llm_used = False

    limited_keywords, kw_omitted, kw_cursor = _truncate_list(
        keywords,
        _CHATLOG_MAX_LIST_ITEMS,
        cursor_prefix="keywords"
    )
    raw_topics = metadata.get("topics", []) or []
    limited_topics, topic_omitted, topic_cursor = _truncate_list(
        raw_topics,
        _CHATLOG_MAX_LIST_ITEMS,
        cursor_prefix="topics"
    )
    data = {
        "keywords": limited_keywords,
        "topics": limited_topics,
        "sentiment": metadata.get("sentiment"),
        "information_density": metadata.get("information_density"),
        "method": method,
        "model": model,
        "llm_available": llm_available,
        "omitted_count": {
            "keywords": kw_omitted,
            "topics": topic_omitted,
        },
        "next_cursor": {
            "keywords": kw_cursor,
            "topics": topic_cursor,
        },
    }
    meta = {
        "available": True,
        "source": "llm" if method == "llm" else "rule_based",
        "llm_used": llm_used,
        "model": model,
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="expand_query")


async def _search_semantic_impl(args: dict) -> dict:
    started = time.time()
    query = args.get("query", "")
    top_k = min(int(args.get("top_k", _CHATLOG_MAX_LIST_ITEMS)), 200)

    if not query:
        return _error(
            "请提供查询文本",
            meta={"source": "semantic"},
            tool_name="search_semantic"
        )

    semantic_index = get_semantic_index()
    if not semantic_index.is_available():
        data = {
            "available": False,
            "reason": "缺少 embeddings 缓存文件",
            "suggestion": "运行 python -m src.chatlog.semantic_index 构建索引",
            "results": [],
        }
        meta = {
            "available": False,
            "source": "semantic",
            "timing_ms": int((time.time() - started) * 1000),
        }
        return _success(data, meta=meta, tool_name="search_semantic")

    raw_results = semantic_index.search(query, top_k=top_k)
    results = [
        {"line": ln, "score": round((score + 1.0) / 2.0, 4)}
        for ln, score in raw_results
    ]
    limited, omitted_count, next_cursor = _truncate_list(
        results,
        top_k,
        cursor_prefix="semantic"
    )
    data = {
        "available": True,
        "results": limited,
        "count": len(limited),
        "query": query,
        "omitted_count": omitted_count,
        "next_cursor": next_cursor,
    }
    meta = {
        "available": True,
        "source": "semantic",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="search_semantic")


async def _filter_by_person_impl(args: dict) -> dict:
    started = time.time()
    messages = args.get("messages") or []
    target_person = args.get("target_person", "")
    use_llm = bool(args.get("use_llm", True))

    if not messages:
        return _error(
            "请提供消息列表",
            meta={"source": "llm"},
            tool_name="filter_by_person"
        )
    if not target_person:
        return _error(
            "请提供目标人物",
            meta={"source": "llm"},
            tool_name="filter_by_person"
        )

    cleaner = _get_cleaner()
    poe_client = cleaner._get_poe_client()
    llm_available = bool(poe_client and poe_client.is_configured)

    kept: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []

    if use_llm and llm_available:
        formatted_lines = [
            f"[{m.get('time', '')}] {m.get('sender', '未知')}: {m.get('content', '')}"
            for m in messages
        ]
        formatted_text = "\n".join(formatted_lines)
        filtered_text, attr_stats = await cleaner.entity_attribution(
            formatted_text,
            target_person,
            ""
        )
        filtered_set = {line.strip() for line in filtered_text.splitlines() if line.strip()}
        for msg, line in zip(messages, formatted_lines):
            if line.strip() in filtered_set:
                kept.append(msg)
            else:
                excluded.append(msg)
        method = "llm_attribution"
        meta = {
            "available": True,
            "source": "llm",
            "llm_used": True,
            "model": cleaner.config.model,
            "timing_ms": int((time.time() - started) * 1000),
            "attr_stats": attr_stats,
        }
    else:
        for msg in messages:
            content = msg.get("content", "")
            sender = msg.get("sender", "")
            if target_person in content or target_person == sender:
                kept.append(msg)
            else:
                excluded.append(msg)
        method = "name_match"
        meta = {
            "available": True,
            "source": "rule_based",
            "llm_used": False,
            "model": None,
            "timing_ms": int((time.time() - started) * 1000),
        }

    data = {
        "filtered_messages": kept,
        "kept_count": len(kept),
        "excluded_count": len(excluded),
        "method": method,
        "target_person": target_person,
        "llm_available": llm_available,
    }
    return _success(data, meta=meta, tool_name="filter_by_person")


async def _format_messages_impl(args: dict) -> dict:
    started = time.time()
    messages = args.get("messages") or []
    fmt = args.get("format", "compact")
    max_chars = min(int(args.get("max_chars", _CHATLOG_MAX_RETURN_CHARS)), 10000)

    if not messages:
        return _error(
            "请提供消息列表",
            meta={"source": "format"},
            tool_name="format_messages"
        )

    lines: List[str] = []
    if fmt == "timeline":
        lines.append("## 时间线")
        current_date = None
        for m in messages:
            time_str = m.get("time", "")
            date = time_str[:10] if time_str else "未知日期"
            if date != current_date:
                current_date = date
                lines.append("")
                lines.append(f"### {date}")
            clock = time_str[11:16] if len(time_str) >= 16 else ""
            sender = m.get("sender", "未知")
            content = m.get("content", "")
            lines.append(f"- **{clock}** [{sender}]: {content}")
    elif fmt == "detailed":
        for m in messages:
            lines.append("---")
            lines.append(f"**行号**: {m.get('line')}")
            lines.append(f"**时间**: {m.get('time')}")
            lines.append(f"**发送者**: {m.get('sender')}")
            lines.append(f"**内容**: {m.get('content')}")
    else:
        for m in messages:
            tag = "✓" if m.get("is_match") else ""
            line = f"[{m.get('time', '')}] {m.get('sender', '未知')}: {m.get('content', '')} {tag}".strip()
            lines.append(line)

    text = "\n".join(lines)
    truncated = len(text) > max_chars
    if truncated:
        text = _cap_text(text, max_chars)

    data = {
        "text": text,
        "chars": len(text),
        "messages": len(messages),
        "format": fmt,
        "truncated": truncated,
    }
    meta = {
        "available": True,
        "source": "format",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="format_messages")


def _extract_amounts(text: str) -> List[str]:
    if not text:
        return []
    amounts: List[str] = []
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(元|块|￥|¥|rmb|人民币)", re.IGNORECASE)
    for match in pattern.finditer(text):
        amount = match.group(1)
        unit = match.group(2)
        amounts.append(f"{amount}{unit}")
    return amounts


def _classify_signal(content: str) -> Tuple[bool, bool]:
    repay_keywords = ("还", "还钱", "还款", "还你", "还我", "已还", "转账给")
    negative_keywords = ("没还", "未还", "拖", "推迟", "下次", "改天", "晚点")

    has_repay = any(k in content for k in repay_keywords)
    has_negative = any(k in content for k in negative_keywords)
    return has_repay, has_negative


async def _parse_task_impl(args: dict) -> dict:
    started = time.time()
    question = args.get("question", "")
    target_person = args.get("target_person")
    use_llm = bool(args.get("use_llm", True))
    max_dimensions = min(int(args.get("max_dimensions", 4)), 6)

    if not question:
        return _error(
            "请提供问题",
            meta={"source": "parse"},
            tool_name="parse_task"
        )

    index_loader = get_index_loader()
    available_topics = index_loader.available_topics if index_loader.load_index() else []
    cleaner = _get_cleaner()
    poe_client = cleaner._get_poe_client()
    llm_available = bool(poe_client and poe_client.is_configured)

    if use_llm and llm_available:
        plan = await cleaner.plan_evidence_dimensions(
            question,
            target_person=target_person,
            available_topics=available_topics,
            max_dimensions=max_dimensions,
        )
        method = plan.get("method", "llm")
        model = plan.get("model")
    else:
        plan = cleaner._fallback_dimension_plan(
            question,
            target_person=target_person,
            available_topics=available_topics,
            max_dimensions=max_dimensions,
        )
        method = plan.get("method", "rule_based")
        model = plan.get("model")

    task_type = _infer_task_type(question)

    output = {
        "task_type": task_type,
        "question_type": plan.get("question_type", "analysis"),
        "target_person": target_person,
        "dimensions": plan.get("dimensions", []),
        "method": method,
        "model": model,
    }
    result_meta = {
        "available": True,
        "source": "parse",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(output, meta=result_meta, tool_name="parse_task")


async def _retrieve_evidence_impl(args: dict) -> dict:
    started = time.time()
    question = args.get("question", "")
    target_person = args.get("target_person")
    dimensions = args.get("dimensions") or []
    max_per_dimension = min(
        int(args.get("max_per_dimension", _CHATLOG_MAX_EVIDENCE_PER_DIM)),
        _CHATLOG_MAX_EVIDENCE_PER_DIM,
    )
    max_total_messages = min(
        int(args.get("max_total_messages", _CHATLOG_MAX_EVIDENCE_MESSAGES)),
        _CHATLOG_MAX_EVIDENCE_MESSAGES,
    )
    snippet_chars = min(
        int(args.get("snippet_chars", _CHATLOG_EVIDENCE_SNIPPET_CHARS)),
        300,
    )
    context_before = min(
        int(args.get("context_before", _CHATLOG_LOAD_CONTEXT_BEFORE)),
        3,
    )
    context_after = min(
        int(args.get("context_after", _CHATLOG_LOAD_CONTEXT_AFTER)),
        3,
    )
    use_semantic = bool(args.get("use_semantic", True))
    use_llm_plan = bool(args.get("use_llm_plan", True))

    if not question and not dimensions:
        return _error(
            "请提供问题或维度计划",
            meta={"source": "retrieve"},
            tool_name="retrieve_evidence"
        )

    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error(
            "无法加载索引",
            meta={"source": "index"},
            tool_name="retrieve_evidence"
        )

    available_topics = index_loader.available_topics

    if not dimensions:
        cleaner = _get_cleaner()
        poe_client = cleaner._get_poe_client()
        llm_available = bool(poe_client and poe_client.is_configured)
        if use_llm_plan and llm_available:
            plan = await cleaner.plan_evidence_dimensions(
                question,
                target_person=target_person,
                available_topics=available_topics,
                max_dimensions=4,
            )
        else:
            plan = cleaner._fallback_dimension_plan(
                question,
                target_person=target_person,
                available_topics=available_topics,
                max_dimensions=4,
            )
        dimensions = plan.get("dimensions", [])

    if not dimensions:
        data = {
            "evidence_id": None,
            "dimensions": [],
            "limits": {
                "max_per_dimension": max_per_dimension,
                "max_total_messages": max_total_messages,
            },
        }
        meta = {
            "available": True,
            "source": "retrieve",
            "timing_ms": int((time.time() - started) * 1000),
        }
        return _success(data, meta=meta, tool_name="retrieve_evidence")

    semantic_index = get_semantic_index()
    sem_weight = float(os.getenv("CHATLOG_SEM_WEIGHT", "0.6"))
    kw_weight = float(os.getenv("CHATLOG_KW_WEIGHT", "0.4"))
    weight_sum = sem_weight + kw_weight if (sem_weight + kw_weight) > 0 else 1.0
    sem_weight /= weight_sum
    kw_weight /= weight_sum
    high_info_lines = set(index_loader.get_high_value_messages())

    evidence_store: List[Dict[str, Any]] = []
    dimension_outputs: List[Dict[str, Any]] = []
    remaining_budget = max_total_messages

    for dim in dimensions:
        if remaining_budget <= 0:
            break
        name = dim.get("name") or "未命名维度"
        intent = dim.get("intent") or ""
        topic_seeds = _coerce_list(dim.get("topic_seeds"))
        keyword_seeds = _coerce_list(dim.get("keyword_seeds"))
        semantic_queries = _coerce_list(dim.get("semantic_queries"))
        counter_queries = _coerce_list(dim.get("counter_queries"))
        min_evidence = int(dim.get("min_evidence", 3))

        topic_seeds = [t for t in topic_seeds if t in available_topics]
        topic_lines: Dict[int, int] = {}
        for topic in topic_seeds:
            for ln in index_loader.search_by_topic_exact(topic):
                topic_lines[ln] = topic_lines.get(ln, 0) + 1

        semantic_lines: Dict[int, float] = {}
        if use_semantic and semantic_queries and semantic_index.is_available():
            sem_top_k = min(_CHATLOG_MAX_LIST_ITEMS, max_per_dimension * 4)
            for query in semantic_queries:
                for line_num, score in semantic_index.search(query, top_k=sem_top_k):
                    semantic_lines[line_num] = max(
                        semantic_lines.get(line_num, 0.0),
                        max(0.0, min(1.0, (score + 1.0) / 2.0)),
                    )

        keyword_lines: Dict[int, int] = {}
        if keyword_seeds and not topic_lines and not semantic_lines:
            keyword_result = await _search_by_keywords_impl({
                "keywords": keyword_seeds,
                "target_person": target_person,
                "max_results": _CHATLOG_MAX_LIST_ITEMS,
                "match_all": False,
            })
            payload = _extract_payload(keyword_result)
            keyword_data = payload.get("data", {})
            for ln in keyword_data.get("line_numbers", []) or []:
                if isinstance(ln, int):
                    keyword_lines[ln] = keyword_lines.get(ln, 0) + 1

        combined_lines = set(topic_lines.keys()) | set(keyword_lines.keys()) | set(semantic_lines.keys())
        if not combined_lines:
            dimension_outputs.append({
                "name": name,
                "intent": intent,
                "evidence": [],
                "counter_evidence": [],
                "coverage": {
                    "topic_seeds": topic_seeds,
                    "keyword_seeds": keyword_seeds,
                    "semantic_queries": semantic_queries,
                    "counter_queries": counter_queries,
                },
                "omitted_count": 0,
                "next_cursor": None,
                "min_evidence": min_evidence,
            })
            continue

        def _score(line_num: int) -> float:
            score = 0.0
            if line_num in topic_lines or line_num in keyword_lines:
                score += kw_weight
            if line_num in semantic_lines:
                score += sem_weight * semantic_lines[line_num]
            if line_num in high_info_lines:
                score += 0.15
            return score

        ranked_lines = sorted(combined_lines, key=lambda ln: (_score(ln), -ln), reverse=True)
        desired = min(max_per_dimension, remaining_budget)
        selected_lines = ranked_lines[:desired]
        omitted_count = max(0, len(combined_lines) - len(selected_lines))

        messages = index_loader.get_messages_by_lines(
            selected_lines,
            context_before=context_before,
            context_after=context_after,
        )
        formatted_messages: List[Dict[str, Any]] = []
        for msg in messages:
            if not msg.get("is_match"):
                continue
            raw = msg.get("content", "")
            sender, body = _parse_sender_content(raw)
            full_content = body
            if _CHATLOG_MAX_CONTENT_CHARS > 0 and len(full_content) > _CHATLOG_MAX_CONTENT_CHARS:
                full_content = full_content[:_CHATLOG_MAX_CONTENT_CHARS] + "…"
            snippet = _build_snippet(full_content, snippet_chars)
            mentions_target = False
            if target_person:
                mentions_target = target_person in (sender or "") or target_person in full_content
            score = _score(msg.get("line_number", 0))
            formatted_messages.append({
                "line": msg.get("line_number"),
                "time": (msg.get("timestamp") or "")[:19],
                "sender": sender or "未知",
                "content": full_content,
                "snippet": snippet,
                "topics": msg.get("topics", []),
                "metadata": msg.get("metadata", {}),
                "score": round(score, 4),
                "dimension": name,
                "mentions_target": mentions_target,
                "is_counter": False,
            })

        formatted_messages.sort(key=lambda m: (m.get("mentions_target"), m.get("score")), reverse=True)
        formatted_messages = formatted_messages[:desired]
        remaining_budget -= len(formatted_messages)

        counter_evidence: List[Dict[str, Any]] = []
        counter_store: List[Dict[str, Any]] = []
        if use_semantic and counter_queries and semantic_index.is_available():
            counter_lines: Dict[int, float] = {}
            counter_top_k = min(_CHATLOG_MAX_LIST_ITEMS, max(5, int(max_per_dimension / 2)))
            for query in counter_queries:
                for line_num, score in semantic_index.search(query, top_k=counter_top_k):
                    counter_lines[line_num] = max(
                        counter_lines.get(line_num, 0.0),
                        max(0.0, min(1.0, (score + 1.0) / 2.0)),
                    )
            counter_candidates = [ln for ln in counter_lines.keys() if ln not in selected_lines]
            if counter_candidates:
                counter_messages = index_loader.get_messages_by_lines(
                    counter_candidates[:counter_top_k],
                    context_before=0,
                    context_after=0,
                )
                for msg in counter_messages:
                    if not msg.get("is_match"):
                        continue
                    raw = msg.get("content", "")
                    sender, body = _parse_sender_content(raw)
                    full_content = body
                    if _CHATLOG_MAX_CONTENT_CHARS > 0 and len(full_content) > _CHATLOG_MAX_CONTENT_CHARS:
                        full_content = full_content[:_CHATLOG_MAX_CONTENT_CHARS] + "…"
                    snippet = _build_snippet(full_content, snippet_chars)
                    counter_store.append({
                        "line": msg.get("line_number"),
                        "time": (msg.get("timestamp") or "")[:19],
                        "sender": sender or "未知",
                        "content": full_content,
                        "snippet": snippet,
                        "topics": msg.get("topics", []),
                        "metadata": msg.get("metadata", {}),
                        "score": round(counter_lines.get(msg.get("line_number"), 0.0), 4),
                        "dimension": name,
                        "mentions_target": (
                            target_person in (sender or "") or target_person in full_content
                        ) if target_person else False,
                        "is_counter": True,
                    })
                    counter_evidence.append({
                        "line": msg.get("line_number"),
                        "time": (msg.get("timestamp") or "")[:19],
                        "sender": sender or "未知",
                        "snippet": snippet,
                        "score": round(counter_lines.get(msg.get("line_number"), 0.0), 4),
                        "is_counter": True,
                    })
            counter_evidence = counter_evidence[:max(1, int(max_per_dimension / 3))]

        evidence_store.extend(formatted_messages)
        evidence_store.extend(counter_store)

        dimension_outputs.append({
            "name": name,
            "intent": intent,
            "evidence": [
                {
                    "line": m.get("line"),
                    "time": m.get("time"),
                    "sender": m.get("sender"),
                    "snippet": m.get("snippet"),
                    "topics": m.get("topics", []),
                    "score": m.get("score"),
                }
                for m in formatted_messages
            ],
            "counter_evidence": counter_evidence,
            "coverage": {
                "topic_seeds": topic_seeds,
                "keyword_seeds": keyword_seeds,
                "semantic_queries": semantic_queries,
                "counter_queries": counter_queries,
            },
            "omitted_count": omitted_count,
            "next_cursor": None if omitted_count == 0 else f"dimension:{name}#offset={desired}",
            "min_evidence": min_evidence,
        })

    # Step: Optionally compress messages using Poe small model
    use_compression = bool(args.get("use_compression", True))
    if use_compression and evidence_store:
        cleaner = _get_cleaner()
        poe_client = cleaner._get_poe_client()
        if poe_client and poe_client.is_configured:
            try:
                evidence_store = await cleaner.compress_messages(
                    evidence_store,
                    question,
                    target_person=target_person,
                    max_output_messages=max_total_messages,
                    compression_ratio=0.5,
                )
                print(f"[RETRIEVE] ✓ 智能压缩: {len(evidence_store)} 条消息")
            except Exception as e:
                print(f"[RETRIEVE] 压缩失败, 使用原始数据: {e}")

    evidence_id = _store_evidence({
        "question": question,
        "target_person": target_person,
        "dimensions": dimensions,
        "messages": evidence_store,
    })

    data = {
        "evidence_id": evidence_id,
        "dimensions": dimension_outputs,
        "limits": {
            "max_per_dimension": max_per_dimension,
            "max_total_messages": max_total_messages,
            "snippet_chars": snippet_chars,
            "context_window": f"±{context_before}/{context_after}",
        },
        "inputs": {
            "question": question,
            "target_person": target_person,
        },
    }
    meta = {
        "available": True,
        "source": "retrieve",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="retrieve_evidence")


async def _analyze_evidence_impl(args: dict) -> dict:
    started = time.time()
    evidence_id = args.get("evidence_id")
    messages = args.get("messages") or []
    question = args.get("question", "")
    target_person = args.get("target_person")
    max_examples = min(int(args.get("max_examples", 3)), 5)
    use_llm_analysis = bool(args.get("use_llm_analysis", True))  # 使用 Poe 小模型生成智能分析

    stored = _get_evidence(evidence_id) if evidence_id else None
    if stored:
        messages = stored.get("messages", []) or []
        question = question or stored.get("question", "")
        target_person = target_person or stored.get("target_person")
        dimensions = stored.get("dimensions", []) or []
    else:
        dimensions = args.get("dimensions") or []

    if not messages:
        return _error(
            "请提供 evidence_id 或消息列表",
            meta={"source": "analysis"},
            tool_name="analyze_evidence"
        )

    if not dimensions:
        dimensions = [{
            "name": "综合证据",
            "intent": "",
            "min_evidence": 3,
        }]
        for msg in messages:
            msg.setdefault("dimension", "综合证据")

    matrix: List[Dict[str, Any]] = []
    sender_counts: Dict[str, int] = {}
    for msg in messages:
        sender = msg.get("sender", "未知")
        sender_counts[sender] = sender_counts.get(sender, 0) + 1

    for dim in dimensions:
        name = dim.get("name") or "未命名维度"
        intent = dim.get("intent") or ""
        min_evidence = int(dim.get("min_evidence", 3))
        dim_messages = [m for m in messages if m.get("dimension") == name and not m.get("is_counter")]
        counter_messages = [m for m in messages if m.get("dimension") == name and m.get("is_counter")]

        dim_messages.sort(key=lambda m: (m.get("mentions_target"), m.get("score", 0)), reverse=True)
        counter_messages.sort(key=lambda m: m.get("score", 0), reverse=True)

        selected = dim_messages[:max_examples]
        counter_selected = counter_messages[:max(1, int(max_examples / 2))] if counter_messages else []

        topics_seen: List[str] = []
        for msg in selected:
            for topic in msg.get("topics", []) or []:
                if topic not in topics_seen:
                    topics_seen.append(topic)
            if len(topics_seen) >= 4:
                break

        if not selected:
            conclusion = "该维度证据不足，暂无法形成稳定结论。"
        elif counter_selected:
            conclusion = "该维度存在互相矛盾的信号，需要更多上下文确认倾向。"
        else:
            conclusion = "该维度证据相对集中，呈现出一致的倾向性。"

        gaps: List[str] = []
        if len(dim_messages) < min_evidence:
            gaps.append("证据数量不足")
        if target_person and not any(m.get("mentions_target") for m in dim_messages):
            gaps.append("证据中目标人物出现较少")
        if not counter_messages:
            gaps.append("缺少明确反证")

        if len(dim_messages) >= min_evidence + 2:
            confidence = "high"
        elif len(dim_messages) >= min_evidence:
            confidence = "medium"
        else:
            confidence = "low"

        matrix.append({
            "dimension": name,
            "intent": intent,
            "conclusion": conclusion,
            "evidence": [
                {
                    "line": m.get("line"),
                    "time": m.get("time"),
                    "sender": m.get("sender"),
                    "snippet": m.get("snippet") or _build_snippet(m.get("content", ""), _CHATLOG_EVIDENCE_SNIPPET_CHARS),
                }
                for m in selected
            ],
            "counter_evidence": [
                {
                    "line": m.get("line"),
                    "time": m.get("time"),
                    "sender": m.get("sender"),
                    "snippet": m.get("snippet") or _build_snippet(m.get("content", ""), _CHATLOG_EVIDENCE_SNIPPET_CHARS),
                }
                for m in counter_selected
            ],
            "reasoning": f"证据主要集中在: {', '.join(topics_seen) or '相关对话'}。",
            "gaps": gaps,
            "confidence": confidence,
        })

    # Step: Optionally use LLM for intelligent analysis
    llm_matrix = None
    if use_llm_analysis and matrix:
        cleaner = _get_cleaner()
        poe_client = cleaner._get_poe_client()
        if poe_client and poe_client.is_configured:
            try:
                llm_matrix = await cleaner.generate_evidence_matrix(
                    matrix,  # Pass the basic matrix as dimension_evidence
                    question,
                    target_person,
                )
                if llm_matrix and llm_matrix.get("method") == "llm":
                    # Merge LLM analysis into matrix
                    llm_dims = {d.get("name"): d for d in llm_matrix.get("dimensions", [])}
                    for m in matrix:
                        llm_dim = llm_dims.get(m.get("dimension"))
                        if llm_dim:
                            m["conclusion"] = llm_dim.get("conclusion", m.get("conclusion"))
                            m["reasoning"] = llm_dim.get("reasoning_chain", m.get("reasoning"))
                            if llm_dim.get("gaps"):
                                m["gaps"] = llm_dim.get("gaps")
                            if llm_dim.get("confidence"):
                                m["confidence"] = llm_dim.get("confidence")
            except Exception as e:
                print(f"[ANALYZE] LLM matrix generation failed: {e}")

    data = {
        "evidence_id": evidence_id,
        "matrix": matrix,
        "overview": {
            "message_count": len(messages),
            "sender_counts": sender_counts,
            "target_person": target_person,
        },
        "framework": _task_sub_questions(_infer_task_type(question)),
        "overall_conclusion": llm_matrix.get("overall_conclusion") if llm_matrix else None,
        "evidence_quality": llm_matrix.get("evidence_quality") if llm_matrix else None,
        "analysis_method": "llm" if (llm_matrix and llm_matrix.get("method") == "llm") else "rule_based",
        "disclaimer": "分析仅基于聊天记录证据，不构成最终决策建议。",
    }
    meta = {
        "available": True,
        "source": "analysis",
        "llm_used": bool(llm_matrix and llm_matrix.get("method") == "llm"),
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta, tool_name="analyze_evidence")


async def _search_person_impl(args: dict) -> dict:
    """Internal implementation of search_person."""
    person = args.get("person", "")
    include_context = bool(args.get("include_context", False))
    max_messages = min(int(args.get("max_messages", _CHATLOG_MAX_LIST_ITEMS)), 200)
    context_before = min(int(args.get("context_before", 1)), 3)
    context_after = min(int(args.get("context_after", 1)), 3)

    if not person:
        return _error(
            "错误：请提供人物名称。",
            meta={"source": "search_person"},
            tool_name="search_person"
        )

    loader = _get_loader()

    if not loader.is_loaded:
        if not loader.load():
            return _error(
                "错误：无法加载聊天记录文件",
                meta={"source": "search_person"},
                tool_name="search_person"
            )

    person_messages = loader.get_messages_by_sender(person)

    if not person_messages:
        return _success(
            {
                "person": person,
                "messages": [],
                "total_messages": 0,
                "returned_count": 0,
                "omitted_count": 0,
                "next_cursor": None,
            },
            meta={"source": "search_person", "available": True},
            tool_name="search_person"
        )

    line_numbers: List[int] = []
    if include_context:
        line_set = set()
        for msg in person_messages[:max_messages]:
            for ln in range(max(1, msg.line_number - context_before), msg.line_number + context_after + 1):
                line_set.add(ln)
        line_numbers = sorted(line_set)
    else:
        line_numbers = [msg.line_number for msg in person_messages[:max_messages]]

    items = []
    for ln in line_numbers:
        msg = loader.get_message(ln)
        if msg:
            items.append({
                "line": msg.line_number,
                "time": (msg.timestamp or "")[:19],
                "sender": msg.sender or "未知",
                "content": _build_snippet(msg.content or "", _CHATLOG_SNIPPET_CHARS),
                "is_match": msg.sender == person,
            })

    limited, omitted_count, next_cursor = _truncate_list(
        items,
        max_messages,
        cursor_prefix=f"person:{person}"
    )

    data = {
        "person": person,
        "messages": limited,
        "total_messages": len(person_messages),
        "returned_count": len(limited),
        "omitted_count": omitted_count,
        "next_cursor": next_cursor,
        "include_context": include_context,
    }
    meta = {
        "available": True,
        "source": "search_person",
    }
    return _success(data, meta=meta, tool_name="search_person")


# Tool-decorated versions (for MCP)
@tool(
    "get_chatlog_stats",
    "获取聊天记录的统计信息，包括总消息数、发送者列表等。",
    {}
)
async def get_chatlog_stats(args: dict) -> dict:
    """Get statistics about the loaded chatlog."""
    return await _get_chatlog_stats_impl(args)


@tool(
    "search_person",
    "搜索特定人物的所有相关消息记录。",
    {
        "person": str,            # 人物名称
        "include_context": bool,  # 可选：是否包含上下文（默认false）
        "max_messages": int,
        "context_before": int,
        "context_after": int
    }
)
async def search_person(args: dict) -> dict:
    """Search for all messages related to a specific person."""
    return await _search_person_impl(args)


@tool(
    "list_topics",
    "列出聊天记录索引中的话题标签。",
    {
        "limit": int,
        "pattern": str
    }
)
async def list_topics(args: dict) -> dict:
    return await _list_topics_impl(args)


@tool(
    "search_by_topics",
    "根据话题标签检索消息行号。",
    {
        "topics": list,
        "max_results": int
    }
)
async def search_by_topics(args: dict) -> dict:
    return await _search_by_topics_impl(args)


@tool(
    "search_by_keywords",
    "根据关键词全文检索消息行号。可限定发送者。",
    {
        "keywords": list,
        "target_person": str,
        "max_results": int,
        "match_all": bool
    }
)
async def search_by_keywords(args: dict) -> dict:
    return await _search_by_keywords_impl(args)


@tool(
    "load_messages",
    "根据行号加载消息内容，可选包含上下文与元数据。",
    {
        "line_numbers": list,
        "context_before": int,
        "context_after": int,
        "include_metadata": bool,
        "max_messages": int,
        "max_content_chars": int
    }
)
async def load_messages(args: dict) -> dict:
    return await _load_messages_impl(args)


@tool(
    "expand_query",
    "将问题扩展为关键词和话题标签（LLM 可选）。",
    {
        "question": str,
        "target_person": str,
        "use_llm": bool
    }
)
async def expand_query(args: dict) -> dict:
    return await _expand_query_impl(args)


@tool(
    "search_semantic",
    "使用语义向量召回相似消息。",
    {
        "query": str,
        "top_k": int
    }
)
async def search_semantic(args: dict) -> dict:
    return await _search_semantic_impl(args)


@tool(
    "filter_by_person",
    "过滤消息，确保内容与目标人物相关。",
    {
        "messages": list,
        "target_person": str,
        "use_llm": bool
    }
)
async def filter_by_person(args: dict) -> dict:
    return await _filter_by_person_impl(args)


@tool(
    "format_messages",
    "格式化消息列表为文本。",
    {
        "messages": list,
        "format": str,
        "max_chars": int
    }
)
async def format_messages(args: dict) -> dict:
    return await _format_messages_impl(args)


@tool(
    "parse_task",
    "解析用户问题为任务类型与证据维度计划。",
    {
        "question": str,
        "target_person": str,
        "use_llm": bool,
        "max_dimensions": int
    }
)
async def parse_task(args: dict) -> dict:
    return await _parse_task_impl(args)


@tool(
    "retrieve_evidence",
    "按维度检索证据，返回证据摘要与 evidence_id。",
    {
        "question": str,
        "target_person": str,
        "dimensions": list,
        "max_per_dimension": int,
        "max_total_messages": int,
        "snippet_chars": int,
        "context_before": int,
        "context_after": int,
        "use_semantic": bool,
        "use_llm_plan": bool
    }
)
async def retrieve_evidence(args: dict) -> dict:
    return await _retrieve_evidence_impl(args)


@tool(
    "analyze_evidence",
    "基于 evidence_id 或证据列表输出证据矩阵。",
    {
        "evidence_id": str,
        "messages": list,
        "question": str,
        "target_person": str,
        "dimensions": list,
        "max_examples": int
    }
)
async def analyze_evidence(args: dict) -> dict:
    return await _analyze_evidence_impl(args)


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Server Creation
# ═══════════════════════════════════════════════════════════════════════════════

def create_chatlog_mcp_server(chatlog_path: Optional[str] = None):
    """
    Create the Chatlog MCP server.
    
    Args:
        chatlog_path: Optional path to chatlog JSONL file
        
    Returns:
        An MCP server that can be passed to ClaudeAgentOptions.mcp_servers
    """
    global _chatlog_loader
    
    # Initialize loader with custom path if provided
    if chatlog_path:
        _chatlog_loader = ChatlogLoader(chatlog_path)
    
    tool_profile = os.getenv("CHATLOG_TOOL_PROFILE", "slim").lower()
    core_tools = [parse_task, retrieve_evidence, analyze_evidence]
    if tool_profile in ("full", "debug"):
        tools = [
            get_chatlog_stats,
            search_person,
            list_topics,
            search_by_topics,
            search_by_keywords,
            load_messages,
            expand_query,
            search_semantic,
            filter_by_person,
            format_messages,
            *core_tools,
        ]
    elif tool_profile == "stats":
        tools = [get_chatlog_stats, *core_tools]
    else:
        tools = core_tools

    return create_sdk_mcp_server(
        name="chatlog",
        version="1.0.0",
        tools=tools,
    )


def get_chatlog_tools_info() -> List[Dict[str, str]]:
    """Get information about available chatlog tools for documentation."""
    tool_profile = os.getenv("CHATLOG_TOOL_PROFILE", "slim").lower()
    tools = [
        {
            "name": "mcp__chatlog__parse_task",
            "description": "解析问题为任务类型与证据维度计划",
            "usage": "入口：生成证据维度计划"
        },
        {
            "name": "mcp__chatlog__retrieve_evidence",
            "description": "按维度检索证据并返回 evidence_id",
            "usage": "检索证据摘要，避免大文本回传"
        },
        {
            "name": "mcp__chatlog__analyze_evidence",
            "description": "基于 evidence_id 产出证据矩阵",
            "usage": "输出维度结论、证据与反证"
        },
    ]

    if tool_profile in ("full", "debug", "stats"):
        tools = [
            {
                "name": "mcp__chatlog__get_chatlog_stats",
                "description": "获取聊天记录统计信息",
                "usage": "查看聊天记录概况时调用"
            },
            *tools,
        ]

    if tool_profile in ("full", "debug"):
        tools = [
            *tools,
            {
                "name": "mcp__chatlog__search_person",
                "description": "搜索特定人物的消息记录",
                "usage": "需要了解某个人的历史消息时调用"
            },
            {
                "name": "mcp__chatlog__list_topics",
                "description": "列出聊天记录索引中的话题标签",
                "usage": "调试可用话题范围"
            },
            {
                "name": "mcp__chatlog__search_by_topics",
                "description": "按话题标签返回匹配行号",
                "usage": "调试话题索引召回"
            },
            {
                "name": "mcp__chatlog__search_by_keywords",
                "description": "按关键词检索消息行号",
                "usage": "调试关键词召回"
            },
            {
                "name": "mcp__chatlog__load_messages",
                "description": "按行号加载消息与上下文",
                "usage": "调试消息加载"
            },
            {
                "name": "mcp__chatlog__expand_query",
                "description": "将问题扩展为关键词和话题",
                "usage": "调试关键词/话题扩展"
            },
            {
                "name": "mcp__chatlog__search_semantic",
                "description": "语义向量召回相似消息",
                "usage": "调试语义召回"
            },
            {
                "name": "mcp__chatlog__filter_by_person",
                "description": "过滤与目标人物相关的消息",
                "usage": "调试人名归因"
            },
            {
                "name": "mcp__chatlog__format_messages",
                "description": "格式化消息列表为文本",
                "usage": "调试格式化输出"
            },
        ]

    return tools


async def close_chatlog_clients() -> None:
    """Close any chatlog-related async clients (e.g., Poe session)."""
    global _chatlog_cleaner
    if _chatlog_cleaner is None:
        return
    try:
        await _chatlog_cleaner.close()
    except Exception:
        pass
    _chatlog_cleaner = None


# ═══════════════════════════════════════════════════════════════════════════════
# Synchronous API for direct usage
# ═══════════════════════════════════════════════════════════════════════════════

def compose_chatlog_query_sync(
    question: str,
    target_person: Optional[str] = None,
    max_results: int = 100
) -> str:
    """Synchronous wrapper for composed chatlog query (internal use)."""
    args = {
        "question": question,
        "target_person": target_person,
        "max_results": max_results
    }
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(_query_chatlog_composed_impl(args))
    
    # Extract text from result
    if "content" in result and result["content"]:
        return result["content"][0].get("text", "")
    return str(result)


def compose_chatlog_analysis_sync(
    question: str,
    target_person: Optional[str] = None,
    max_dimensions: int = 4
) -> str:
    """Synchronous wrapper for the parse->retrieve->analyze flow."""
    args = {
        "question": question,
        "target_person": target_person,
        "max_dimensions": max_dimensions,
    }

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    parse_result = loop.run_until_complete(_parse_task_impl(args))
    parse_payload = _extract_payload(parse_result)
    parse_data = parse_payload.get("data", {})
    dimensions = parse_data.get("dimensions", []) or []

    retrieve_result = loop.run_until_complete(_retrieve_evidence_impl({
        "question": question,
        "target_person": target_person,
        "dimensions": dimensions,
    }))
    retrieve_payload = _extract_payload(retrieve_result)
    retrieve_data = retrieve_payload.get("data", {})
    evidence_id = retrieve_data.get("evidence_id")

    analyze_result = loop.run_until_complete(_analyze_evidence_impl({
        "evidence_id": evidence_id,
        "question": question,
        "target_person": target_person,
        "dimensions": dimensions,
    }))
    analyze_payload = _extract_payload(analyze_result)
    analyze_data = analyze_payload.get("data", {})

    lines: List[str] = []
    lines.append("## 证据分析")
    lines.append("")
    lines.append(f"**问题**: {question}")
    if target_person:
        lines.append(f"**目标人物**: {target_person}")
    lines.append(f"**evidence_id**: {evidence_id or '无'}")
    lines.append("")

    for item in analyze_data.get("matrix", []):
        lines.append(f"### {item.get('dimension', '未命名维度')}")
        lines.append(f"- 结论: {item.get('conclusion', '')}")
        lines.append(f"- 置信度: {item.get('confidence', '')}")
        lines.append(f"- 推断: {item.get('reasoning', '')}")
        gaps = item.get("gaps") or []
        if gaps:
            lines.append(f"- 缺口: {', '.join(gaps)}")

        evidence = item.get("evidence") or []
        if evidence:
            lines.append("- 证据:")
            for ev in evidence:
                snippet = ev.get("snippet", "")
                sender = ev.get("sender", "未知")
                line_no = ev.get("line")
                lines.append(f"  - [{line_no}] {sender}: {snippet}")

        counter = item.get("counter_evidence") or []
        if counter:
            lines.append("- 反证:")
            for ev in counter:
                snippet = ev.get("snippet", "")
                sender = ev.get("sender", "未知")
                line_no = ev.get("line")
                lines.append(f"  - [{line_no}] {sender}: {snippet}")

        lines.append("")

    return "\n".join(lines).strip()


def get_chatlog_stats_sync() -> str:
    """Synchronous wrapper for get_chatlog_stats."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(_get_chatlog_stats_impl({}))
    
    # Extract text from result
    if "content" in result and result["content"]:
        return result["content"][0].get("text", "")
    return str(result)


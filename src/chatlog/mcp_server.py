"""
Chatlog MCP Server for BENEDICTJUN Agent

Provides MCP tools for intelligent chatlog retrieval:
- get_chatlog_stats: Get statistics about loaded chatlog
- search_person: Search messages from a specific person
- atomic tools for topic/keyword/semantic retrieval
"""

import os
import json
import time
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

_CHATLOG_MAX_RETURN_CHARS = int(os.getenv("CHATLOG_MAX_RETURN_CHARS", "4000"))
_CHATLOG_INDEX_MAX_RESULTS = int(os.getenv("CHATLOG_INDEX_MAX_RESULTS", "200"))
_CHATLOG_INDEX_CONTEXT_BEFORE = int(os.getenv("CHATLOG_INDEX_CONTEXT_BEFORE", "2"))
_CHATLOG_INDEX_CONTEXT_AFTER = int(os.getenv("CHATLOG_INDEX_CONTEXT_AFTER", "2"))


def _cap_text(text: str, max_chars: int) -> str:
    """Cap tool output to prevent context overflow."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...(已截断)"

def _build_response(
    ok: bool,
    data: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    is_error: bool = False
) -> Dict[str, Any]:
    payload = {
        "ok": ok,
        "data": data,
        "meta": meta or {}
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        **({"is_error": True} if is_error else {})
    }


def _success(data: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _build_response(True, data, meta=meta, is_error=False)


def _error(message: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {"error": message}
    return _build_response(False, payload, meta=meta, is_error=True)


def _parse_sender_content(content: str) -> Tuple[str, str]:
    if ": " in content:
        sender, body = content.split(": ", 1)
        return sender, body
    return "", content



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
    sem_top_k = int(os.getenv("CHATLOG_SEM_TOP_K", "50"))
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
        sem_top_k = int(os.getenv("CHATLOG_SEM_TOP_K", "50"))
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
            return {
                "content": [{
                    "type": "text",
                    "text": f"错误：无法加载聊天记录文件 {loader.file_path}"
                }]
            }
    
    stats = loader.get_stats()
    
    output = "## 聊天记录统计\n\n"
    output += f"**文件路径**: {stats['file_path']}\n"
    output += f"**总消息数**: {stats['total_messages']}\n"
    output += f"\n### 发送者统计\n\n"
    
    for sender, count in stats['sender_message_counts'].items():
        output += f"- **{sender}**: {count} 条消息\n"
    
    output = _cap_text(output, _CHATLOG_MAX_RETURN_CHARS)
    return {
        "content": [{
            "type": "text",
            "text": output
        }]
    }


async def _list_topics_impl(args: dict) -> dict:
    started = time.time()
    limit = int(args.get("limit", 100))
    pattern = (args.get("pattern") or "").strip()

    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error(
            "无法加载索引",
            meta={
                "available": False,
                "source": "index",
                "timing_ms": int((time.time() - started) * 1000)
            }
        )

    topics = index_loader.available_topics
    if pattern:
        pattern_lower = pattern.lower()
        topics = [t for t in topics if pattern_lower in t.lower()]

    topics_sorted = sorted(topics)
    data = {
        "topics": topics_sorted[:limit],
        "total_count": len(index_loader.available_topics),
        "returned_count": min(len(topics_sorted), limit),
        "pattern": pattern or None,
    }
    meta = {
        "available": True,
        "source": "index",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta)


async def _search_by_topics_impl(args: dict) -> dict:
    started = time.time()
    topics = args.get("topics") or []
    max_results = min(int(args.get("max_results", 100)), 500)

    if not topics:
        return _error("请提供至少一个话题", meta={"source": "index"})

    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error(
            "无法加载索引",
            meta={
                "available": False,
                "source": "index",
                "timing_ms": int((time.time() - started) * 1000)
            }
        )

    all_lines: set[int] = set()
    breakdown: Dict[str, int] = {}
    for topic in topics:
        lines = index_loader.search_by_topic_exact(topic)
        breakdown[topic] = len(lines)
        all_lines.update(lines)

    line_numbers = sorted(all_lines)[:max_results]
    data = {
        "line_numbers": line_numbers,
        "total_matches": len(all_lines),
        "topic_breakdown": breakdown,
    }
    meta = {
        "available": True,
        "source": "index",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta)


async def _search_by_keywords_impl(args: dict) -> dict:
    started = time.time()
    keywords = args.get("keywords") or []
    target_person = args.get("target_person")
    max_results = min(int(args.get("max_results", 100)), 500)
    match_all = bool(args.get("match_all", False))

    if not keywords:
        return _error("请提供至少一个关键词", meta={"source": "scan"})

    loader = _get_loader()
    if not loader.load():
        return _error(
            "无法加载聊天记录",
            meta={
                "available": False,
                "source": "scan",
                "timing_ms": int((time.time() - started) * 1000)
            }
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

    data = {
        "line_numbers": matched_lines[:max_results],
        "total_matches": len(matched_lines),
        "keyword_breakdown": keyword_hits,
        "person_filter": target_person,
        "match_all": match_all,
    }
    meta = {
        "available": True,
        "source": "scan",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta)


async def _load_messages_impl(args: dict) -> dict:
    started = time.time()
    line_numbers = args.get("line_numbers") or []
    context_before = min(int(args.get("context_before", 0)), 10)
    context_after = min(int(args.get("context_after", 0)), 10)
    include_metadata = bool(args.get("include_metadata", False))

    if not line_numbers:
        return _error("请提供行号列表", meta={"source": "index"})

    cleaned_lines = []
    for ln in line_numbers[:200]:
        try:
            cleaned_lines.append(int(ln))
        except (TypeError, ValueError):
            continue
    if not cleaned_lines:
        return _error("行号格式无效", meta={"source": "index"})

    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error(
            "无法加载索引",
            meta={
                "available": False,
                "source": "index",
                "timing_ms": int((time.time() - started) * 1000)
            }
        )

    messages = index_loader.get_messages_by_lines(
        cleaned_lines,
        context_before=context_before,
        context_after=context_after,
    )
    result = []
    for msg in messages:
        raw = msg.get("content", "")
        sender, body = _parse_sender_content(raw)
        item = {
            "line": msg.get("line_number"),
            "time": (msg.get("timestamp") or "")[:19],
            "sender": sender or "未知",
            "content": body,
            "is_match": bool(msg.get("is_match")),
        }
        if include_metadata:
            item["metadata"] = msg.get("metadata", {})
        result.append(item)

    data = {
        "messages": result,
        "count": len(result),
        "context": f"±{context_before}/{context_after}",
    }
    meta = {
        "available": True,
        "source": "index",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta)


async def _expand_query_impl(args: dict) -> dict:
    started = time.time()
    question = args.get("question", "")
    target_person = args.get("target_person")
    use_llm = bool(args.get("use_llm", True))

    if not question:
        return _error("请提供问题", meta={"source": "llm"})

    index_loader = get_index_loader()
    available_topics = index_loader.available_topics if index_loader.load_index() else []

    cleaner = _get_cleaner()
    poe_client = cleaner._get_poe_client()
    llm_available = bool(poe_client and poe_client.is_configured)

    if use_llm and llm_available:
        keywords, metadata = await cleaner.expand_query(
            question, target_person, available_topics
        )
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

    data = {
        "keywords": keywords,
        "topics": metadata.get("topics", []),
        "sentiment": metadata.get("sentiment"),
        "information_density": metadata.get("information_density"),
        "method": method,
        "model": model,
        "llm_available": llm_available,
    }
    meta = {
        "available": True,
        "source": "llm" if method == "llm" else "rule_based",
        "llm_used": llm_used,
        "model": model,
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta)


async def _search_semantic_impl(args: dict) -> dict:
    started = time.time()
    query = args.get("query", "")
    top_k = min(int(args.get("top_k", 50)), 200)

    if not query:
        return _error("请提供查询文本", meta={"source": "semantic"})

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
        return _success(data, meta=meta)

    raw_results = semantic_index.search(query, top_k=top_k)
    results = [
        {"line": ln, "score": round((score + 1.0) / 2.0, 4)}
        for ln, score in raw_results
    ]
    data = {
        "available": True,
        "results": results,
        "count": len(results),
        "query": query,
    }
    meta = {
        "available": True,
        "source": "semantic",
        "timing_ms": int((time.time() - started) * 1000),
    }
    return _success(data, meta=meta)


async def _filter_by_person_impl(args: dict) -> dict:
    started = time.time()
    messages = args.get("messages") or []
    target_person = args.get("target_person", "")
    use_llm = bool(args.get("use_llm", True))

    if not messages:
        return _error("请提供消息列表", meta={"source": "llm"})
    if not target_person:
        return _error("请提供目标人物", meta={"source": "llm"})

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
    return _success(data, meta=meta)


async def _format_messages_impl(args: dict) -> dict:
    started = time.time()
    messages = args.get("messages") or []
    fmt = args.get("format", "compact")
    max_chars = min(int(args.get("max_chars", _CHATLOG_MAX_RETURN_CHARS)), 10000)

    if not messages:
        return _error("请提供消息列表", meta={"source": "format"})

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
    return _success(data, meta=meta)


async def _search_person_impl(args: dict) -> dict:
    """Internal implementation of search_person."""
    person = args.get("person", "")
    include_context = args.get("include_context", True)
    
    if not person:
        return {
            "content": [{
                "type": "text",
                "text": "错误：请提供人物名称。"
            }]
        }
    
    loader = _get_loader()
    
    if not loader.is_loaded:
        if not loader.load():
            return {
                "content": [{
                    "type": "text",
                    "text": "错误：无法加载聊天记录文件"
                }]
            }
    
    # Get messages from this person
    person_messages = loader.get_messages_by_sender(person)
    
    if not person_messages:
        return {
            "content": [{
                "type": "text",
                "text": f"未找到「{person}」的消息记录。"
            }]
        }
    
    # Build result
    output = f"## 关于「{person}」的消息记录\n\n"
    output += f"**总消息数**: {len(person_messages)}\n"
    output += f"---\n\n"
    
    if include_context:
        # Get context for each message
        all_line_numbers = set()
        for msg in person_messages[:50]:  # Limit to avoid too much data
            for ln in range(max(1, msg.line_number - 2), msg.line_number + 3):
                all_line_numbers.add(ln)
        
        for ln in sorted(all_line_numbers):
            msg = loader.get_message(ln)
            if msg:
                output += msg.format_simple() + "\n"
    else:
        # Just the person's messages
        for msg in person_messages[:100]:
            output += msg.format_simple() + "\n"
    
    return {
        "content": [{
            "type": "text",
            "text": output
        }]
    }


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
        "include_context": bool   # 可选：是否包含上下文（默认true）
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
        "include_metadata": bool
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
    
    return create_sdk_mcp_server(
        name="chatlog",
        version="1.0.0",
        tools=[
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
        ]
    )


def get_chatlog_tools_info() -> List[Dict[str, str]]:
    """Get information about available chatlog tools for documentation."""      
    return [
        {
            "name": "mcp__chatlog__get_chatlog_stats",
            "description": "获取聊天记录统计信息",
            "usage": "查看聊天记录概况时调用"
        },
        {
            "name": "mcp__chatlog__search_person",
            "description": "搜索特定人物的消息记录",
            "usage": "需要了解某个人的历史消息时调用"
        },
        {
            "name": "mcp__chatlog__list_topics",
            "description": "列出聊天记录索引中的话题标签",
            "usage": "了解可用话题范围时调用"
        },
        {
            "name": "mcp__chatlog__search_by_topics",
            "description": "按话题标签返回匹配行号",
            "usage": "已有话题标签时快速缩小范围"
        },
        {
            "name": "mcp__chatlog__search_by_keywords",
            "description": "按关键词检索消息行号",
            "usage": "需要精确关键词匹配时调用"
        },
        {
            "name": "mcp__chatlog__load_messages",
            "description": "按行号加载消息与上下文",
            "usage": "在已有行号时获取原始内容"
        },
        {
            "name": "mcp__chatlog__expand_query",
            "description": "将问题扩展为关键词和话题",
            "usage": "问题模糊或需要话题建议时调用"
        },
        {
            "name": "mcp__chatlog__search_semantic",
            "description": "语义向量召回相似消息",
            "usage": "语义检索或宽泛问题召回时调用"
        },
        {
            "name": "mcp__chatlog__filter_by_person",
            "description": "过滤与目标人物相关的消息",
            "usage": "需要保证人名归因时调用"
        },
        {
            "name": "mcp__chatlog__format_messages",
            "description": "格式化消息列表为文本",
            "usage": "需要固定格式输出时调用"
        }
    ]


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


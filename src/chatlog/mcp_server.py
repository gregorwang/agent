"""
Chatlog MCP Server for BENEDICTJUN Agent

Provides MCP tools for intelligent chatlog retrieval:
- query_chatlog: Main query tool with keyword expansion and cleaning
- get_chatlog_stats: Get statistics about loaded chatlog
- search_person: Search messages from a specific person
"""

import os
import asyncio
from typing import Optional, Dict, Any, List

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
    "query_chatlog",
    "基于问题智能检索聊天记录。会自动扩展关键词、提取上下文、清洗结果。适合回答需要基于历史聊天记录的问题。",
    {
        "question": str,       # 用户的问题
        "target_person": str,  # 可选：目标人物名称
        "max_results": int     # 可选：最大结果数（默认100）
    }
)
async def query_chatlog(args: dict) -> dict:
    """Query the chatlog based on a question (uses indexed search)."""
    return await _query_chatlog_indexed_impl(args)


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
            query_chatlog,
            get_chatlog_stats,
            search_person,
        ]
    )


def get_chatlog_tools_info() -> List[Dict[str, str]]:
    """Get information about available chatlog tools for documentation."""
    return [
        {
            "name": "mcp__chatlog__query_chatlog",
            "description": "基于问题智能检索聊天记录",
            "usage": "当需要了解历史对话内容时调用"
        },
        {
            "name": "mcp__chatlog__get_chatlog_stats",
            "description": "获取聊天记录统计信息",
            "usage": "查看聊天记录概况时调用"
        },
        {
            "name": "mcp__chatlog__search_person",
            "description": "搜索特定人物的消息记录",
            "usage": "需要了解某个人的历史消息时调用"
        }
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Synchronous API for direct usage
# ═══════════════════════════════════════════════════════════════════════════════

def query_chatlog_sync(
    question: str,
    target_person: Optional[str] = None,
    max_results: int = 100
) -> str:
    """Synchronous wrapper for query_chatlog."""
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
    
    result = loop.run_until_complete(_query_chatlog_indexed_impl(args))
    
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


# Chatlog MCP 重构设计文档

> **状态**: 设计提案  
> **版本**: 2.0  
> **创建日期**: 2026-01-11  
> **作者**: Agent 综合分析

---

## 📋 目录

1. [执行摘要](#执行摘要)
2. [现状分析](#现状分析)
3. [问题诊断](#问题诊断)
4. [MCP 规范对照](#mcp-规范对照)
5. [重构方案](#重构方案)
6. [工具详细定义](#工具详细定义)
7. [Agent 调用示例](#agent-调用示例)
8. [实施路线图](#实施路线图)
9. [风险与缓解](#风险与缓解)

---

## 执行摘要

### 当前状态（已拆分）

Chatlog MCP Server 目前暴露原子工具集（不再提供 `query_chatlog`）：

| 工具 | 功能 |
|------|------|
| `get_chatlog_stats` | 数据集统计 |
| `search_person` | 按发送者过滤 |
| `list_topics` | 列出可用话题 |
| `search_by_topics` | 话题 → 行号 |
| `search_by_keywords` | 关键词 → 行号 |
| `load_messages` | 行号 → 消息内容 |
| `expand_query` | 问题 → 关键词/话题 |
| `search_semantic` | 语义向量召回 |
| `filter_by_person` | 实体归因过滤 |
| `format_messages` | 输出格式化 |

### 核心问题（历史）

原 `query_chatlog` 在单次调用中执行：
1. 查询扩展（调用小模型）
2. 话题/关键词识别
3. 索引检索
4. 语义向量召回
5. 上下文窗口加载
6. 实体归因过滤
7. 结果清洗/截断

**这是 Workflow，不是 MCP Tool。**

### 推荐方案

已完成拆分并移除 `query_chatlog`，只保留原子工具供 Agent 自主组合。

---

## 现状分析

### 当前代码结构

```
src/chatlog/
├── mcp_server.py          # MCP 工具定义
├── loader.py              # 聊天记录加载
├── searcher.py            # 搜索逻辑
├── cleaner.py             # LLM 驱动的清洗
├── metadata_index_loader.py # 话题索引
└── semantic_index.py      # 向量检索
```

### 原 `query_chatlog` 内部流程（已移除）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    query_chatlog 单次调用                                │
├─────────────────────────────────────────────────────────────────────────┤
│  [1] 加载索引 (MetadataIndexLoader)                                      │
│       ↓                                                                 │
│  [2] 查询扩展 (ChatlogCleaner.expand_query)  ← 隐藏的 LLM 调用！        │
│       ↓                                                                 │
│  [3] 话题索引检索 (O(1) 哈希查找)                                        │
│       ↓                                                                 │
│  [4] 语义向量召回 (可选，cosine 相似度)                                  │
│       ↓                                                                 │
│  [5] 分数融合排序 (kw_weight + sem_weight)                               │
│       ↓                                                                 │
│  [6] 加载消息 + 上下文窗口                                               │
│       ↓                                                                 │
│  [7] 实体归因过滤 (entity_attribution)  ← 又一个隐藏的 LLM 调用！       │
│       ↓                                                                 │
│  [8] 二次清洗截断 (clean_results)                                        │
│       ↓                                                                 │
│  [9] 返回最终文本                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 协议层合规性

从 MCP 协议角度看，当前实现是**合法的**：
- ✅ 使用 Claude Agent SDK 的 `@tool` 装饰器
- ✅ 正确创建 MCP Server
- ✅ 工具有明确的输入/输出

但从**设计原则**角度看，存在严重问题。

---

## 问题诊断

### 🔴 问题 1: Workflow 式单一入口

```python
# 当前实现 (mcp_server.py, Line 637-648)
@tool("query_chatlog", "基于问题智能检索聊天记录...")
async def query_chatlog(args: dict) -> dict:
    return await _query_chatlog_indexed_impl(args)  # 一个函数包揽一切
```

**影响**: 无论用户查询 "老王借了多少钱" 还是 "今天天气怎么样"，都执行相同的 9 步流程。

### 🔴 问题 2: 隐藏的 LLM 调用

```python
# cleaner.py, Line 111-248
async def expand_query(self, question, target_person, available_topics):
    poe_client = self._get_poe_client()
    if poe_client and poe_client.is_configured:
        response = await poe_client.generate(...)  # Agent 完全不知道这里调用了另一个模型！
```

**影响**: 
- Agent 无法知道内部使用了 Gemini-2.5-Flash-Lite
- Token 消耗不透明
- 无法选择跳过 LLM 步骤

### 🔴 问题 3: 不可组合

Agent 可能想要：
- 只做精确查询，跳过关键词扩展
- 只使用语义检索，跳过话题索引
- 增大上下文窗口获取更多背景
- 跳过 LLM 清洗以保留原始证据

**当前无法做到任何一项。**

### 🔴 问题 4: 黑盒输出

```python
return {
    "content": [{"type": "text", "text": result_text}]  # 只有最终文本
}
```

Agent 无法访问：
- 识别出的话题列表
- 匹配的原始消息行号
- 语义相似度分数
- 被过滤掉的消息及原因

---

## MCP 规范对照

根据 [Model Context Protocol 官方规范](https://modelcontextprotocol.io/)：

| 原则 | 定义 | 当前状态 |
|------|------|----------|
| **原子性** | 每个工具执行一个明确操作 | ❌ 9 步串行 |
| **透明性** | Agent 理解工具行为 | ❌ 隐藏 LLM 调用 |
| **可组合性** | 工具可自由组合 | ❌ 固定管道 |
| **最小权限** | 只返回必要信息 | ❌ 总是完整处理 |
| **Agent 可控** | Agent 决定调用策略 | ❌ 策略硬编码 |

### Claude Agent SDK 实践要点（基于官方文档）

- MCP 工具返回结构应为 `{"content": [{"type": "text", "text": "..."}]}`。
- 遇到工具内部错误建议返回 `is_error: true`，避免 Agent 误解为成功结果。
- MCP server 注册时保持 `name`/`version` 稳定，工具名由 `mcp__<server>__<tool>` 解析。
- 允许工具列表（`allowed_tools`）是可控的，拆分后更利于按任务精细授权。

以上要点与本重构方案一致，进一步支持“可组合、可控、可解释”的工具设计。

### 正确 vs 错误示例

```python
# ❌ 错误：Workflow 式工具
@tool("query_with_search_clean_and_format")
async def do_everything(args):
    step1_result = await expand_query(...)
    step2_result = await search_topics(...)
    step3_result = await load_messages(...)
    step4_result = await clean_results(...)
    return step4_result

# ✅ 正确：原子工具
@tool("search_by_topic")
async def search_by_topic(args):
    topic = args.get("topic")
    return {"line_numbers": index.search(topic)}
```

---

## 重构方案

### 新架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Chatlog MCP v2.0 - 原子工具集                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      🔵 基础工具层                              │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │ │
│  │  │ get_stats    │ │ list_topics  │ │ search_index │           │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘           │ │
│  │  ┌──────────────┐ ┌──────────────┐                            │ │
│  │  │ search_kw    │ │ load_messages│                            │ │
│  │  └──────────────┘ └──────────────┘                            │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      🟡 智能辅助层（可选）                      │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │ │
│  │  │ expand_query │ │ search_sem   │ │ entity_filter│           │ │
│  │  │ (LLM 可选)   │ │ (需要索引)   │ │ (LLM 可选)   │           │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘           │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      🟢 格式化层                                │ │
│  │  ┌──────────────┐ ┌──────────────────────────────────────────┐ │ │
│  │  └──────────────┘ └──────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 工具清单

| 编号 | 工具名 | 层级 | 功能 | LLM 依赖 |
|------|--------|------|------|----------|
| 1 | `get_chatlog_stats` | 基础 | 返回数据集统计 | ❌ |
| 2 | `list_topics` | 基础 | 列出可用话题 | ❌ |
| 3 | `search_by_topics` | 基础 | 话题 → 行号 | ❌ |
| 4 | `search_by_keywords` | 基础 | 关键词 → 行号 | ❌ |
| 5 | `load_messages` | 基础 | 行号 → 消息内容 | ❌ |
| 6 | `expand_query` | 智能 | 问题 → 关键词+话题 | ⚠️ 可选 |
| 7 | `search_semantic` | 智能 | 语义检索 | ❌ |
| 8 | `filter_by_person` | 智能 | 实体归因过滤 | ⚠️ 可选 |
| 9 | `format_messages` | 格式 | 结构化 → 文本 | ❌ |

---

## 结果结构与可复现性

### 统一响应结构（建议）

为避免 Agent 解析歧义，建议所有工具返回统一 JSON 结构，再包到 `content.text`：

```json
{
  "ok": true,
  "data": { },
  "meta": {
    "available": true,
    "llm_used": false,
    "model": null,
    "timing_ms": 0,
    "source": "index|semantic|scan"
  }
}
```

### 可复现模式

- 工具默认 `use_llm=false`（或提供全局开关），确保基础路径可复现。
- 若使用 LLM，必须在 `meta.llm_used/model` 显式标记来源与模型。
- 任何随机性应通过固定策略（排序/截断规则）保证输出稳定。

---

## 排序融合与去重规则（建议）

当 `search_by_topics` 与 `search_semantic` 合并时，建议明确：

1. **融合规则**：`score = kw_weight*kw_hit + sem_weight*sem_score`  
2. **去重规则**：按 `line_number` 去重，保留最高分版本  
3. **排序规则**：按 `score` 降序，若相同则 `line_number` 降序  
4. **窗口合并**：窗口重叠时合并为单一窗口，避免重复上下文  
5. **截断策略**：优先保留高分窗口，超限时丢弃低分窗口  

把这些规则固化为文档/实现，可以显著提升 Agent 的解释能力。

---

## 依赖与降级策略

- **索引不可用**：`list_topics/search_by_topics` 返回 `available=false`，建议回退到 `search_by_keywords`。
- **语义索引不可用**：`search_semantic` 返回 `available=false` 并给出构建建议。
- **LLM 不可用**：`expand_query/filter_by_person/clean_results` 自动降级为规则模式并标记 `method=rule_based`。

---

## 访问控制与最小披露

- `load_messages` 默认不返回元数据，仅在显式 `include_metadata=true` 时返回。
- `format_messages` 默认紧凑输出并强制 `max_chars` 上限。
- 对“需要原文证据”的回答，应让 Agent 先说明范围，再调用 `load_messages`。

---

## 工具详细定义

### 🔵 基础工具层

#### 1. `list_topics`

```python
@tool(
    "list_topics",
    "列出聊天记录索引中所有可用的话题标签。帮助 Agent 了解可搜索的范围。",
    {
        "limit": int,      # 可选：最多返回数量（默认100）
        "pattern": str     # 可选：模糊匹配模式
    }
)
async def list_topics(args: dict) -> dict:
    limit = args.get("limit", 100)
    pattern = args.get("pattern", "")
    
    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error("无法加载索引")
    
    topics = index_loader.available_topics
    if pattern:
        topics = [t for t in topics if pattern.lower() in t.lower()]
    
    return _success({
        "topics": sorted(topics)[:limit],
        "total_count": len(index_loader.available_topics),
        "returned_count": min(len(topics), limit)
    })
```

**输出示例**:
```json
{
  "topics": ["借贷", "工作", "家庭", "旅行", "健康"],
  "total_count": 156,
  "returned_count": 5
}
```

---

#### 2. `search_by_topics`

```python
@tool(
    "search_by_topics",
    "根据话题标签检索消息行号。使用预建索引，O(1) 时间复杂度。",
    {
        "topics": list,       # 话题列表（必填）
        "max_results": int    # 可选：最大返回数（默认100）
    }
)
async def search_by_topics(args: dict) -> dict:
    topics = args.get("topics", [])
    max_results = min(args.get("max_results", 100), 500)
    
    if not topics:
        return _error("请提供至少一个话题")
    
    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error("无法加载索引")
    
    all_lines = set()
    breakdown = {}
    
    for topic in topics:
        lines = index_loader.search_by_topic_exact(topic)
        breakdown[topic] = len(lines)
        all_lines.update(lines)
    
    return _success({
        "line_numbers": sorted(all_lines)[:max_results],
        "total_matches": len(all_lines),
        "topic_breakdown": breakdown
    })
```

**输出示例**:
```json
{
  "line_numbers": [123, 456, 789, 1024],
  "total_matches": 42,
  "topic_breakdown": {"借贷": 30, "金钱": 12}
}
```

---

#### 3. `search_by_keywords`

```python
@tool(
    "search_by_keywords",
    "根据关键词全文检索消息行号。可限定发送者。",
    {
        "keywords": list,     # 关键词列表（必填）
        "target_person": str, # 可选：限定发送者
        "max_results": int,   # 可选：最大返回数
        "match_all": bool     # 可选：是否要求匹配全部关键词
    }
)
async def search_by_keywords(args: dict) -> dict:
    keywords = args.get("keywords", [])
    target_person = args.get("target_person")
    max_results = min(args.get("max_results", 100), 500)
    match_all = args.get("match_all", False)
    
    if not keywords:
        return _error("请提供至少一个关键词")
    
    loader = _get_loader()
    if not loader.load():
        return _error("无法加载聊天记录")
    
    matched = []
    kw_hits = {kw: 0 for kw in keywords}
    
    for msg in loader.messages:
        content = msg.content.lower()
        
        if target_person and target_person.lower() not in msg.sender.lower():
            continue
        
        matches = [kw for kw in keywords if kw.lower() in content]
        
        if (match_all and len(matches) == len(keywords)) or (not match_all and matches):
            matched.append(msg.line_number)
            for kw in matches:
                kw_hits[kw] += 1
    
    return _success({
        "line_numbers": matched[:max_results],
        "total_matches": len(matched),
        "keyword_breakdown": kw_hits,
        "person_filter": target_person
    })
```

---

#### 4. `load_messages`

```python
@tool(
    "load_messages",
    "根据行号加载消息内容。可选包含上下文和元数据。",
    {
        "line_numbers": list,    # 行号列表（必填）
        "context_before": int,   # 可选：前置上下文条数（默认0，最大10）
        "context_after": int,    # 可选：后置上下文条数（默认0，最大10）
        "include_metadata": bool # 可选：是否包含元数据（默认false）
    }
)
async def load_messages(args: dict) -> dict:
    line_numbers = args.get("line_numbers", [])[:50]  # 限制数量
    context_before = min(args.get("context_before", 0), 10)
    context_after = min(args.get("context_after", 0), 10)
    include_metadata = args.get("include_metadata", False)
    
    if not line_numbers:
        return _error("请提供行号列表")
    
    index_loader = get_index_loader()
    if not index_loader.load_index():
        return _error("无法加载索引")
    
    messages = index_loader.get_messages_by_lines(
        line_numbers,
        context_before=context_before,
        context_after=context_after
    )
    
    result = []
    for msg in messages:
        item = {
            "line": msg.get("line_number"),
            "time": msg.get("timestamp", "")[:19],
            "sender": msg.get("sender", "未知"),
            "content": msg.get("content", ""),
            "is_match": msg.get("is_match", False)
        }
        if include_metadata:
            item["metadata"] = msg.get("metadata", {})
        result.append(item)
    
    return _success({
        "messages": result,
        "count": len(result),
        "context": f"±{context_before}/{context_after}"
    })
```

**输出示例**:
```json
{
  "messages": [
    {
      "line": 123,
      "time": "2024-01-15 14:30:00",
      "sender": "老王",
      "content": "那笔钱我下周还你",
      "is_match": true,
      "metadata": {"topics": ["借贷"], "sentiment": "neutral"}
    }
  ],
  "count": 1,
  "context": "±2/2"
}
```

---

### 🟡 智能辅助层

#### 5. `expand_query`

```python
@tool(
    "expand_query",
    "使用小模型将问题扩展为关键词和话题。可选工具，跳过则使用精确匹配。",
    {
        "question": str,           # 用户问题（必填）
        "target_person": str,      # 可选：目标人物
        "use_llm": bool            # 可选：是否使用 LLM（默认true）
    }
)
async def expand_query(args: dict) -> dict:
    question = args.get("question", "")
    target_person = args.get("target_person")
    use_llm = args.get("use_llm", True)
    
    if not question:
        return _error("请提供问题")
    
    index_loader = get_index_loader()
    available_topics = index_loader.available_topics if index_loader.load_index() else []
    
    cleaner = _get_cleaner()
    
    # 检查 LLM 可用性
    poe_client = cleaner._get_poe_client()
    llm_available = poe_client and poe_client.is_configured
    
    if use_llm and llm_available:
        keywords, metadata = await cleaner.expand_query(question, target_person, available_topics)
        method = "llm"
        model = cleaner.config.model
    else:
        keywords = cleaner._fallback_keyword_extraction(question, target_person, available_topics)
        metadata = cleaner._fallback_metadata_classification(question, available_topics)
        method = "rule_based"
        model = None
    
    return _success({
        "keywords": keywords,
        "topics": metadata.get("topics", []),
        "sentiment": metadata.get("sentiment"),
        "info_density": metadata.get("information_density"),
        "method": method,
        "model": model,
        "llm_available": llm_available
    })
```

**关键特性**: 透明地返回使用了哪个模型，让 Agent 知道扩展的来源。

---

#### 6. `search_semantic`

```python
@tool(
    "search_semantic",
    "使用语义向量召回相似消息。需要预建的 embeddings 缓存。",
    {
        "query": str,         # 查询文本（必填）
        "top_k": int          # 可选：返回数量（默认50）
    }
)
async def search_semantic(args: dict) -> dict:
    query = args.get("query", "")
    top_k = min(args.get("top_k", 50), 200)
    
    if not query:
        return _error("请提供查询文本")
    
    semantic_index = get_semantic_index()
    
    if not semantic_index.is_available():
        return _success({
            "available": False,
            "reason": "缺少 embeddings 缓存文件",
            "suggestion": "运行 python -m src.chatlog.semantic_index 构建索引",
            "results": []
        })
    
    raw_results = semantic_index.search(query, top_k=top_k)
    
    results = [
        {"line": ln, "score": round((score + 1) / 2, 4)}
        for ln, score in raw_results
    ]
    
    return _success({
        "available": True,
        "results": results,
        "count": len(results),
        "query": query
    })
```

---

#### 7. `filter_by_person`

```python
@tool(
    "filter_by_person",
    "使用实体归因逻辑过滤消息，确保只保留与目标人物相关的内容。",
    {
        "messages": list,      # 消息列表（来自 load_messages）
        "target_person": str,  # 目标人物（必填）
        "use_llm": bool        # 可选：是否使用 LLM 归因（默认true）
    }
)
async def filter_by_person(args: dict) -> dict:
    messages = args.get("messages", [])
    target_person = args.get("target_person", "")
    use_llm = args.get("use_llm", True)
    
    if not messages:
        return _error("请提供消息列表")
    if not target_person:
        return _error("请提供目标人物")
    
    if use_llm:
        # 调用 entity_attribution
        cleaner = _get_cleaner()
        text = "\n".join([f"[{m.get('time')}] {m.get('sender')}: {m.get('content')}" for m in messages])
        filtered_text, stats = await cleaner.entity_attribution(text, target_person, "")
        
        # 解析保留的消息
        kept = [m for m in messages if m.get("content", "") in filtered_text]
        excluded = [m for m in messages if m not in kept]
    else:
        # 简单的名称匹配
        kept = [m for m in messages if target_person in m.get("content", "") or target_person == m.get("sender")]
        excluded = [m for m in messages if m not in kept]
    
    return _success({
        "filtered_messages": kept,
        "kept_count": len(kept),
        "excluded_count": len(excluded),
        "method": "llm_attribution" if use_llm else "name_match",
        "target_person": target_person
    })
```

---

### 🟢 格式化层

#### 8. `format_messages`

```python
@tool(
    "format_messages",
    "将消息列表格式化为便于阅读的文本。支持多种格式。",
    {
        "messages": list,       # 消息列表（必填）
        "format": str,          # 可选："compact"（默认）, "detailed", "timeline"
        "max_chars": int        # 可选：最大字符数（默认4000）
    }
)
async def format_messages(args: dict) -> dict:
    messages = args.get("messages", [])
    fmt = args.get("format", "compact")
    max_chars = min(args.get("max_chars", 4000), 10000)
    
    if not messages:
        return _error("请提供消息列表")
    
    lines = []
    
    if fmt == "timeline":
        lines.append("## 时间线\n")
        current_date = None
        for m in messages:
            date = m.get("time", "")[:10]
            if date != current_date:
                current_date = date
                lines.append(f"\n### {date}\n")
            time = m.get("time", "")[11:16]
            lines.append(f"- **{time}** [{m.get('sender')}]: {m.get('content')}")
    
    elif fmt == "detailed":
        for m in messages:
            lines.append("---")
            lines.append(f"**行号**: {m.get('line')}")
            lines.append(f"**时间**: {m.get('time')}")
            lines.append(f"**发送者**: {m.get('sender')}")
            lines.append(f"**内容**: {m.get('content')}")
    
    else:  # compact
        for m in messages:
            tag = "✓" if m.get("is_match") else ""
            lines.append(f"[{m.get('time')}] {m.get('sender')}: {m.get('content')} {tag}")
    
    text = "\n".join(lines)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n...(已截断)"
    
    return _success({
        "text": text,
        "chars": len(text),
        "messages": len(messages),
        "format": fmt,
        "truncated": truncated
    })
```

---

## Agent 调用示例

### 场景 1: 简单话题查询

**用户**: "有没有关于旅行的聊天记录？"

```
Agent 规划:
1. list_topics(pattern="旅") → 确认有 "旅行" 话题
2. search_by_topics(topics=["旅行"]) → 获取行号 [45, 67, 89]
3. load_messages(line_numbers=[45, 67, 89], context_before=1, context_after=1)
4. format_messages(format="timeline")

结果: 直接返回，无需 LLM
```

### 场景 2: 模糊问题查询

**用户**: "老王有没有借过我钱？"

```
Agent 规划:
1. expand_query(question="老王有没有借过我钱", target_person="老王")
   → keywords=["借钱", "借", "还钱"], topics=["借贷", "金钱"]
2. 并行调用:
   - search_by_topics(topics=["借贷", "金钱"]) → [123, 234, ...]
   - search_by_keywords(keywords=["借", "还"], target_person="老王") → [456, ...]
3. 合并去重行号
4. load_messages(line_numbers=[...], context_before=2, context_after=2)
5. filter_by_person(target_person="老王")
6. format_messages(format="compact")

结果: Agent 可以选择是否使用 LLM 步骤
```

### 场景 3: 语义相似查询

**用户**: "之前讨论过类似'我觉得应该早点睡觉'的话题吗？"

```
Agent 规划:
1. search_semantic(query="应该早点睡觉", top_k=20)
   → [{line: 789, score: 0.92}, ...]
2. load_messages(line_numbers=[789, ...], include_metadata=true)
3. format_messages(format="detailed")

结果: 纯向量检索，无需话题索引
```

---

## 实施路线图

### Phase 1: 基础工具层 ⏱️ 1-2 天

| 任务 | 优先级 | 复杂度 |
|------|--------|--------|
| 实现 `list_topics` | P0 | 🟢 低 |
| 实现 `search_by_topics` | P0 | 🟢 低 |
| 实现 `search_by_keywords` | P0 | 🟡 中 |
| 实现 `load_messages` | P0 | 🟡 中 |

### Phase 2: 智能辅助层 ⏱️ 2-3 天

| 任务 | 优先级 | 复杂度 |
|------|--------|--------|
| 实现 `expand_query` | P1 | 🟡 中 |
| 实现 `search_semantic` | P1 | 🟡 中 |
| 实现 `filter_by_person` | P2 | 🔴 高 |

### Phase 3: 集成与迁移 ⏱️ 1 天

| 任务 | 优先级 | 复杂度 |
|------|--------|--------|
| 实现 `format_messages` | P1 | 🟢 低 |
| 更新 MCP Server 注册 | P0 | 🟢 低 |
| 更新 Prompt 注入 | P1 | 🟡 中 |

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 工具数量增多导致 Agent 决策困难 | 🟡 中 | 提供默认组合流程示例 |
| 索引/缓存不可用 | 🟡 中 | 每个工具返回明确的 `available` 标志 |
| 输出过大导致上下文溢出 | 🔴 高 | 限制 `max_results`/`max_chars`，默认紧凑输出 |
| LLM 调用失败 | 🟡 中 | 所有 LLM 工具提供 `use_llm=false` 回退 |

---

## 附录：辅助函数

```python
def _success(data: dict) -> dict:
    """标准成功响应"""
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(data, ensure_ascii=False, indent=2)
        }]
    }

def _error(message: str) -> dict:
    """标准错误响应"""
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"error": message}, ensure_ascii=False)
        }]
    }
```

---

## 更新日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-01-11 | 2.0 | 融合 GPT 提案与详细实现指南，形成完整设计文档 |

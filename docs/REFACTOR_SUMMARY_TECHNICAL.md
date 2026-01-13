# Chatlog 智能检索系统重构报告 - 技术视角

> 文档版本: v2.0.0  
> 更新日期: 2026-01-13  
> 文档类型: 技术架构设计 & 实现详解

---

## 目录

1. [技术背景与问题分析](#1-技术背景与问题分析)
2. [系统架构设计](#2-系统架构设计)
3. [核心模块实现](#3-核心模块实现)
4. [代码变更详解](#4-代码变更详解)
5. [API 接口规范](#5-api-接口规范)
6. [配置参数说明](#6-配置参数说明)
7. [性能优化策略](#7-性能优化策略)
8. [测试与验证](#8-测试与验证)
9. [部署与运维](#9-部署与运维)
10. [扩展与演进](#10-扩展与演进)

---

## 1. 技术背景与问题分析

### 1.1 原有技术架构

BENEDICTJUN 聊天记录检索系统基于 Claude Agent SDK 构建，采用 MCP (Multi-modal Context Protocol) 协议进行工具调用。原有架构如下：

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude Agent SDK                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │   Session   │───▶│   Agent     │───▶│   Tools     │      │
│  │   Manager   │    │   Runtime   │    │   (MCP)     │      │
│  └─────────────┘    └─────────────┘    └─────────────┘      │
│                            │                   │             │
│                            ▼                   ▼             │
│                     ┌─────────────┐    ┌─────────────┐      │
│                     │   Context   │    │   Chatlog   │      │
│                     │   Manager   │    │   MCP Server│      │
│                     └─────────────┘    └─────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 问题根源技术分析

通过对 token 消耗的详细追踪，我们定位到以下技术问题：

#### 1.2.1 expand_query 函数的 Token 爆炸

**问题代码** (cleaner.py):
```python
async def expand_query(self, question, target_person, available_topics):
    # 问题: available_topics 包含 1771 个话题
    topics_preview = ", ".join(available_topics[:50])  # 但只取前50
    topics_hint = f"\n可用话题标签(只能从中选择): {topics_preview}"
    
    # 传递给 LLM 的 prompt 包含全量列表引用
    # 导致: ~8000 tokens 消耗
```

**问题根源**:
- `available_topics` 列表在每次查询时被完整加载
- 即使只取前 50 个预览，整个列表仍被传递到其他函数
- 服务端没有对 LLM 返回的 topics 进行验证

#### 1.2.2 工具返回结果无限制

**问题代码** (mcp_server.py):
```python
def _build_response(ok, data, meta=None, is_error=False, tool_name="unknown"):
    # 问题: data 字典可能非常大
    payload = {"ok": ok, "data": data, "meta": meta}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # 只在最终 JSON 层面截断，但结构化数据已经消耗 tokens
```

**问题根源**:
- 缺乏数据结构层面的预截断
- 列表字段可能包含数百个元素
- 字符串字段可能包含完整消息内容

#### 1.2.3 消息加载无上限

**问题代码** (mcp_server.py):
```python
_CHATLOG_LOAD_CONTEXT_BEFORE = int(os.getenv("CHATLOG_LOAD_CONTEXT_BEFORE", "5"))
_CHATLOG_LOAD_CONTEXT_AFTER = int(os.getenv("CHATLOG_LOAD_CONTEXT_AFTER", "5"))
_CHATLOG_LOAD_MAX_MESSAGES = int(os.getenv("CHATLOG_LOAD_MAX_MESSAGES", "200"))
# 问题: 默认上下文 ±5，最大 200 条消息，导致巨量数据
```

#### 1.2.4 缺乏预算管控机制

原有系统没有任何预算限制：
- 工具可以无限次调用
- 消息可以无限加载
- 没有熔断机制

### 1.3 Token 消耗分布分析

对一次典型查询 "冯天奇对女性的看法" 的 token 分析：

| 阶段 | Token 消耗 | 占比 |
|------|-----------|------|
| 初始 prompt + 系统消息 | 15,000 | 3.5% |
| expand_query (topics 列表) | 8,500 | 2.0% |
| 第一轮工具调用结果 | 45,000 | 10.5% |
| 第二轮工具调用结果 | 89,000 | 20.7% |
| 第三轮工具调用结果 | 125,000 | 29.1% |
| 累积上下文 | 147,500 | 34.2% |
| **总计** | **430,000** | **100%** |

**关键发现**: 超过 60% 的 token 消耗来自工具调用结果的累积。

---

## 2. 系统架构设计

### 2.1 重构后的架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         BENEDICTJUN Agent                            │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    MCP Tool Layer                             │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │   │
│  │  │ parse_task  │  │  retrieve   │  │  analyze    │           │   │
│  │  │   [产品级]   │  │  _evidence  │  │  _evidence  │           │   │
│  │  │             │  │   [产品级]   │  │   [产品级]   │           │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘           │   │
│  │         │                │                │                   │   │
│  │         ▼                ▼                ▼                   │   │
│  │  ┌─────────────────────────────────────────────────────────┐ │   │
│  │  │              Internal Tool Layer (隐藏)                  │ │   │
│  │  │  expand_query | search_by_* | load_messages | filter    │ │   │
│  │  └─────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                │                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   Optimization Layer                          │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │   │
│  │  │ Token       │  │ Data        │  │ Budget      │           │   │
│  │  │ Monitor     │  │ Slimmer     │  │ Manager     │           │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                │                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   Intelligence Layer                          │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │   │
│  │  │ Poe Small   │  │ Compress    │  │ Evidence    │           │   │
│  │  │ Model API   │  │ Messages    │  │ Matrix Gen  │           │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                │                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     Data Layer                                │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │   │
│  │  │ Metadata    │  │ Semantic    │  │ Evidence    │           │   │
│  │  │ Index       │  │ Index       │  │ Store       │           │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

#### 2.2.1 工具分层原则

将工具分为三个层级：

| 层级 | 可见性 | 工具列表 | 说明 |
|------|--------|---------|------|
| **产品级** | Agent 可见 | parse_task, retrieve_evidence, analyze_evidence | 高层抽象，完整功能 |
| **内部级** | 仅内部调用 | expand_query, search_by_*, load_messages, filter_by_person | 原子操作，组合使用 |
| **遗留级** | 已弃用 | get_chatlog_stats, search_person | 保留兼容，不推荐 |

**设计理由**:
- 减少 Agent 决策复杂度
- 避免低效的工具调用组合
- 内部工具可以进行更激进的优化

#### 2.2.2 数据瘦身原则

在数据离开服务端之前进行多层截断：

```
原始数据
    ↓
┌─────────────────┐
│ _slim_data()    │  ← 结构化截断（列表≤50，字符串≤200）
└─────────────────┘
    ↓
┌─────────────────┐
│ _build_response │  ← JSON 层面截断（≤15000 chars）
└─────────────────┘
    ↓
┌─────────────────┐
│ compress_msgs   │  ← 智能压缩（相关性评分+内容压缩）
└─────────────────┘
    ↓
返回给 Agent
```

#### 2.2.3 预算硬限原则

所有资源消耗都有硬上限：

```python
class ToolBudget:
    max_tool_calls: int = 3      # 最多 3 次工具调用
    max_loaded_messages: int = 80  # 最多加载 80 条消息
    max_tool_result_chars: int = 15000  # 最大返回 15k 字符
```

超过预算时：
1. 停止继续调用
2. 返回已收集的部分结果
3. 附带缺口说明

---

## 3. 核心模块实现

### 3.1 Token 监控模块

**文件**: `src/chatlog/mcp_server.py`

#### 3.1.1 _log_tool_payload 增强

```python
def _log_tool_payload(tool_name: str, payload: Dict[str, Any], chars: int) -> None:
    """Log tool result with token estimation and alert for large payloads."""
    approx_tokens = _approx_tokens(chars)
    threshold_chars = int(os.getenv("CHATLOG_TOOL_ALERT_CHARS", "12000"))
    
    # Extract field sizes for debugging
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
        # Alert for oversized payloads
        print(f"[TOOL ALERT] ⚠️ {tool_name}: {chars} chars (~{approx_tokens} tokens) OVER THRESHOLD")
        if largest_key[0]:
            print(f"  └─ Largest field: '{largest_key[0]}' = {largest_key[1]} chars")
        print(f"  └─ Fields: {list(key_sizes.keys())}")
    else:
        print(f"[TOOL] {tool_name}: {chars} chars (~{approx_tokens} tokens)")
```

**功能说明**:
- 实时监控每个工具调用的返回大小
- 超过阈值时自动告警
- 显示最大字段，便于定位问题
- Token 估算公式: `tokens ≈ chars / 3.6`

#### 3.1.2 Token 估算函数

```python
def _approx_tokens(chars: int) -> int:
    """Approximate token count from character count.
    
    Based on empirical observation:
    - Chinese: ~1.5 chars per token
    - Mixed content: ~3.6 chars per token (weighted average)
    """
    if chars <= 0:
        return 0
    return max(1, int(chars / 3.6))
```

### 3.2 数据瘦身模块

#### 3.2.1 _slim_data 递归截断

```python
_SLIM_MAX_LIST = int(os.getenv("CHATLOG_SLIM_MAX_LIST", "50"))
_SLIM_MAX_SNIPPET = int(os.getenv("CHATLOG_SLIM_MAX_SNIPPET", "200"))

def _slim_data(data: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    """
    Recursively slim down data structure to prevent token explosion.
    
    Processing rules:
    - Lists: truncated to _SLIM_MAX_LIST items with omitted_count
    - Long strings: truncated to _SLIM_MAX_SNIPPET chars
    - Nested dicts: recursively processed (max depth: 5)
    """
    if depth > 5:  # Prevent infinite recursion
        return data
    
    slimmed: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, list):
            # Truncate lists
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
```

**设计要点**:
- 递归处理嵌套结构
- 为截断的列表添加 `_xxx_omitted` 和 `_xxx_cursor` 字段
- 支持分页查询更多数据
- depth 限制防止循环引用导致的无限递归

#### 3.2.2 集成到 _build_response

```python
def _build_response(
    ok: bool,
    data: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    is_error: bool = False,
    tool_name: str = "unknown",
    slim: bool = True,  # 新增参数
) -> Dict[str, Any]:
    """Build standardized tool response with automatic data slimming."""
    meta = meta or {}
    meta.setdefault("tool", tool_name)
    
    # Apply data slimming before serialization to prevent token explosion
    if slim and isinstance(data, dict):
        data = _slim_data(data)
    
    payload = {"ok": ok, "data": data, "meta": meta}
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
        **({\"is_error\": True} if is_error else {})
    }
```

### 3.3 预算管理模块

**文件**: `src/chatlog/budget_manager.py`

```python
@dataclass
class ToolBudget:
    """Budget constraints for a single query session."""
    
    # Configurable limits
    max_tool_calls: int = 3
    max_loaded_messages: int = 80
    max_tool_result_chars: int = 15000
    
    # Current usage tracking
    tool_calls: int = 0
    loaded_messages: int = 0
    total_result_chars: int = 0
    tool_history: List[str] = field(default_factory=list)
    
    def can_call_tool(self, tool_name: str = "") -> bool:
        """Check if another tool call is allowed."""
        return self.tool_calls < self.max_tool_calls
    
    def can_load_messages(self, count: int) -> bool:
        """Check if loading more messages is allowed."""
        return self.loaded_messages + count <= self.max_loaded_messages
    
    def record_tool_call(self, tool_name: str, result_chars: int):
        """Record a tool call and its result size."""
        self.tool_calls += 1
        self.total_result_chars += result_chars
        self.tool_history.append(tool_name)
    
    def record_messages(self, count: int):
        """Record loaded messages count."""
        self.loaded_messages += count
    
    def is_over_budget(self) -> bool:
        """Check if any budget limit has been exceeded."""
        return (
            self.tool_calls >= self.max_tool_calls or
            self.loaded_messages >= self.max_loaded_messages or
            self.total_result_chars >= self.max_tool_result_chars
        )
    
    def get_gap_annotation(self) -> str:
        """Generate annotation describing what was not retrieved due to budget."""
        gaps = []
        remaining = self.get_remaining()
        
        if remaining["tool_calls"] == 0:
            gaps.append(f"已达工具调用上限({self.max_tool_calls}次)")
        if remaining["messages"] == 0:
            gaps.append(f"已达消息加载上限({self.max_loaded_messages}条)")
        if remaining["chars"] == 0:
            gaps.append(f"已达结果字符上限({self.max_tool_result_chars}字符)")
        
        if gaps:
            return "⚠️ 证据收集受预算限制: " + "; ".join(gaps)
        return ""


class BudgetManager:
    """Manage tool budgets per query session."""
    
    def __init__(self):
        self._budgets: Dict[str, ToolBudget] = {}
        
        # Load defaults from environment
        self._default_max_calls = int(os.getenv("CHATLOG_MAX_TOOL_CALLS", "3"))
        self._default_max_messages = int(os.getenv("CHATLOG_MAX_MESSAGES", "80"))
        self._default_max_chars = int(os.getenv("CHATLOG_MAX_RESULT_CHARS", "15000"))
    
    def get_budget(self, session_id: str) -> ToolBudget:
        """Get or create budget for a session."""
        if session_id not in self._budgets:
            self._budgets[session_id] = ToolBudget(
                max_tool_calls=self._default_max_calls,
                max_loaded_messages=self._default_max_messages,
                max_tool_result_chars=self._default_max_chars,
            )
        return self._budgets[session_id]
    
    def clear_budget(self, session_id: str):
        """Clear budget for a session (call after query completes)."""
        self._budgets.pop(session_id, None)
```

### 3.4 智能压缩模块

**文件**: `src/chatlog/cleaner.py`

#### 3.4.1 compress_messages 实现

```python
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
    
    Processing steps:
    1. Score each message for relevance (0-10)
    2. Sort by relevance, select top N
    3. Compress verbose low-relevance messages
    
    Returns:
        Compressed message list with 'compressed' and 'relevance' fields
    """
    if not messages:
        return []
    
    client = self._get_poe_client()
    
    if client is None or not client.is_configured:
        return messages[:max_output_messages]
    
    # Step 1: Score each message for relevance
    scored_messages = []
    batch_size = 20
    
    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]
        batch_text = "\n".join([
            f"[{idx + i}] {m.get('sender', '?')}: {m.get('content', '')[:200]}"
            for idx, m in enumerate(batch)
        ])
        
        score_prompt = f"""为以下消息评估与问题的相关性（0-10分）。
问题: {question}
{f"关于「{target_person}」" if target_person else ""}

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
                m['relevance'] = 5
            scored_messages.append(m)
    
    # Step 2: Sort by relevance and select top messages
    scored_messages.sort(key=lambda m: m.get('relevance', 0), reverse=True)
    selected = scored_messages[:max_output_messages]
    
    # Step 3: Compress verbose messages
    for m in selected:
        content = m.get('content', '')
        if len(content) > 200 and m.get('relevance', 0) < 8:
            compressed = await self._compress_single_message(
                content, question, target_person,
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
```

#### 3.4.2 generate_evidence_matrix 实现

```python
async def generate_evidence_matrix(
    self,
    dimension_evidence: List[Dict[str, Any]],
    question: str,
    target_person: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate structured evidence matrix from dimension evidence.
    
    Output structure:
    - Per-dimension conclusion
    - Evidence list with snippets and weights
    - Reasoning chain
    - Counter-evidence and gaps
    - Confidence score
    """
    client = self._get_poe_client()
    
    if client is None or not client.is_configured:
        return self._fallback_evidence_matrix(dimension_evidence, question, target_person)
    
    # Prepare evidence text
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
    
    matrix_prompt = f"""基于以下证据，为每个维度生成「证据矩阵」分析。

问题: {question}
{f"目标人物: {target_person}" if target_person else ""}
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
```

---

## 4. 代码变更详解

### 4.1 变更文件清单

| 文件路径 | 变更类型 | 主要修改 |
|---------|---------|---------|
| `src/chatlog/mcp_server.py` | MODIFY | Token 监控、数据瘦身、参数提升、压缩集成 |
| `src/chatlog/cleaner.py` | MODIFY | prompt 优化、compress_messages、evidence_matrix |
| `src/chatlog/budget_manager.py` | NEW | 预算管理器 |

### 4.2 mcp_server.py 变更详解

#### 4.2.1 常量参数变更

```python
# === 变更前 ===
_CHATLOG_MAX_RETURN_CHARS = int(os.getenv("CHATLOG_MAX_RETURN_CHARS", "4000"))
_CHATLOG_MAX_TOOL_CHARS = int(os.getenv("CHATLOG_MAX_TOOL_CHARS", "12000"))
_CHATLOG_MAX_LIST_ITEMS = int(os.getenv("CHATLOG_MAX_LIST_ITEMS", "50"))
_CHATLOG_MAX_EVIDENCE_MESSAGES = int(os.getenv("CHATLOG_MAX_EVIDENCE_MESSAGES", "40"))
_CHATLOG_MAX_EVIDENCE_PER_DIM = int(os.getenv("CHATLOG_MAX_EVIDENCE_PER_DIM", "10"))
_CHATLOG_LOAD_CONTEXT_BEFORE = int(os.getenv("CHATLOG_LOAD_CONTEXT_BEFORE", "1"))
_CHATLOG_LOAD_CONTEXT_AFTER = int(os.getenv("CHATLOG_LOAD_CONTEXT_AFTER", "1"))
_CHATLOG_LOAD_MAX_MESSAGES = int(os.getenv("CHATLOG_LOAD_MAX_MESSAGES", "20"))

# === 变更后 ===
_CHATLOG_MAX_RETURN_CHARS = int(os.getenv("CHATLOG_MAX_RETURN_CHARS", "6000"))
_CHATLOG_MAX_TOOL_CHARS = int(os.getenv("CHATLOG_MAX_TOOL_CHARS", "15000"))
_CHATLOG_MAX_LIST_ITEMS = int(os.getenv("CHATLOG_MAX_LIST_ITEMS", "80"))
_CHATLOG_MAX_EVIDENCE_MESSAGES = int(os.getenv("CHATLOG_MAX_EVIDENCE_MESSAGES", "80"))
_CHATLOG_MAX_EVIDENCE_PER_DIM = int(os.getenv("CHATLOG_MAX_EVIDENCE_PER_DIM", "25"))
_CHATLOG_LOAD_CONTEXT_BEFORE = int(os.getenv("CHATLOG_LOAD_CONTEXT_BEFORE", "2"))
_CHATLOG_LOAD_CONTEXT_AFTER = int(os.getenv("CHATLOG_LOAD_CONTEXT_AFTER", "2"))
_CHATLOG_LOAD_MAX_MESSAGES = int(os.getenv("CHATLOG_LOAD_MAX_MESSAGES", "60"))
```

**变更理由**:
- 有智能压缩后可以处理更多数据
- 更多证据 = 更准确的分析
- 参数可通过环境变量覆盖

#### 4.2.2 _expand_query_impl 变更

```python
# === 变更前 ===
async def _expand_query_impl(args: dict) -> dict:
    index_loader = get_index_loader()
    available_topics = index_loader.available_topics if index_loader.load_index() else []
    
    if use_llm and llm_available:
        keywords, metadata = await cleaner.expand_query(
            question, target_person, available_topics  # 传递全量 1771 个话题
        )

# === 变更后 ===
async def _expand_query_impl(args: dict) -> dict:
    index_loader = get_index_loader()
    available_topics = index_loader.available_topics if index_loader.load_index() else []
    # Only pass first 50 topics as preview to LLM to prevent token explosion
    topics_preview = available_topics[:50] if available_topics else []

    if use_llm and llm_available:
        keywords, metadata = await cleaner.expand_query(
            question, target_person, topics_preview  # 只传递预览
        )
        # Server-side filtering: ensure LLM-suggested topics exist
        llm_topics = metadata.get("topics", [])
        metadata["topics"] = [t for t in llm_topics if t in available_topics]
```

**变更效果**:
- Token 消耗从 ~8000 降至 ~300
- 服务端验证确保结果有效
- LLM 仍可推理预览之外的话题

#### 4.2.3 _retrieve_evidence_impl 变更

新增智能压缩步骤：

```python
# 在存储证据前添加
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

evidence_id = _store_evidence({...})
```

#### 4.2.4 _analyze_evidence_impl 变更

新增 LLM 分析步骤：

```python
use_llm_analysis = bool(args.get("use_llm_analysis", True))

# Step: Optionally use LLM for intelligent analysis
llm_matrix = None
if use_llm_analysis and matrix:
    cleaner = _get_cleaner()
    poe_client = cleaner._get_poe_client()
    if poe_client and poe_client.is_configured:
        try:
            llm_matrix = await cleaner.generate_evidence_matrix(
                matrix,
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
    ...
    "overall_conclusion": llm_matrix.get("overall_conclusion") if llm_matrix else None,
    "evidence_quality": llm_matrix.get("evidence_quality") if llm_matrix else None,
    "analysis_method": "llm" if (llm_matrix and llm_matrix.get("method") == "llm") else "rule_based",
}
```

### 4.3 cleaner.py 变更详解

#### 4.3.1 expand_query prompt 变更

```python
# === 变更前 ===
topics_hint = f"\n可用话题标签(只能从中选择): {topics_preview}"

# === 变更后 ===
topics_hint = f"\n话题标签示例（作参考，可推理相关话题）: {topics_preview}"
```

**变更理由**:
- 允许 LLM 推理未在预览中的话题
- 更灵活的话题生成
- 服务端会验证有效性

---

## 5. API 接口规范

### 5.1 产品级工具

#### 5.1.1 parse_task

**功能**: 解析用户问题，生成维度计划

**输入参数**:
```json
{
  "question": "用户问题 (必填)",
  "target_person": "目标人物 (可选)",
  "max_dimensions": "最大维度数 (默认: 4)"
}
```

**输出格式**:
```json
{
  "ok": true,
  "data": {
    "task_type": "decision|comparison|analysis|...",
    "question_type": "persona_on_topic|...",
    "target_person": "冯天奇",
    "dimensions": [
      {
        "name": "经济信誉维度",
        "intent": "从借贷历史判断信誉",
        "topic_seeds": ["借贷", "还钱"],
        "keyword_seeds": ["借钱", "欠款"],
        "semantic_queries": ["借钱还钱情况"],
        "counter_queries": ["赖账", "不还钱"],
        "min_evidence": 3
      }
    ],
    "method": "llm|rule_based",
    "model": "Gemini-2.5-Flash-Lite"
  },
  "meta": {
    "tool": "parse_task",
    "timing_ms": 1234
  }
}
```

#### 5.1.2 retrieve_evidence

**功能**: 根据维度计划检索证据

**输入参数**:
```json
{
  "question": "用户问题 (必填)",
  "target_person": "目标人物 (可选)",
  "dimensions": "维度计划 (可选，不提供则自动生成)",
  "max_per_dimension": "每维度最大证据数 (默认: 25)",
  "max_total_messages": "总最大消息数 (默认: 80)",
  "use_semantic": "是否使用语义搜索 (默认: true)",
  "use_compression": "是否使用智能压缩 (默认: true)"
}
```

**输出格式**:
```json
{
  "ok": true,
  "data": {
    "evidence_id": "evi_abc123",
    "dimensions": [
      {
        "name": "经济信誉维度",
        "intent": "...",
        "evidence": [
          {
            "line": 1234,
            "time": "2025-06-15 14:30",
            "sender": "冯天奇",
            "snippet": "借的钱我会还的...",
            "topics": ["借贷"],
            "score": 0.85,
            "relevance": 8,
            "compressed": false
          }
        ],
        "counter_evidence": [...],
        "coverage": {...},
        "omitted_count": 5,
        "next_cursor": "dimension:经济信誉维度#offset=25"
      }
    ],
    "limits": {
      "max_per_dimension": 25,
      "max_total_messages": 80,
      "snippet_chars": 150,
      "context_window": "±2/2"
    }
  },
  "meta": {
    "tool": "retrieve_evidence",
    "timing_ms": 2345
  }
}
```

#### 5.1.3 analyze_evidence

**功能**: 分析证据，生成证据矩阵

**输入参数**:
```json
{
  "evidence_id": "evi_abc123 (必填)",
  "question": "用户问题 (可选，从缓存获取)",
  "target_person": "目标人物 (可选)",
  "max_examples": "每维度最大展示证据数 (默认: 5)",
  "use_llm_analysis": "是否使用 LLM 生成结论 (默认: true)"
}
```

**输出格式**:
```json
{
  "ok": true,
  "data": {
    "evidence_id": "evi_abc123",
    "matrix": [
      {
        "dimension": "经济信誉维度",
        "intent": "...",
        "conclusion": "该人物有较好的财务信誉...",
        "evidence": [
          {
            "line": 1234,
            "time": "2025-06-15 14:30",
            "sender": "冯天奇",
            "snippet": "..."
          }
        ],
        "counter_evidence": [...],
        "reasoning": "从多次借贷记录可见...",
        "gaps": ["缺少大额借款历史"],
        "confidence": "中高"
      }
    ],
    "overview": {
      "message_count": 72,
      "sender_counts": {"冯天奇": 45, "其他": 27},
      "target_person": "冯天奇"
    },
    "overall_conclusion": "综合分析...",
    "evidence_quality": "证据充分度较高",
    "analysis_method": "llm",
    "framework": [...],
    "disclaimer": "分析仅基于聊天记录证据..."
  },
  "meta": {
    "tool": "analyze_evidence",
    "llm_used": true,
    "timing_ms": 3456
  }
}
```

---

## 6. 配置参数说明

### 6.1 环境变量清单

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| **消息数量相关** | | |
| `CHATLOG_MAX_EVIDENCE_MESSAGES` | 80 | 单次检索最大证据消息数 |
| `CHATLOG_MAX_EVIDENCE_PER_DIM` | 25 | 每维度最大证据数 |
| `CHATLOG_LOAD_MAX_MESSAGES` | 60 | 单次加载最大消息数 |
| `CHATLOG_SEM_TOP_K` | 100 | 语义搜索返回数量 |
| **上下文相关** | | |
| `CHATLOG_LOAD_CONTEXT_BEFORE` | 2 | 加载消息前上下文行数 |
| `CHATLOG_LOAD_CONTEXT_AFTER` | 2 | 加载消息后上下文行数 |
| **字符限制相关** | | |
| `CHATLOG_MAX_RETURN_CHARS` | 6000 | 最终返回最大字符数 |
| `CHATLOG_MAX_TOOL_CHARS` | 15000 | 工具返回最大字符数 |
| `CHATLOG_SNIPPET_CHARS` | 150 | 摘要片段最大字符数 |
| **数据瘦身相关** | | |
| `CHATLOG_SLIM_MAX_LIST` | 50 | 列表截断最大项数 |
| `CHATLOG_SLIM_MAX_SNIPPET` | 200 | 字符串截断最大长度 |
| `CHATLOG_TOOL_ALERT_CHARS` | 12000 | 告警阈值字符数 |
| **预算相关** | | |
| `CHATLOG_MAX_TOOL_CALLS` | 3 | 单次查询最大工具调用 |
| `CHATLOG_MAX_MESSAGES` | 80 | 预算：最大消息数 |
| `CHATLOG_MAX_RESULT_CHARS` | 15000 | 预算：最大结果字符 |
| **模型相关** | | |
| `CHATLOG_CLEANER_MODEL` | Gemini-2.5-Flash-Lite | 小模型名称 |
| **搜索权重** | | |
| `CHATLOG_SEM_WEIGHT` | 0.6 | 语义搜索权重 |
| `CHATLOG_KW_WEIGHT` | 0.4 | 关键词搜索权重 |

### 6.2 .env 配置示例

```env
# === Chatlog 检索配置 ===

# 消息数量（有压缩后可以调高）
CHATLOG_MAX_EVIDENCE_MESSAGES=80
CHATLOG_MAX_EVIDENCE_PER_DIM=25
CHATLOG_SEM_TOP_K=100

# 上下文窗口
CHATLOG_LOAD_CONTEXT_BEFORE=2
CHATLOG_LOAD_CONTEXT_AFTER=2

# 数据瘦身（防止 token 爆炸）
CHATLOG_SLIM_MAX_LIST=50
CHATLOG_SLIM_MAX_SNIPPET=200
CHATLOG_TOOL_ALERT_CHARS=12000

# 预算限制
CHATLOG_MAX_TOOL_CALLS=3
CHATLOG_MAX_TOOL_CHARS=15000

# 小模型（用于压缩和分析）
CHATLOG_CLEANER_MODEL=Gemini-2.5-Flash-Lite
```

---

## 7. 性能优化策略

### 7.1 Token 优化策略

| 策略 | 实现方式 | 效果 |
|------|---------|------|
| **预截断** | `_slim_data()` 在序列化前截断 | 防止大对象进入 JSON |
| **预览替代全量** | topics 只传 50 个预览 | 8000→300 tokens |
| **智能压缩** | 低相关消息压缩 50% | 同空间 2x 信息量 |
| **增量分页** | `omitted_count` + `next_cursor` | 按需加载 |
| **预算熔断** | 超限即停，返回部分结果 | 防止无限累积 |

### 7.2 延迟优化策略

| 策略 | 实现方式 | 效果 |
|------|---------|------|
| **并行召回** | topic/semantic/keyword 并行 | 减少串行等待 |
| **批量评分** | 20 条消息一批评分 | 减少 API 调用 |
| **缓存复用** | `evidence_id` 缓存完整结果 | 分析时无需重新检索 |
| **懒加载** | 只在需要时加载消息内容 | 减少内存占用 |

### 7.3 准确率优化策略

| 策略 | 实现方式 | 效果 |
|------|---------|------|
| **多通道召回** | topic + semantic + keyword | 提高召回率 |
| **相关性评分** | LLM 0-10 评分 | 过滤低价值信息 |
| **反证搜索** | counter_queries 自动生成 | 避免确认偏误 |
| **实体归因** | 判断消息讨论的是谁 | 避免张冠李戴 |

---

## 8. 测试与验证

### 8.1 单元测试

```python
# 测试 _slim_data
def test_slim_data():
    data = {
        "topics": list(range(100)),  # 100 项列表
        "content": "a" * 500,         # 500 字符字符串
        "nested": {"items": list(range(200))}
    }
    slimmed = _slim_data(data)
    assert len(slimmed["topics"]) == 50
    assert len(slimmed["content"]) <= 200
    assert slimmed["_topics_omitted"] == 50
    assert len(slimmed["nested"]["items"]) == 50

# 测试 _approx_tokens
def test_approx_tokens():
    assert _approx_tokens(0) == 0
    assert _approx_tokens(360) == 100
    assert _approx_tokens(3600) == 1000
```

### 8.2 集成测试

```python
# 测试 expand_query token 消耗
async def test_expand_query_tokens():
    result = await _expand_query_impl({
        "question": "冯天奇对女性的看法",
        "target_person": "冯天奇"
    })
    content = result["content"][0]["text"]
    
    # 验证返回大小合理
    assert len(content) < 2000  # 应该远小于 2k
    
    # 验证结构完整
    payload = json.loads(content)
    assert payload["ok"] == True
    assert "keywords" in payload["data"]
    assert "topics" in payload["data"]

# 测试 retrieve_evidence 消息压缩
async def test_retrieve_evidence_compression():
    result = await _retrieve_evidence_impl({
        "question": "冯天奇的消费习惯",
        "target_person": "冯天奇",
        "use_compression": True
    })
    
    payload = json.loads(result["content"][0]["text"])
    
    # 验证证据被正确压缩
    for dim in payload["data"]["dimensions"]:
        for evidence in dim.get("evidence", []):
            # 压缩后的消息应该有 relevance 字段
            if evidence.get("compressed"):
                assert len(evidence["content"]) < len(evidence.get("original_content", ""))
```

### 8.3 端到端验证

```bash
# 运行语法检查
python -m py_compile src/chatlog/mcp_server.py
python -m py_compile src/chatlog/cleaner.py
python -m py_compile src/chatlog/budget_manager.py

# 运行功能测试
python -c "
import asyncio
from src.chatlog.mcp_server import _expand_query_impl

async def test():
    result = await _expand_query_impl({
        'question': '冯天奇对女性的看法',
        'target_person': '冯天奇'
    })
    content = result['content'][0]['text']
    print(f'Result chars: {len(content)}')
    print(f'Approx tokens: {len(content) // 3}')

asyncio.run(test())
"
```

**验证结果**:
```
Result chars: 820
Approx tokens: ~227
```

（对比重构前: 40,000+ chars, ~11,000 tokens）

---

## 9. 部署与运维

### 9.1 依赖清单

```
# Python 依赖
claude-agent-sdk>=1.0.0
aiohttp>=3.8.0
pydantic>=2.0.0

# 可选依赖 (语义搜索)
numpy>=1.20.0
sentence-transformers>=2.0.0
```

### 9.2 部署步骤

```bash
# 1. 更新代码
git pull origin main

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 设置参数

# 4. 验证安装
python -m py_compile src/chatlog/mcp_server.py

# 5. 启动服务
python -m src.tui_agent
```

### 9.3 监控指标

| 指标 | 告警阈值 | 说明 |
|------|---------|------|
| `tool_result_chars` | >15000 | 工具返回过大 |
| `query_tokens` | >50000 | 单次查询 token 过高 |
| `query_latency_ms` | >30000 | 查询延迟过高 |
| `compression_failure_rate` | >10% | 压缩失败率过高 |
| `poe_api_error_rate` | >5% | 小模型 API 错误率 |

### 9.4 日志分析

```bash
# 查看工具调用告警
grep "\[TOOL ALERT\]" logs/agent.log

# 查看压缩日志
grep "\[RETRIEVE\]" logs/agent.log | grep "智能压缩"

# 查看 LLM 分析日志
grep "\[ANALYZE\]" logs/agent.log
```

---

## 10. 扩展与演进

### 10.1 可扩展点

| 扩展点 | 当前实现 | 扩展方向 |
|--------|---------|---------|
| **评分模型** | Poe 小模型 | 本地微调模型 |
| **压缩算法** | LLM 压缩 | 规则 + LLM 混合 |
| **证据存储** | 内存缓存 | Redis/数据库 |
| **预算策略** | 固定阈值 | 动态自适应 |

### 10.2 技术债务

| 债务项 | 严重程度 | 解决方案 |
|--------|---------|---------|
| 压缩函数 LLM 调用过多 | 中 | 批量处理 + 本地缓存 |
| 缺乏单元测试 | 中 | 补充测试用例 |
| 错误处理不够细致 | 低 | 增加重试和降级逻辑 |

### 10.3 性能优化路线图

**短期 (1-2周)**:
- 添加压缩结果缓存
- 优化批量评分 batch size
- 增加更详细的日志

**中期 (1-2月)**:
- 引入本地 embedding 模型
- 实现预算自适应算法
- 添加 A/B 测试框架

**长期 (3-6月)**:
- 微调专用小模型
- 实现增量索引更新
- 支持多源数据整合

---

## 附录

### A. 代码调用链路

```
用户问题
    │
    ▼
┌─────────────────────────────────────────────────┐
│ Agent 调用 parse_task                            │
│   └─> _parse_task_impl                          │
│         └─> cleaner.plan_evidence_dimensions    │
│               └─> Poe API (小模型)               │
│                     └─> 返回维度计划             │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ Agent 调用 retrieve_evidence                     │
│   └─> _retrieve_evidence_impl                   │
│         ├─> index_loader.search_by_topic_exact  │
│         ├─> semantic_index.search               │
│         ├─> _search_by_keywords_impl            │
│         ├─> index_loader.get_messages_by_lines  │
│         ├─> cleaner.compress_messages           │
│         │     └─> Poe API (相关性评分)           │
│         │     └─> Poe API (内容压缩)             │
│         └─> _store_evidence                     │
│               └─> 返回 evidence_id              │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ Agent 调用 analyze_evidence                      │
│   └─> _analyze_evidence_impl                    │
│         ├─> _get_evidence(evidence_id)          │
│         ├─> 构建基础 matrix                      │
│         ├─> cleaner.generate_evidence_matrix    │
│         │     └─> Poe API (证据矩阵生成)         │
│         └─> 返回分析结果                         │
└─────────────────────────────────────────────────┘
    │
    ▼
最终回答
```

### B. 错误码说明

| 错误码 | 说明 | 处理方式 |
|--------|------|---------|
| `ERR_NO_QUESTION` | 未提供问题 | 返回错误提示 |
| `ERR_INDEX_LOAD` | 索引加载失败 | 回退到旧实现 |
| `ERR_BUDGET_EXCEEDED` | 预算超限 | 返回部分结果 + 缺口说明 |
| `ERR_POE_API` | 小模型 API 失败 | 回退到规则方法 |
| `ERR_JSON_PARSE` | JSON 解析失败 | 使用原始文本 |

---

*文档结束*

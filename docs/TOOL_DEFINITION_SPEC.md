# BENEDICTJUN 工具定义规范文档

本文档详细说明 BENEDICTJUN 项目中如何定义工具（Tools），与用户提供的 Kimi API 格式对比，并深入分析项目中使用的 Claude Agent SDK 工具定义模式。

---

## 1. 总体对比概览

### 1.1 Kimi API 格式 vs Claude Agent SDK 格式

| 维度 | Kimi API | Claude Agent SDK (BENEDICTJUN) |
|------|----------|-------------------------------|
| **定义方式** | 纯 JSON Schema 字典 | `@tool` 装饰器 + Python 类型 |
| **参数定义** | JSON Schema `properties` | Python `dict[type]` 简写 |
| **描述信息** | 多层级嵌套的 `description` | 装饰器参数直接传入 |
| **类型系统** | JSON Schema 原生类型 | Python 类型 → SDK 自动转换 |
| **注册方式** | 手动构建 `tools` 列表 | `create_sdk_mcp_server()` 自动注册 |
| **执行方式** | 外部函数分发 | 装饰的异步函数直接执行 |

### 1.2 两种格式对照示例

**Kimi API 格式（搜索工具）：**
```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "通过搜索引擎搜索互联网上的内容...",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户搜索的内容..."
                    }
                }
            }
        }
    }
]
```

**Claude Agent SDK 格式（等效工具）：**
```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool(
    "web_search",                           # name
    "Search the web with Tavily",           # description
    {                                       # parameters (简化格式)
        "query": str,
        "max_results": int,
        "search_depth": str,
    },
)
async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    """函数实现..."""
    query = args.get("query", "")
    # ... 实现逻辑
```

---

## 2. Claude Agent SDK `@tool` 装饰器详解

### 2.1 装饰器签名

```python
@tool(name: str, description: str, parameters: dict[str, type])
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 工具名称，将被映射为 `mcp__<server>__<name>` |
| `description` | `str` | 工具说明，LLM 根据此描述决定何时调用 |
| `parameters` | `dict[str, type]` | 参数名 → Python 类型的映射 |

### 2.2 参数类型映射

| Python 类型 | 对应 JSON Schema |
|-------------|-----------------|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `list` | `{"type": "array"}` |
| `dict` | `{"type": "object"}` |

### 2.3 限制与约束

- **无 `required` 声明**：SDK 简化格式不区分必填/可选参数
- **无嵌套 Schema**：不支持深层对象结构定义
- **无枚举约束**：不支持 `enum` 值限制
- **类型提示是关键**：SDK 根据 Python 类型生成 Schema

---

## 3. 项目中的工具定义实例

### 3.1 Web 搜索模块 (`src/tools/web_search.py`)

```python
@tool(
    "web_search",
    "Search the web with Tavily",
    {
        "query": str,           # 搜索关键词
        "max_results": int,     # 结果数量
        "search_depth": str,    # 搜索深度 (basic/advanced)
    },
)
async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY")
    query = (args.get("query") or "").strip()
    max_results = int(args.get("max_results") or 5)
    # ... 调用 Tavily API
```

```python
@tool(
    "web_fetch",
    "Fetch a web page over HTTP",
    {
        "url": str,             # 网页 URL
        "max_bytes": int,       # 最大读取字节数
    },
)
async def web_fetch(args: dict[str, Any]) -> dict[str, Any]:
    url = (args.get("url") or "").strip()
    max_bytes = int(args.get("max_bytes") or 200_000)
    # ... 抓取网页
```

### 3.2 Memory 模块 (`src/memory/mcp_server.py`)

```python
@tool(
    "recall_memory",
    "根据话题或关键词检索相关的用户记忆。用于获取与当前对话相关的用户偏好、事实、观点等信息。",
    {
        "topic": str,      # 搜索话题或关键词
        "limit": int       # 返回结果数量限制（默认5）
    }
)
async def recall_memory(args: dict) -> dict:
    storage = _get_storage()
    topic = args.get("topic", "")
    limit = args.get("limit", 5)
    # ...
```

```python
@tool(
    "remember",
    "保存用户明确要求记住的信息。类别包括：preference（偏好）、fact（事实）、opinion（观点）、attitude（态度）。",
    {
        "category": str,   # 类别: preference/fact/opinion/attitude
        "content": str,    # 要记住的内容
        "key": str,        # 可选：对于偏好类型，指定键名
        "value": str       # 可选：对于偏好类型，指定值
    }
)
async def remember(args: dict) -> dict:
    # ...
```

```python
@tool(
    "get_user_profile",
    "获取用户的核心画像信息，包括姓名、语言偏好、职业等基础信息。这些信息始终可用且token消耗很少。",
    {}  # 无参数
)
async def get_user_profile(args: dict) -> dict:
    # ...
```

```python
@tool(
    "list_memories",
    "列出已保存的记忆。可以按类别筛选（preference/fact/opinion/attitude）。",
    {
        "category": str,  # 可选：筛选类别
        "limit": int      # 返回数量限制
    }
)
async def list_memories(args: dict) -> dict:
    # ...
```

```python
@tool(
    "forget",
    "删除指定ID的记忆。",
    {
        "memory_id": str  # 要删除的记忆ID
    }
)
async def forget(args: dict) -> dict:
    # ...
```

### 3.3 Chatlog 模块 (`src/chatlog/mcp_server.py`)

```python
@tool(
    "get_chatlog_stats",
    "获取聊天记录的统计信息，包括总消息数、发送者列表等。",
    {}  # 无参数
)
async def get_chatlog_stats(args: dict) -> dict:
    # ...
```

```python
@tool(
    "search_person",
    "搜索特定人物的所有相关消息记录。",
    {
        "person": str,            # 人物名称
        "include_context": bool   # 可选：是否包含上下文（默认true）
    }
)
async def search_person(args: dict) -> dict:
    # ...
```

```python
@tool(
    "list_topics",
    "列出聊天记录索引中的话题标签。",
    {
        "limit": int,     # 返回数量限制
        "pattern": str    # 筛选模式
    }
)
async def list_topics(args: dict) -> dict:
    # ...
```

```python
@tool(
    "search_by_topics",
    "根据话题标签检索消息行号。",
    {
        "topics": list,       # 话题列表
        "max_results": int    # 最大结果数
    }
)
async def search_by_topics(args: dict) -> dict:
    # ...
```

```python
@tool(
    "search_by_keywords",
    "根据关键词全文检索消息行号。可限定发送者。",
    {
        "keywords": list,         # 关键词列表
        "target_person": str,     # 目标人物（可选）
        "max_results": int,       # 最大结果数
        "match_all": bool         # 是否要求全部匹配
    }
)
async def search_by_keywords(args: dict) -> dict:
    # ...
```

```python
@tool(
    "load_messages",
    "根据行号加载消息内容，可选包含上下文与元数据。",
    {
        "line_numbers": list,       # 行号列表
        "context_before": int,      # 上文消息数
        "context_after": int,       # 下文消息数
        "include_metadata": bool    # 是否包含元数据
    }
)
async def load_messages(args: dict) -> dict:
    # ...
```

```python
@tool(
    "expand_query",
    "将问题扩展为关键词和话题标签（LLM 可选）。",
    {
        "question": str,       # 原始问题
        "target_person": str,  # 目标人物（可选）
        "use_llm": bool        # 是否使用 LLM 扩展
    }
)
async def expand_query(args: dict) -> dict:
    # ...
```

```python
@tool(
    "search_semantic",
    "使用语义向量召回相似消息。",
    {
        "query": str,    # 查询文本
        "top_k": int     # 返回数量
    }
)
async def search_semantic(args: dict) -> dict:
    # ...
```

```python
@tool(
    "filter_by_person",
    "过滤消息，确保内容与目标人物相关。",
    {
        "messages": list,      # 消息列表
        "target_person": str,  # 目标人物
        "use_llm": bool        # 是否使用 LLM 归因
    }
)
async def filter_by_person(args: dict) -> dict:
    # ...
```

```python
@tool(
    "format_messages",
    "格式化消息列表为文本。",
    {
        "messages": list,   # 消息列表
        "format": str,      # 格式类型 (compact/timeline/detailed)
        "max_chars": int    # 最大字符数
    }
)
async def format_messages(args: dict) -> dict:
    # ...
```

---

## 4. MCP Server 创建与工具注册

### 4.1 创建 MCP Server

```python
from claude_agent_sdk import create_sdk_mcp_server

def create_web_mcp_server():
    return create_sdk_mcp_server(
        name="web",           # MCP 服务名称
        version="1.0.0",      # 版本号
        tools=[               # 工具列表（装饰后的函数）
            web_search,
            web_fetch
        ],
    )
```

### 4.2 工具命名规范

工具在注册后，会被映射为标准的 MCP 工具名：

```
mcp__<server_name>__<tool_name>
```

| 定义时名称 | 运行时调用名 |
|-----------|-------------|
| `web_search` | `mcp__web__web_search` |
| `web_fetch` | `mcp__web__web_fetch` |
| `recall_memory` | `mcp__memory__recall_memory` |
| `remember` | `mcp__memory__remember` |
| `get_chatlog_stats` | `mcp__chatlog__get_chatlog_stats` |
| `search_by_topics` | `mcp__chatlog__search_by_topics` |

### 4.3 在 Agent 中注册 MCP Servers

```python
# tui_agent.py

from src.tools.web_search import create_web_mcp_server
from src.memory import create_memory_mcp_server
from src.chatlog import create_chatlog_mcp_server

mcp_servers = {
    "memory": create_memory_mcp_server(),
    "chatlog": create_chatlog_mcp_server(),
    "web": create_web_mcp_server(),
}

options = ClaudeAgentOptions(
    model=model,
    max_turns=max_turns,
    allowed_tools=routed_tools,
    mcp_servers=mcp_servers,  # 注册 MCP 服务
    agents=AGENT_DEFINITIONS,
)

client = await connect_with_retry(options)
```

---

## 5. Subagent（子代理）定义

### 5.1 AgentDefinition 格式

除了 MCP 工具，项目还支持定义 Subagent（子代理），使用 `AgentDefinition` 类：

```python
from claude_agent_sdk import AgentDefinition

AGENT_DEFINITIONS: dict[str, AgentDefinition] = {
    "explorer": AgentDefinition(
        description=(
            "Fast codebase exploration specialist. Use for quickly finding files, "
            "searching code patterns, understanding project structure..."
        ),
        prompt="""You are a codebase exploration specialist.
        
Your task is to quickly and efficiently explore codebases...

Guidelines:
- Use Glob to find files by pattern
- Use Grep to search for code patterns and keywords
- Use Read to examine file contents
...""",
        tools=["Glob", "Grep", "Read"],  # 允许的工具列表
        model="haiku"                     # 使用的模型
    ),
    
    "coder": AgentDefinition(
        description="Code implementation specialist...",
        prompt="You are a senior software developer...",
        tools=["Read", "Edit", "Write", "Bash", "Glob", "Grep"],
        model="inherit"  # 继承父模型
    ),
}
```

### 5.2 AgentDefinition 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `description` | `str` | 何时使用该子代理的说明，LLM 据此决定调用 |
| `prompt` | `str` | 子代理的系统提示词 |
| `tools` | `list[str]` | 允许使用的工具名列表 |
| `model` | `str` | 模型选择：`"haiku"`, `"sonnet"`, `"opus"`, `"inherit"` |

### 5.3 项目中定义的 Subagents

| Agent 名称 | 职责 | 工具权限 | 模型 |
|-----------|------|---------|------|
| `explorer` | 代码库探索 | Glob, Grep, Read | haiku（快速） |
| `planner` | 任务规划 | Read, Glob, Grep | inherit |
| `coder` | 代码实现 | Read, Edit, Write, Bash, Glob, Grep | inherit |
| `reviewer` | 代码审查 | Read, Grep, Glob | inherit |
| `debugger` | 调试问题 | Read, Grep, Glob, Bash | sonnet |
| `test-runner` | 测试执行 | Bash, Read, Grep | haiku（快速） |

---

## 6. 工具返回格式规范

### 6.1 标准 MCP 响应格式

```python
return {
    "content": [
        {
            "type": "text",
            "text": "工具执行结果文本..."
        }
    ]
}
```

### 6.2 项目中的扩展格式

项目中使用了更丰富的结构化响应：

```python
# 成功响应
def _success(data: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> dict:
    return {
        "ok": True,
        "data": data,
        "meta": meta or {},
        "content": [{
            "type": "text",
            "text": json.dumps(data, ensure_ascii=False, indent=2)
        }]
    }

# 错误响应
def _error(message: str, meta: Optional[Dict[str, Any]] = None) -> dict:
    return {
        "ok": False,
        "error": message,
        "meta": meta or {},
        "content": [{
            "type": "text",
            "text": f"错误: {message}"
        }]
    }
```

### 6.3 响应示例

**成功响应：**
```json
{
    "ok": true,
    "data": {
        "line_numbers": [10, 25, 42],
        "total_matches": 3,
        "topic_breakdown": {"消费": 2, "习惯": 1}
    },
    "meta": {
        "available": true,
        "source": "index",
        "timing_ms": 15
    },
    "content": [{"type": "text", "text": "..."}]
}
```

**错误响应：**
```json
{
    "ok": false,
    "error": "请提供至少一个关键词",
    "meta": {"source": "scan"},
    "content": [{"type": "text", "text": "错误: 请提供至少一个关键词"}]
}
```

---

## 7. 与 Kimi API 格式的详细对比

### 7.1 结构差异

```
┌─────────────────────────────────────────────────────────────────┐
│                      Kimi API 格式                               │
├─────────────────────────────────────────────────────────────────┤
│  tools = [                                                      │
│      {                                                          │
│          "type": "function",           ◀── 固定值               │
│          "function": {                 ◀── 嵌套层级              │
│              "name": "search",                                  │
│              "description": "...",                              │
│              "parameters": {                                    │
│                  "type": "object",     ◀── 固定值               │
│                  "required": [...],    ◀── 必填参数列表          │
│                  "properties": {       ◀── 参数定义              │
│                      "query": {                                 │
│                          "type": "string",                      │
│                          "description": "..."                   │
│                      }                                          │
│                  }                                              │
│              }                                                  │
│          }                                                      │
│      }                                                          │
│  ]                                                              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                  Claude Agent SDK 格式                           │
├─────────────────────────────────────────────────────────────────┤
│  @tool(                                                         │
│      "search",                         ◀── name                 │
│      "通过搜索引擎搜索...",             ◀── description           │
│      {                                 ◀── parameters (简化)     │
│          "query": str,                 ◀── 直接类型映射           │
│      }                                                          │
│  )                                                              │
│  async def search(args: dict) -> dict: ◀── 函数立即绑定          │
│      ...                                                        │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 功能对比表

| 功能 | Kimi API | Claude Agent SDK |
|------|----------|------------------|
| 必填参数声明 | ✅ `required: [...]` | ❌ 无原生支持 |
| 参数描述 | ✅ 每个参数有 `description` | ❌ 仅注释 |
| 嵌套对象 | ✅ 通过 `properties` 嵌套 | ⚠️ 需使用 `dict` |
| 枚举类型 | ✅ `enum: [...]` | ❌ 无原生支持 |
| 默认值 | ⚠️ 需在代码中处理 | ⚠️ 需在代码中处理 |
| 类型约束 | ✅ JSON Schema 类型 | ⚠️ Python 类型推断 |
| 代码绑定 | ❌ 需手动分发 | ✅ 装饰器自动绑定 |
| 异步支持 | 取决于实现 | ✅ 原生 async |

### 7.3 项目中的变通方案

由于 SDK 简化格式的限制，项目采用以下变通方案：

**1. 参数描述放在注释中：**
```python
@tool(
    "recall_memory",
    "根据话题或关键词检索相关的用户记忆...",
    {
        "topic": str,      # 搜索话题或关键词
        "limit": int       # 返回结果数量限制（默认5）
    }
)
```

**2. 默认值在函数内处理：**
```python
async def recall_memory(args: dict) -> dict:
    topic = args.get("topic", "")       # 默认空字符串
    limit = args.get("limit", 5)        # 默认5
```

**3. 枚举约束通过描述文字说明：**
```python
@tool(
    "remember",
    "保存用户明确要求记住的信息。类别包括：preference（偏好）、fact（事实）、opinion（观点）、attitude（态度）。",
    {"category": str, ...}
)
```

---

## 8. 配置文件：`.mcp.json`

项目根目录的 `.mcp.json` 文件定义了 MCP 服务的启动配置：

```json
{
  "mcpServers": {
    "web": {
      "command": "python",
      "args": ["-m", "src.tools.web_search"],
      "env": {
        "TAVILY_API_KEY": "${TAVILY_API_KEY}"
      }
    },
    "memory": {
      "command": "python",
      "args": ["-m", "src.memory.mcp_server"],
      "env": {
        "POE_API_KEY": "${POE_API_KEY}"
      }
    },
    "chatlog": {
      "command": "python",
      "args": ["-m", "src.chatlog.mcp_server"],
      "env": {}
    }
  }
}
```

---

## 9. 工具定义最佳实践

### 9.1 命名规范

| 规则 | 示例 |
|------|------|
| 使用小写字母和下划线 | `search_by_keywords`, `get_user_profile` |
| 动词开头表示操作 | `get_`, `search_`, `list_`, `load_`, `format_` |
| 清晰表达功能 | `filter_by_person` 而非 `filter` |

### 9.2 描述规范

- **中文描述**：面向中文用户时使用中文
- **说明使用场景**：告诉 LLM 何时应该调用此工具
- **列出可选值**：如果参数有固定选项，在描述中说明

```python
@tool(
    "remember",
    "保存用户明确要求记住的信息。类别包括：preference（偏好）、fact（事实）、opinion（观点）、attitude（态度）。",
    {...}
)
```

### 9.3 参数设计

- **保持扁平**：避免深层嵌套
- **类型明确**：使用 Python 基础类型
- **提供默认值**：在函数内使用 `args.get(key, default)`

### 9.4 响应设计

- **结构化返回**：使用 `data` + `meta` 分离核心数据和元信息
- **错误处理**：统一使用 `ok: bool` 标识成功/失败
- **性能追踪**：在 `meta` 中返回 `timing_ms`

---

## 10. 完整工具清单

| MCP Server | 工具名 | 参数 | 描述 |
|------------|--------|------|------|
| **web** | `web_search` | query, max_results, search_depth | 网络搜索 |
| **web** | `web_fetch` | url, max_bytes | 抓取网页 |
| **memory** | `recall_memory` | topic, limit | 检索记忆 |
| **memory** | `remember` | category, content, key, value | 保存记忆 |
| **memory** | `get_user_profile` | (无) | 获取用户画像 |
| **memory** | `list_memories` | category, limit | 列出记忆 |
| **memory** | `forget` | memory_id | 删除记忆 |
| **chatlog** | `get_chatlog_stats` | (无) | 聊天统计 |
| **chatlog** | `search_person` | person, include_context | 搜索人物 |
| **chatlog** | `list_topics` | limit, pattern | 列出话题 |
| **chatlog** | `search_by_topics` | topics, max_results | 按话题搜索 |
| **chatlog** | `search_by_keywords` | keywords, target_person, max_results, match_all | 关键词搜索 |
| **chatlog** | `load_messages` | line_numbers, context_before, context_after, include_metadata | 加载消息 |
| **chatlog** | `expand_query` | question, target_person, use_llm | 扩展查询 |
| **chatlog** | `search_semantic` | query, top_k | 语义搜索 |
| **chatlog** | `filter_by_person` | messages, target_person, use_llm | 人物过滤 |
| **chatlog** | `format_messages` | messages, format, max_chars | 格式化消息 |

---

## 11. 总结

### 11.1 BENEDICTJUN 的工具定义特点

1. **装饰器驱动**：使用 `@tool` 装饰器，代码即配置
2. **类型简化**：直接使用 Python 类型，SDK 自动转换为 JSON Schema
3. **函数绑定**：工具定义与实现函数紧密结合
4. **MCP 规范**：遵循 Model Context Protocol，工具名自动映射

### 11.2 与 Kimi API 的核心差异

| 设计理念 | Kimi API | Claude Agent SDK |
|----------|----------|------------------|
| 配置方式 | 数据驱动（JSON） | 代码驱动（装饰器） |
| 灵活性 | 高（完整 JSON Schema） | 中（类型映射简化） |
| 开发效率 | 需要大量手动配置 | 简洁高效 |
| 类型安全 | 运行时校验 | 静态类型提示 |

### 11.3 推荐使用场景

- **复杂参数约束**（枚举、嵌套）：Kimi API 格式更灵活
- **快速开发**：Claude Agent SDK 的 `@tool` 装饰器更高效
- **类型安全**：SDK 配合 Python 类型提示更可靠

---

*文档生成时间：2026-01-11*  
*项目版本：v0.5.0*

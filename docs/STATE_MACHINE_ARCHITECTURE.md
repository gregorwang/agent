# BENEDICTJUN 状态机架构文档

本文档详细说明 BENEDICTJUN Agent 系统的状态机设计，包括主循环状态流转、子系统状态、以及各个模块之间的协作关系。

---

## 1. 系统概述

BENEDICTJUN 是一个基于 Claude Agent SDK 的终端 AI 代理系统，采用 **事件驱动的状态机架构**。系统的核心是一个主循环（`main()` 函数），通过监听用户输入和 SDK 响应来驱动状态流转。

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BENEDICTJUN 系统架构                              │
├─────────────────────────────────────────────────────────────────────┤
│  用户输入  ──▶  命令调度器  ──▶  状态管理  ──▶  SDK 执行  ──▶  响应处理  │
│                    ↑                                      │         │
│                    └──────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 主循环状态机

### 2.1 状态图

```
状态 1：初始化
    ↓
    （条件：环境加载完成）
    ↓
状态 2：等待用户输入
    ↓
    （条件 A：收到 "/" 开头的命令）→ 状态 3：命令处理
    （条件 B：收到普通文本）→ 状态 4：查询预处理
    （条件 C：收到 Ctrl+C/EOF）→ 状态 10：清理退出
    ↓
状态 3：命令处理
    ↓
    （条件 A：命令由 Dispatcher 处理）→ 回到状态 2
    （条件 B：/exit 命令）→ 状态 10：清理退出
    （条件 C：需要重连）→ 设置 reconnect=True，回到状态 2
    ↓
状态 4：查询预处理
    ↓
    （条件：检查技能激活、历史追加）
    ↓
状态 5：连接管理
    ↓
    （条件 A：需要重连 reconnect=True）→ 建立 SDK 连接
    （条件 B：已连接）→ 跳过连接步骤
    ↓
状态 6：执行模式选择
    ↓
    （条件 A：react_mode=True）→ 状态 7：ReAct 执行
    （条件 B：react_mode=False）→ 状态 8：标准查询执行
    ↓
状态 7：ReAct 执行
    ↓
    （循环：Thought → Action → Observation）
    ↓
状态 8：标准查询执行
    ↓
    （条件：发送查询到 SDK）
    ↓
状态 9：响应流处理
    ↓
    （循环：处理 AssistantMessage / ToolUseBlock / ResultMessage）
    ↓
    （条件：收到 ResultMessage）→ 状态 2（继续等待输入）
    ↓
状态 10：清理退出
    ↓
    （条件：保存上下文、断开连接）
    ↓
状态 11：结束
```

### 2.2 状态详细说明

| 状态 | 名称 | 触发条件 | 行为 |
|------|------|----------|------|
| S1 | 初始化 | 程序启动 | 加载环境变量、配置文件、创建 Session/Context Manager |
| S2 | 等待输入 | 前一状态完成 | 显示 prompt，等待 `prompt_toolkit` 输入 |
| S3 | 命令处理 | 输入以 `/` 开头 | `CommandDispatcher` 路由到相应 Handler |
| S4 | 查询预处理 | 非命令文本输入 | 追加历史、激活技能、准备 prompt |
| S5 | 连接管理 | 进入查询流程 | 检查客户端状态，必要时重连 |
| S6 | 模式选择 | 连接就绪 | 根据 `react_mode` 分流 |
| S7 | ReAct 执行 | `react_mode=True` | 执行 Thought→Action→Observation 循环 |
| S8 | 标准查询 | `react_mode=False` | 调用 `run_query()` |
| S9 | 响应处理 | 查询发送后 | 流式处理 SDK 响应消息 |
| S10 | 清理退出 | `/exit` 或 Ctrl+C | 保存状态、断开连接 |
| S11 | 结束 | 清理完成 | 程序终止 |

---

## 3. 命令调度状态机 (CommandDispatcher)

### 3.1 状态图

```
状态 1：接收命令
    ↓
    （条件：解析命令名称和参数）
    ↓
状态 2：查找 Handler
    ↓
    （条件 A：找到匹配的 Handler）→ 状态 3
    （条件 B：未找到）→ 返回 not_handled
    ↓
状态 3：执行 Handler
    ↓
    （条件 A：执行成功）→ 返回 CommandResult.success()
    （条件 B：执行失败）→ 返回 CommandResult.fail(error)
    （条件 C：需要退出）→ 返回 CommandResult.exit()
```

### 3.2 Handler 分类

| Handler 类型 | 命令 | 文件位置 |
|-------------|------|----------|
| Session | `/session`, `/reset`, `/resume`, `/fork`, `/sessions` | `src/commands/session.py` |
| Model | `/model`, `/tools`, `/max`, `/continue`, `/thinking` | `src/commands/model.py` |
| Utility | `/help`, `/info`, `/context`, `/compact`, `/agents`, `/exit`, `/quit` | `src/commands/utility.py` |

---

## 4. 查询执行状态机 (run_query)

### 4.1 状态图

```
状态 1：初始化统计
    ↓
    （条件：创建 TurnStats，记录开始时间）
    ↓
状态 2：准备查询参数
    ↓
    （条件：设置 session_id, thinking 配置）
    ↓
状态 3：发送查询
    ↓
    （条件 A：成功）→ 状态 4
    （条件 B：超时）→ 状态 8：处理超时错误
    ↓
状态 4：等待响应流
    ↓
    （循环处理消息）
    ↓
状态 5：处理 AssistantMessage
    ↓
    （条件 A：TextBlock）→ 渲染 Markdown
    （条件 B：ThinkingBlock）→ 显示思考过程（如启用）
    （条件 C：ToolUseBlock）→ 显示工具调用
    （条件 D：ToolResultBlock）→ 显示工具结果
    ↓
状态 6：处理 ResultMessage
    ↓
    （条件：更新 Session、记录 token 使用量）
    ↓
状态 7：完成
    ↓
    （条件：打印统计信息，检查是否需要 compact）
    ↓
状态 8：错误处理
    ↓
    （条件：显示错误信息）
```

### 4.2 消息类型映射

| SDK 消息类型 | 处理行为 |
|-------------|----------|
| `SystemMessage (init)` | 捕获 session_id，更新 SessionManager |
| `AssistantMessage` | 解析 content blocks，分类处理 |
| `StreamEvent` | 实时更新显示文本（流式输出） |
| `ResultMessage` | 标记查询结束，提取最终结果和 token 统计 |

---

## 5. ReAct 执行状态机

### 5.1 状态图

```
状态 1：开始任务
    ↓
    （条件：初始化 ReActTrace）
    ↓
状态 2：执行步骤（最多 max_steps 次）
    ↓
    ╭──────────────────────────────────────╮
    │ 步骤内部循环：                        │
    │                                      │
    │ 状态 2a：构建 Prompt                 │
    │     ↓                                │
    │ 状态 2b：发送查询                    │
    │     ↓                                │
    │ 状态 2c：解析 Thought                │
    │     ↓                                │
    │ 状态 2d：执行 Action                 │
    │     ↓                                │
    │ 状态 2e：记录 Observation            │
    ╰──────────────────────────────────────╯
    ↓
    （条件 A：action 包含 "Final Answer"）→ 状态 3：完成
    （条件 B：未达到 max_steps）→ 回到状态 2
    ↓
状态 3：完成
    ↓
    （条件：设置 trace.success = True，返回 trace）
```

### 5.2 ReAct 步骤结构

```python
@dataclass
class ReActStep:
    step_number: int
    thought: str          # 思考过程
    action: str | None    # 要执行的工具名
    action_input: dict    # 工具输入参数
    observation: str      # 工具执行结果
    is_final: bool        # 是否为最终答案
```

---

## 6. Session 管理状态机

### 6.1 状态图

```
┌─────────────────────────────────────────────────────┐
│                  Session 生命周期                    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  create_session()                                  │
│       ↓                                            │
│  ╔═══════════╗                                     │
│  ║  CREATED  ║──▶ get_current_session_id()        │
│  ╚═══════════╝                                     │
│       │                                            │
│       ├── update_session() ──▶ 更新消息计数/名称   │
│       │                                            │
│       ├── fork_session() ──▶ 创建分支会话          │
│       │        │                                   │
│       │        └──▶ [NEW FORKED SESSION]           │
│       │                                            │
│       ├── resume ──▶ 恢复到此会话                  │
│       │                                            │
│       └── delete_session() ──▶ 删除会话            │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 6.2 存储结构

```
.claude/sessions/
├── sessions.json           # 所有会话的元数据索引
└── <session_id>.jsonl      # 每个会话的对话历史
```

---

## 7. Context 管理状态机

### 7.1 状态图

```
状态 1：正常运行
    ↓
    （每次添加消息后检查 token_usage_ratio）
    ↓
    （条件 A：usage_ratio < 0.8）→ 保持状态 1
    （条件 B：usage_ratio >= 0.8）→ 状态 2：需要压缩
    ↓
状态 2：需要压缩
    ↓
    （条件 A：用户执行 /compact）→ 状态 3
    （条件 B：继续添加消息）→ 显示警告，保持状态 2
    ↓
状态 3：执行压缩
    ↓
    （条件：保留最近 keep_recent 条消息，生成摘要）
    ↓
状态 4：压缩完成
    ↓
    （条件：回到状态 1）
```

### 7.2 关键阈值

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `compact_threshold` | 0.8 (80%) | 触发压缩警告的 token 使用率 |
| `keep_recent` | 10 | 压缩时保留的最近消息数 |
| `max_tokens` | 根据模型 | Claude Sonnet: ~100k |

---

## 8. Chatlog 查询状态机

### 8.1 原子工具组合流程

```
状态 1：接收查询
    ↓
    （条件：用户输入问题）
    ↓
状态 2：关键词扩展（可选）
    ↓
    （条件：调用 expand_query 生成关键词列表）
    ↓
状态 3：多路检索
    ↓
    ╭────────────────────────────────────────────────╮
    │ 并行执行：                                      │
    │  • search_by_topics(topics)                   │
    │  • search_by_keywords(keywords)               │
    │  • search_semantic(query) [可选]              │
    ╰────────────────────────────────────────────────╯
    ↓
状态 4：合并行号
    ↓
    （条件：去重、按相关性排序）
    ↓
状态 5：加载消息
    ↓
    （条件：调用 load_messages，扩展上下文窗口）
    ↓
状态 6：人物过滤（可选）
    ↓
    （条件 A：指定 target_person）→ 调用 filter_by_person
    （条件 B：未指定）→ 跳过
    ↓
状态 7：格式化输出
    ↓
    （条件：调用 format_messages，返回结果）
```

### 8.2 MCP 工具列表

| 工具 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `get_chatlog_stats` | 获取统计信息 | - | 消息数、发送者等 |
| `list_topics` | 列出所有话题 | limit | 话题列表 |
| `search_by_topics` | 按话题搜索 | topics[] | 行号列表 |
| `search_by_keywords` | 按关键词搜索 | keywords[] | 行号列表 |
| `load_messages` | 加载消息内容 | line_numbers[], window | 消息列表 |
| `expand_query` | 扩展查询 | question | keywords[], topics[] |
| `search_semantic` | 语义搜索 | query, limit | 行号列表 |
| `filter_by_person` | 人物过滤 | messages, person | 过滤后消息 |
| `format_messages` | 格式化消息 | messages | 格式化文本 |

---

## 9. Memory 系统状态机

### 9.1 记忆提取流程

```
状态 1：对话结束
    ↓
    （条件：触发后台提取）
    ↓
状态 2：发送到 GPT-5-nano（Poe API）
    ↓
    （条件：提取 preferences/facts/opinions/attitudes）
    ↓
状态 3：冲突检测
    ↓
    （条件 A：无冲突）→ 状态 4：保存记忆
    （条件 B：有冲突）→ 状态 5：等待解决
    ↓
状态 4：保存记忆
    ↓
    （条件：写入 memories.json）
    ↓
状态 5：等待解决
    ↓
    （条件：用户执行 /memory resolve）
    ↓
状态 6：应用解决方案
    ↓
    （条件 A：replace）→ 替换旧记忆
    （条件 B：keep_both）→ 同时保留
    （条件 C：ignore）→ 丢弃新信息
```

### 9.2 MCP 工具

| 工具 | 功能 |
|------|------|
| `recall_memory` | 按主题搜索记忆 |
| `remember` | 保存用户请求的记忆 |
| `get_user_profile` | 获取用户画像 |
| `list_memories` | 列出所有记忆 |
| `forget` | 删除指定记忆 |

---

## 10. 技能系统状态机

### 10.1 状态图

```
状态 1：技能发现
    ↓
    （条件：扫描 .claude/skills/ 目录）
    ↓
状态 2：技能加载
    ↓
    （条件：解析 SKILL.md 文件）
    ↓
状态 3：待命
    ↓
    （条件 A：用户执行 /skills enable）→ 状态 4
    （条件 B：无匹配）→ 保持状态 3
    ↓
状态 4：技能激活
    ↓
    （条件：将技能指令注入到 prompt）
    ↓
    （查询完成后）→ 回到状态 3
```

---

## 11. 连接与重试状态机

### 11.1 状态图

```
状态 1：开始连接
    ↓
    （尝试连接 SDK）
    ↓
    （条件 A：成功）→ 状态 4：已连接
    （条件 B：失败）→ 状态 2：重试等待
    ↓
状态 2：重试等待
    ↓
    （条件：指数退避等待 1s * 2^attempt）
    ↓
状态 3：重试连接
    ↓
    （尝试次数 < MAX_RECONNECT_ATTEMPTS）
    ↓
    （条件 A：成功）→ 状态 4
    （条件 B：失败且次数未满）→ 回到状态 2
    （条件 C：次数已满）→ 状态 5：连接失败
    ↓
状态 4：已连接
    ↓
    （正常运行）
    ↓
状态 5：连接失败
    ↓
    （抛出 ConnectionError）
```

### 11.2 超时配置

| 参数 | 值 | 说明 |
|------|------|------|
| `MAX_RECONNECT_ATTEMPTS` | 3 | 最大重试次数 |
| `RECONNECT_DELAY_BASE` | 1.0s | 基础重试延迟 |
| `QUERY_TIMEOUT` | 300s (5min) | 查询超时 |
| `RESPONSE_IDLE_TIMEOUT` | 120s | 响应空闲超时 |
| `RESPONSE_TOTAL_TIMEOUT` | 300s | 响应总超时 |

---

## 12. 整体状态转换矩阵

| 当前状态 | 触发事件 | 目标状态 | 动作 |
|----------|----------|----------|------|
| 等待输入 | 命令输入 | 命令处理 | 解析并调度 |
| 等待输入 | 普通输入 | 查询预处理 | 追加历史 |
| 等待输入 | Ctrl+C | 清理退出 | 保存状态 |
| 命令处理 | /exit | 清理退出 | 断开连接 |
| 命令处理 | 其他命令 | 等待输入 | 执行命令 |
| 查询预处理 | 完成 | 连接管理 | 检查连接 |
| 连接管理 | 需要重连 | 建立连接 | connect_with_retry() |
| 连接管理 | 已连接 | 模式选择 | 跳过连接 |
| 模式选择 | react_mode=True | ReAct执行 | ReActController.run() |
| 模式选择 | react_mode=False | 标准查询 | run_query() |
| 响应处理 | ResultMessage | 等待输入 | 更新Session |
| 响应处理 | 超时 | 等待输入 | 显示警告 |

---

## 13. 文件与模块映射

| 状态机 | 主要文件 | 关键类/函数 |
|--------|----------|-------------|
| 主循环 | `tui_agent.py` | `main()`, `run_query()` |
| 命令调度 | `src/commands/__init__.py` | `CommandDispatcher` |
| Session 管理 | `src/session/persistence.py` | `SessionManager` |
| Context 管理 | `src/context/manager.py` | `ContextManager` |
| ReAct 执行 | `src/agents/react.py` | `ReActController` |
| Chatlog 查询 | `src/chatlog/mcp_server.py` | `_query_chatlog_composed_impl()` |
| Memory 系统 | `src/memory/` | `MemoryStorage`, `MemoryExtractor` |
| 技能系统 | `src/skills/` | `SkillManager` |
| 连接管理 | `tui_agent.py` | `connect_with_retry()` |

---

## 14. 总结

BENEDICTJUN 采用了 **分层状态机架构**：

1. **主循环状态机**：控制整体流程（输入→处理→响应→循环）
2. **命令调度状态机**：路由斜杠命令到相应处理器
3. **查询执行状态机**：管理与 SDK 的交互和响应流处理
4. **子系统状态机**：Session、Context、Memory、Skills 各自维护独立状态

这种设计实现了：
- **关注点分离**：每个模块职责清晰
- **可扩展性**：易于添加新命令和功能
- **健壮性**：通过重试和超时机制处理异常
- **可维护性**：状态转换逻辑清晰可追踪

---

*文档生成时间：2026-01-11*  
*项目版本：v0.5.0*

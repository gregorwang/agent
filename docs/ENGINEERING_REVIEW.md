# 工程化评审 - BENEDICTJUN

## 范围
本评审从可靠性、可维护性、可观测性、安全卫生以及面向生产的可用性角度，评估该项目的工程质量。评审对象为当前仓库状态（代码、脚本与配置文件）。

## MCP 文档参考（Context7）
- Claude Agent SDK（Python）文档：会话管理、工具调用、MCP Server、流式处理。

## 优势
1. **模块划分清晰**：`session`、`context`、`memory`、`chatlog`、`agents`、`ui` 等模块边界明确，利于理解与维护。
2. **工具集成务实**：MCP server 的注册和工具可用性清晰且集中，便于追踪与扩展。
3. **TUI 体验完善**：Command dispatcher + prompt_toolkit 组合提升交互效率，利于快速迭代功能。
4. **Chatlog 索引优化**：元数据索引方案能有效提升历史记录检索性能。
5. **上下文安全改进**：工具输出限制与动态会话行为降低了 token 爆炸风险。

## 关键不足 / 风险（按影响优先级排序）

### 1）可靠性与回归保护
**风险**：没有正式的自动化测试与 CI。  
**影响**：高。对 prompt 流程、会话逻辑、工具输出、MCP 集成的修改容易引发回归。  
**证据**：仅有脚本级测试：`scripts/test_chatlog_limits.py` 与 `scripts/test_chatlog_topics.py`。  
**建议**：
- 引入最小化测试框架（如 `pytest`）并接入 CI。
- 针对关键链路（chatlog 链、session/continue 逻辑、prompt 格式）做 golden 测试。

### 2）敏感信息与产物管理
**风险**：运行时产物与环境文件纳入版本控制。  
**影响**：中到高（取决于部署环境）。  
**证据**：`.env`、`history.jsonl`、`session.json`、`context_state.json`、chatlog 数据等在仓库根目录。  
**建议**：
- 添加 `.gitignore` 排除运行时产物。
- 仅保留 `.env.example`，避免提交真实密钥。

### 3）可观测性与诊断
**风险**：大量核心流程使用 `print()`，缺乏结构化日志与日志等级。  
**影响**：中。调试、过滤与后期审计困难。  
**证据**：`src/chatlog/mcp_server.py`、`src/chatlog/cleaner.py` 等路径。  
**建议**：
- 使用 `logging` 并引入统一日志格式（建议 JSON Lines）。
- 将关键字段（session_id、tool_name、耗时、命中数量）结构化记录。

### 4）外部客户端资源清理
**风险**：HTTP session 生命周期依赖人工关闭，缺少统一关闭机制。  
**影响**：中。长会话可能泄露连接或触发连接池限制。  
**证据**：`src/memory/poe_client.py`。  
**建议**：
- 引入统一的 client lifecycle 管理器。
- 统一在退出流程中执行 `close()`。

### 5）配置项分散且难以校验
**风险**：多处使用 env 默认值，缺少统一校验与聚合展示。  
**影响**：中。配置漂移导致环境差异不可控。  
**证据**：`tui_agent.py`、`src/chatlog/cleaner.py`、`src/chatlog/mcp_server.py`。  
**建议**：
- 用 dataclass 或 pydantic 做统一配置模型。
- 增加 `/config` 命令展示“实际生效配置”。

### 6）会话与上下文语义隐式
**风险**：resume/fork/continue 等语义分散在多个模块。  
**影响**：中。边界场景不易维护。  
**证据**：`tui_agent.py` + `src/session/*` + `src/context/*`。  
**建议**：
- 提取为统一 session controller。
- 对 compaction 阈值加入可视化与指标。

### 7）数据规模与性能防护不足
**风险**：大规模 chatlog 缺少明确的配额与回压策略。  
**影响**：中。极端情况下性能不可控。  
**证据**：`src/chatlog/loader.py`、`src/chatlog/mcp_server.py`。  
**建议**：
- 增加更多可调上限（结果数、上下文窗口）。
- 对大型数据集提供 lazy loading 或分段索引。

## 分模块评审

### TUI (`tui_agent.py`, `src/ui/*`)
- **优势**：结构清晰，交互式组件完整。
- **不足**：UI 状态与业务状态分散，命令扩展会越来越重。
- **建议**：引入统一 UI controller，规范状态传递规则。

### Session & Context (`src/session/*`, `src/context/*`)
- **优势**：可持久化，易于理解。
- **不足**：会话策略分散，context 估算与真实 token 可能偏差。
- **建议**：集中策略模块，并增加回归测试覆盖。

### Chatlog (`src/chatlog/*`)
- **优势**：索引结构合理，召回性能不错。
- **不足**：多层 heuristic（topic/keyword/cleaner），缺少稳定性测试。
- **建议**：增加 topic/cleaning 的确定性测试与召回指标统计。

### Memory (`src/memory/*`)
- **优势**：组件拆分合理。
- **不足**：外部 API 生命周期与错误处理不统一。
- **建议**：加入 retry/backoff 与统一退出清理逻辑。

### Tools & Permissions (`src/tools/*`, `src/permissions.py`)
- **优势**：权限模型直观清晰。
- **不足**：缺少测试与审计日志。
- **建议**：增加 tool ledger（JSONL）记录所有工具使用情况。

### Skills (`src/skills/*`)
- **优势**：扩展友好。
- **不足**：缺少格式校验，技能文件可能存在隐性错误。
- **建议**：提供 `/skills doctor` 检查功能。

### Router (`src/router.py`)
- **优势**：模型路由抽象良好。
- **不足**：无测试覆盖。
- **建议**：添加路由逻辑单测。

## 可运维准备清单
- [ ] CI：lint + tests
- [ ] .gitignore 排除运行时产物
- [ ] 统一配置 schema
- [ ] 结构化日志
- [ ] 工具调用审计
- [ ] 外部 client 生命周期管理
- [ ] 版本管理与 Release notes

## 额外观察
1. **数据治理**：chatlog 与导出文件放在代码库中，建议分离存储。
2. **性能监控**：chatlog index load 频率高，可考虑缓存与显式 reload。
3. **跨平台支持**：当前更偏向 Windows/PowerShell，若需跨平台建议抽象 CLI 与路径处理。
4. **依赖管理**：建议增加 lockfile 或固定依赖版本提升复现能力。

## 结论
该项目在 agent 架构与交互体验上已经很成熟，核心问题主要集中在工程化护栏：测试、日志、配置、资源清理。补齐这些基础设施后，可显著提高稳定性与生产可用性。

# BENEDICTJUN - 快速切换模型指南

## 方法 1：通过 .env 文件（启动时默认）
编辑 `.env` 文件，修改 `ANTHROPIC_MODEL` 的值：

```env
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_AUTH_TOKEN=你的Claude_API_KEY
ANTHROPIC_MODEL=claude-3-5-sonnet-latest  # 改这里
TAVILY_API_KEY=你的Tavily_KEY
```

**可选的 Claude 模型：**
- `claude-3-5-sonnet-latest` - 平衡性能和成本（推荐）
- `claude-3-5-haiku-latest` - 快速、便宜
- `claude-opus-4-20250514` - 最强大，支持扩展思考

## 方法 2：运行时动态切换（不重启）
在 TUI 界面中输入 `/model` 命令：

```bash
# 查看当前模型和建议列表
> /model

# 切换到其他模型
> /model claude-3-5-haiku-latest
> /model claude-opus-4-20250514
```

## 方法 3：通过配置文件持久化
切换模型后，使用 `/save` 保存配置：

```bash
> /model claude-opus-4-20250514
> /save
```

下次启动会自动加载保存的模型。

## 模型选择建议

| 模型 | 用途 | 速度 | 成本 |
|------|------|------|------|
| Haiku 3.5 | 快速探索、代码搜索、简单问答 | ⚡⚡⚡ | 💰 |
| Sonnet 3.5 | 日常编程、复杂任务、平衡之选 | ⚡⚡ | 💰💰 |
| Opus 4 | 复杂推理、架构设计、难题 | ⚡ | 💰💰💰 |

## 子代理（Subagent）的模型
在 `src/agents/definitions.py` 中，每个子代理可以指定自己的模型：
- `explorer`: 使用 `haiku`（快速探索）
- `coder`, `planner`, `reviewer`: 使用 `sonnet`（平衡）
- 可自定义为 `opus` 以获得更强能力

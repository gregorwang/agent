先基于你这份概况里“真实发生了什么”把问题拆开讲清楚，再给你一套**能落地改代码/改工具定义/改调用策略**的方案。

---

## 你这次 42 万 token 到底是哪一种“异常”？

从日志看，实际是：

- **Input tokens = 434,532**
- **Output tokens = 406**

也就是说**爆掉的是“输入”**（模型每一轮要吃进来的上下文/工具返回），不是模型生成输出本身。你觉得“output 42 万”大概率是把 usage 面板里那个 _Input_ 看成了 output，或者把“总消耗”理解成 output。

而且你这轮只有 7 次工具调用，却把输入堆到了 43 万——这几乎只能说明一件事：

> **某个（或多个）工具返回里塞进了大块内容**（例如：整份 chatlog、整份 topics 列表、整份 index 映射、或者非常长的 messages 列表），并且这些内容被“完整写回”到下一轮模型输入里。

文档里有两个强烈的“嫌疑点”：

1. `expand_query` 调用后出现了 **“[INDEX] Loaded index: 1771 topics, 3717 messages”**，而你文件前面又展示了 `available_topics` 这种超长数组（1771 个 topic）。如果工具把 **available_topics 全量**返回给主模型一次，就能吃掉非常多 token。
2. `search_by_keywords` 每次都显示 “Loaded 3717 messages from chatlog”，而你又提到“加载消息太多”。如果这个工具（哪怕是误操作/调试模式）把 **3717 条 message 内容**一并返回，就很容易直接几十万 token。

---

## 1) Token 优化：给你一套“止血 + 根治”的可落地方案

下面按优先级来（越靠前越能立刻把 token 打下来）。

### A. 先做“定位”——你必须知道到底哪个工具在喷大包

在 MCP 服务端（或你封装工具的那层）加一个统一的**工具返回体积监控**：

- 每次工具返回前，计算：

  - `chars = len(json.dumps(result))`
  - `approx_tokens = chars / 3~4`（中文粗估），或者用 tiktoken 精确算

- 打印日志：`tool_name / chars / approx_tokens / keys_top_level`
- 如果超过阈值（比如 12k chars 或 3k tokens），直接标红并截断

你现在的问题不需要猜；**跑一次就能定位哪个 tool 在返回巨量内容**。

> 验收标准：你能看到 “哪一次 tool call 返回了 80k+ tokens”。

---

### B. 立刻止血：给所有工具加“硬上限 + 结构化截断”，并且**在工具层截断**（不是 UI 层 4000 chars）

你文档里提到 `CHATLOG_MAX_RETURN_CHARS=4000` 是“文本响应层面”。这往往意味着：
**用户界面看起来被截断了，但实际工具返回 JSON 仍完整进入模型上下文**——token 还是照炸。

你要做的是：**在工具返回给模型之前**就截断。

推荐做法（非常关键）：

1. **任何 list 字段（messages、topics、line_numbers）都要强制 topK**
2. 超出部分不要丢掉信息：返回 `omitted_count` 和 `next_cursor`
3. 大文本字段（content）做 `snippet`，保留原始引用 id

示例（返回结构建议）：

```json
{
  "items": [ ...最多20条... ],
  "omitted_count": 381,
  "next_cursor": "topic:彩礼#offset=20"
}
```

> 验收标准：任何工具返回都 ≤ 8k~15k chars；输入 token 从 43 万掉到几千~几万以内。

---

### C. 把“整份 index / 整份 available_topics”从工具输出里彻底移除（只返回“被选中的少量 topic”）

你现在的索引有 1771 topics。这类东西：

- **可以存在服务端内存/文件**
- 但**绝对不应该作为 tool result 回传给主模型**

正确方式是：

- `expand_query` 只返回：

  - `selected_topics`: <= 20
  - `keyword_seeds`: <= 30
  - `dimension_plan`: 结构化维度计划（下一节讲）

- 不要返回 `available_topics` 全量

> 验收标准：任何 tool result 的 key 里不再出现 `available_topics` 或类似“大数组”。

---

### D. “search_by_keywords”不要再做全量扫描 + 大返回：改成两段式

你文档写得很清楚：`search_by_keywords` 会加载全部 chatlog 并逐条扫描（成本最高）。
这里要分两件事优化：

1. **算力/耗时优化（扫描少做）**
2. **token 优化（扫描可以做，但返回要小）**

强烈建议实现“两段式”：

- 第一段：关键词/语义召回只返回 `line_numbers`（最多 50）
- 第二段：`load_messages` 只加载 topN（最多 20 条），并对每条只返回 snippet

**禁止** search_by_keywords 直接返回 message 全文列表（尤其不能带上下文窗口）。

---

### E. 工具调用次数硬控：给 Agent 一个“工具预算管理器”

你文件里已经指出“多轮原子调用造成 token 暴涨”。
最有效的工程手段就是：**预算 + 触发熔断**。

建议预算（可按你场景调）：

- `max_tool_calls_per_question = 3`

  - 1 次 parse_task（可选）
  - 1 次 retrieve_evidence（必须）
  - 1 次 analyze_evidence（必须）

- `max_loaded_messages_total = 40`
- `max_tool_result_chars = 12_000`
- 一旦超预算：直接进入“基于现有证据输出 + 标注缺口”，不允许继续搜

> 验收标准：同一个问题不会出现 `search_by_keywords → expand_query → search_by_keywords → ...` 这种链条。

---

### F. “工具结果句柄化”：返回 evidence_id，不要把原始证据反复塞回上下文

这是解决 token 的结构性方法。

让 `retrieve_evidence`：

- 服务端保存完整证据包（比如放内存/redis/本地缓存）
- 工具返回给模型的只有：

  - `evidence_id`
  - 每条证据的 `line_number + 1句snippet + topics + score`

然后 `analyze_evidence(evidence_id, ...)` 在服务端读取完整证据再做分析（或只取必要片段），**不要把完整原文在两轮之间反复回传给模型**。

> 验收标准：第二轮分析时不需要再把第一轮检索得到的大文本重新塞回 prompt。

---

## 2) 让 Agent 按“不同层次维度”挖证据，而不是低级关键词

你期待的效果很明确：
对“冯天奇在女性/爱情上的看法”，要从不同维度取证：

- 社会阶级/工资/消费观
- 恋爱史/择偶标准/分手原因
- 对女权、彩礼、婚姻、AA 等议题的态度
- 语言习惯、对女性的称呼/玩笑/评价方式（潜台词）
- 行为层面：对女性同事/朋友的互动模式

而不是只搜“相亲/女性/女人”。我同意你的判断：那种搜法只会召回低质量噪声。

### A. 把“任务解析”输出改成一个 **维度化证据计划（Evidence Plan）**

你已经有 `mcp__chatlog__parse_task`。关键是让它输出这种结构，而不是一串关键词：

```json
{
  "target_person": "冯天奇",
  "question_type": "persona_on_topic",
  "dimensions": [
    {
      "name": "经济与阶级线索",
      "intent": "从收入/工作压力/消费/房车等推断婚恋现实约束与择偶偏好",
      "topic_seeds": ["工资", "年终", "房", "车", "消费", "工作强度", "中产"],
      "semantic_queries": [
        "工资多少",
        "月薪 年终 奖金 绩效",
        "买房 首付 房贷",
        "彩礼 经济压力"
      ],
      "min_evidence": 4
    },
    {
      "name": "恋爱史与择偶偏好",
      "intent": "用明确的恋爱事件、分手原因、择偶标准做一手证据",
      "topic_seeds": ["前任", "分手", "暧昧", "表白", "追", "对象", "结婚"],
      "semantic_queries": [
        "我前任",
        "分手原因",
        "喜欢什么样的女生",
        "谈恋爱最看重什么"
      ],
      "min_evidence": 4
    },
    {
      "name": "性别议题态度",
      "intent": "看他如何评价女权/彩礼/AA/婚姻分工等议题（价值观层）",
      "topic_seeds": ["女权", "彩礼", "AA", "田园", "男女对立", "婚姻", "生娃"],
      "semantic_queries": [
        "女权怎么看",
        "彩礼合理吗",
        "AA制",
        "结婚以后谁负责什么"
      ],
      "min_evidence": 6
    },
    {
      "name": "语言与潜台词",
      "intent": "从称呼、笑话、评价方式识别尊重程度/物化倾向/刻板印象",
      "topic_seeds": ["绿茶", "捞女", "身材", "颜值", "独立", "作"],
      "semantic_queries": ["评价女生 绿茶 捞", "身材 颜值", "独立 vs 作"],
      "min_evidence": 6
    }
  ]
}
```

这一步的关键点：

- **维度是“推断路径”**，不是“关键词列表”
- 每个维度既有 topic seeds（利用你的倒排索引），也有 semantic queries（利用向量召回）
- 每个维度明确 min_evidence，防止只抓到 1-2 条就开始编

---

### B. 检索层：改成“按维度召回 + 重排 + 反证召回”

你已经有组合型工具 `retrieve_evidence`（内部 expand → topics/keywords → semantic → load → person filter）。
你现在的问题是主 agent 走了原子链条，导致又乱又贵。

建议你把 `retrieve_evidence` 改造成真正的“维度检索器”：

**每个维度执行：**

1. `search_by_topics(topic_seeds)` 召回候选 line_numbers（快、准）
2. `search_semantic(semantic_queries)` 补召回（抓潜台词）
3. 合并去重候选
4. **只 load topN（比如每维度最多 10 条）**
5. 按下面规则重排：

   - `information_density` 高优先（你元数据里已有）
   - 明确提到目标人（或目标人发言）优先
   - 话题匹配数更多的优先
   - 极端情绪（强 positive/negative）优先（更可能表达观点）

6. **做一次“反证搜索”**：

   - 如果维度里找到了“反女权/反彩礼”的观点，再搜是否存在“认可女性独立/反刻板印象”的对话
   - 防止只取单边证据

> 这一步能让你期望的“多层次、多维度证据”自然出现，而不是靠“相亲/女人”这种粗词撞运气。

---

### C. 分析层输出：用“证据矩阵”而不是泛泛结论

你应该让 `analyze_evidence` 输出固定结构（非常利于质量控制）：

- 维度结论（1-2 句）
- 证据列表（最多 3 条关键证据：line_number + snippet）
- 推断链（为什么这些证据支持结论）
- 反证/缺口（有没有相反证据？缺什么数据？）
- 置信度（高/中/低，基于证据量与一致性）

这样 Agent 才会“挖掘潜在对话并分析”，而不是“编个印象”。

---

## 3) “工具太多、太乱、加载消息太多”怎么收敛？

你现在的工具分层其实是对的：高层组合型 + 原子分拆型。问题在于：

- 你把原子工具也暴露给主 agent
- 主 agent 没被强约束，所以会反复试探式调用
- 结果：重复检索、重复加载、重复把大包塞回上下文

### A. 工具对外收敛：主 agent 只允许 2~3 个“产品级工具”

建议你对主 agent **只暴露**：

1. `parse_task`（可选）
2. `retrieve_evidence`（必须）
3. `analyze_evidence`（必须）

原子工具全部隐藏/仅 debug agent 可用。

> 这一个改动，通常就能把“工具太乱”直接解决 80%。

---

### B. 让 retrieve_evidence 变成唯一入口：内部自己决定 topics vs semantic vs keywords

主 agent 不应该关心“先 topics 还是先 keywords”。

它只要说：“我要分析冯天奇在女性/爱情方面的看法，按这些维度给证据”。

然后 retrieve_evidence 内部做最优策略：

- 优先 topics（O(1)）
- 其次 semantic（有 embedding 缓存则更强）
- keywords 全量扫描作为最后 fallback（并且只返回 line_numbers）

---

### C. “加载消息太多”——把 load_messages 改成“按需、少量、可控”

你现在 load_messages 会带上下文窗口，且 include_metadata=true 会放大返回量。建议：

- 默认：`context_before=1, context_after=1`
- 默认：`include_metadata=false`
- 增加参数：`snippet_chars=120`（每条 content 截断）
- 增加参数：`fields=["timestamp","speaker","content","topics"]`
- 增加参数：`max_messages=20`
- 对重复 line_number 做去重

并且：retrieve_evidence 内部决定什么时候需要上下文窗口（例如：当 message 很短、像一句话，需要上下文才能理解时，才扩大窗口）。

---

## 4) 给你一套“最终形态”的可执行落地方案（建议你直接照这个改）

### 方案目标（你可以拿去当验收标准）

- 同一问题（例如你这个冯天奇问题）：

  - 工具调用次数 ≤ 3
  - input_tokens 控制在 **5k~30k**（看你加载证据多少）
  - 输出包含 ≥ 3 个维度，每个维度 ≥ 3 条证据（snippet + line_number）
  - 有反证/缺口说明，避免“瞎猜”

---

### Step 1：工具返回“瘦身协议”（必须做）

对所有工具统一返回协议：

- 列表字段一律 topK
- 长文本一律 snippet
- 永远返回 `omitted_count/next_cursor`
- 禁止返回全量 topics/index/chatlog

---

### Step 2：工具收敛（主 agent 只见 3 个工具）

- 隐藏：expand*query / search_by*\* / load_messages / filter_by_person / format_messages
- 只保留：parse_task / retrieve_evidence / analyze_evidence

---

### Step 3：retrieve_evidence 升级为“维度检索器”

输入：question + target_person
输出：evidence_id + per-dimension top evidence snippets（少量）

内部：topics 优先 + semantic 补充 + keywords 兜底

---

### Step 4：analyze_evidence 固定输出“证据矩阵”

按维度输出：结论 + 证据 + 推断链 + 反证/缺口 + 置信度

---

### Step 5：加预算熔断，彻底杜绝“反复试探式调用”

- max tool calls
- max loaded messages
- max tool result chars

超过就停止检索，进入分析。

---

## 你现在最可能的“真实根因”我帮你直接点名（方便你排查）

结合你文档现象，最常见导致 40 万 input tokens 的具体 bug/设计问题是：

1. **工具 stdout/日志被当成工具返回传回模型**（例如打印了 available_topics 全量）
2. **search_by_keywords 实际返回了全量 messages**（而不是 line_numbers）
3. **expand_query 工具把 index 的 available_topics 全量返回**（为了让 LLM 选 topic）
4. **CHATLOG_MAX_RETURN_CHARS 只对 UI 生效，不对 tool result 生效**

你按我上面“体积监控”一跑，基本 1 次就能确定是哪一个。

---

如果你愿意把你某一次 `search_by_keywords / expand_query / retrieve_evidence` 的**真实 tool result JSON（截取前 200 行也行）**贴出来，我还能进一步帮你精确到“应该删哪个字段/改哪个默认参数/哪个环节在重复返回”。但就算你不贴，现在这套方案也已经足够你把 token 和工具混乱问题彻底压下去。

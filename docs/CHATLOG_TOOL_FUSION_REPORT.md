# Chatlog Tool Fusion Report (PM Perspective)
## Objective
Focus the product on a general "task reasoning framework" for chatlogs while reducing tool sprawl inside the Chatlog MCP. This report is based on the current codebase (`src/chatlog/mcp_server.py`, `tui_agent.py`) and the analysis in `docs/AGENT_VS_WORKFLOW_ANALYSIS.md`.

---

## Executive Summary
- The current Chatlog MCP exposes 10 atomic tools. This is compliant with MCP principles but creates a fragmented surface for task-style questions.
- The real user goal is not "search messages" but "collect multi-layer evidence and reasoning scaffolds." The tool set should be designed around that.
- Recommendation: keep atomic tools internally, but fuse them into 3 task-level tools exposed to the Agent to reduce orchestration friction and provide evidence-centric outputs.

---

## Current State (Chatlog Only)
**Exposed tools in `src/chatlog/mcp_server.py`:**
- get_chatlog_stats
- search_person
- list_topics
- search_by_topics
- search_by_keywords
- load_messages
- expand_query
- search_semantic
- filter_by_person
- format_messages

**Pain points for task reasoning:**
- The Agent must orchestrate 5-7 steps to answer a single high-level question.  
- "Evidence" is scattered across multiple calls and formats.
- No native tool provides patterns or signal summaries; it only returns raw messages.

---

## User Goal Shift: Search -> Task Reasoning
Example questions: "Should I accept this request?", "What changed over time?", "Why did this happen?"

The user is asking for:
1) Evidence recall: relevant events and quotes.
2) Pattern analysis: frequency, trends, contradictions.
3) Reasoning scaffold: risks, missing information, follow-up questions.

The current tool set is optimized for (1) but not for (2) and (3).

---

## Proposed Fusion: Three Task-Level Tools
Expose only these three to the Agent; keep atomic tools for internal composition.

### 1) parse_task
**Goal:** convert a user question into structured task intent.
**Internal composition:** expand_query + heuristics.
**Output:**
```json
{
  "task_type": "decision",
  "target_person": "某人",
  "keywords": ["请求", "承诺", "风险"],
  "topics": ["关系", "承诺"],
  "sub_questions": [
    "相关历史事件与证据有哪些？",
    "正向/负向信号各是什么？",
    "关键信息缺口或不确定性是什么？"
  ],
  "llm_used": true
}
```

### 2) retrieve_evidence
**Goal:** fetch multi-layer evidence with traceable sources.
**Internal composition:** search_by_topics + search_by_keywords + search_semantic + load_messages + filter_by_person.
**Output:**
```json
{
  "evidence": [
    {
      "line": 12345,
      "time": "2024-03-21 09:13:00",
      "sender": "冯天奇",
      "content": "我这周能借你3000吗",
      "tags": ["借款请求", "金额"]
    }
  ],
  "coverage": {
    "topics_hit": ["借贷"],
    "keyword_hit": ["借", "还"],
    "semantic_hit": true
  },
  "limits": {
    "max_results": 80,
    "context_window": "±2"
  }
}
```

### 3) analyze_evidence
**Goal:** turn evidence into patterns + signals + neutral reasoning scaffold.
**Internal composition:** summarization + simple metrics.
**Output:**
```json
{
  "signals": {
    "positive": ["出现过明确承诺并按时完成"],
    "negative": ["出现过多次推迟/未兑现"],
    "gaps": ["缺少关键时间点或理由说明"]
  },
  "framework": [
    "是否存在明确承诺与结果",
    "风险是否可承受",
    "是否需要补充信息"
  ],
  "disclaimer": "建议仅基于聊天记录，不构成决策替代"
}
```

---

## Why This Fusion Fits the Project
- Keeps MCP atomicity in implementation, but exposes task-first surface.
- Directly supports general task reasoning scenarios in `docs/AGENT_VS_WORKFLOW_ANALYSIS.md`.
- Reduces tool count from 10 to 3 for Chatlog without losing capability.

---

## Engineering Notes (Where Changes Live)
- `src/chatlog/mcp_server.py`: add 3 fused tools, compose existing implementations.
- `docs/CHATLOG_MCP.md`: update tool list and flows.
- `docs/TOOL_DEFINITION_SPEC.md`: add task-level tools as recommended interface.
- `tui_agent.py`: optionally restrict allowed tools to fused tools for default mode.

---

## Risks & Mitigations
- **Risk:** The Agent loses control over fine-grained behavior.
  - **Mitigation:** keep atomic tools accessible in "expert mode".
- **Risk:** More LLM-internal steps reduce transparency.
  - **Mitigation:** return `llm_used`, `model`, and source line numbers.
- **Risk:** Higher compute cost for fused tool chain.
  - **Mitigation:** add `mode="fast"` vs `mode="deep"` switches.

---

## Recommendation
Implement the fused tool layer as the default Chatlog interface for task reasoning, while retaining atomic tools for power users or debugging. This aligns with the product goal of "advanced chatlog analysis" and removes the perception of tool sprawl without sacrificing capability.

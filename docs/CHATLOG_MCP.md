# Chatlog MCP Assessment and Decomposition Proposal

## Summary
The chatlog MCP server now exposes atomic tools only (no `query_chatlog`).
This keeps agent autonomy and makes each decision explicit.

Current tools:
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

## MCP Compliance Notes
- MCP server is compliant (SDK tools + content responses).
- Tools are atomic and composable.
- LLM usage is optional and surfaced via tool outputs.

## Suggested Agent Flows
Simple direct lookup (no cleaning):
- expand_query -> search_by_topics -> load_messages -> format_messages

Ambiguous question (needs recall):
- expand_query -> search_by_topics + search_semantic -> load_messages ->
  filter_by_person -> format_messages

Person-focused search:
- expand_query (with target_person) -> search_by_topics -> load_messages ->
  filter_by_person -> format_messages

## Risks and Considerations
- More tools means more agent decisions; defaults should be documented.
- Some steps depend on local caches (embeddings, metadata index).
- Avoid large payloads; return line numbers and compact windows by default.
- If LLM usage is optional, expose a flag in tool outputs for provenance.

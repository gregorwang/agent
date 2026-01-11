import os
import sys
import json
import asyncio

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.chatlog import mcp_server


def _parse_payload(result: dict) -> dict:
    text = result.get("content", [{}])[0].get("text", "{}")
    return json.loads(text)


async def run() -> int:
    result = await mcp_server._list_topics_impl({"limit": 5})
    payload = _parse_payload(result)
    if not payload.get("ok"):
        print("FAIL list_topics")
        return 1

    topics = payload["data"].get("topics", [])
    if not topics:
        print("FAIL list_topics empty")
        return 1

    result = await mcp_server._search_by_topics_impl({"topics": [topics[0]], "max_results": 10})
    payload = _parse_payload(result)
    if not payload.get("ok"):
        print("FAIL search_by_topics")
        return 1

    lines = payload["data"].get("line_numbers", [])
    if not lines:
        print("FAIL search_by_topics empty")
        return 1

    result = await mcp_server._search_by_keywords_impl({"keywords": ["借"], "max_results": 10})
    payload = _parse_payload(result)
    if not payload.get("ok"):
        print("FAIL search_by_keywords")
        return 1

    result = await mcp_server._load_messages_impl({
        "line_numbers": lines[:3],
        "context_before": 1,
        "context_after": 1,
        "include_metadata": False
    })
    payload = _parse_payload(result)
    if not payload.get("ok") or not payload["data"].get("messages"):
        print("FAIL load_messages")
        return 1

    messages = payload["data"]["messages"]
    result = await mcp_server._format_messages_impl({
        "messages": messages,
        "format": "compact",
        "max_chars": 2000
    })
    payload = _parse_payload(result)
    if not payload.get("ok") or not payload["data"].get("text"):
        print("FAIL format_messages")
        return 1

    result = await mcp_server._expand_query_impl({
        "question": "冯天奇 借钱 情况怎么样",
        "target_person": "冯天奇",
        "use_llm": False
    })
    payload = _parse_payload(result)
    if not payload.get("ok") or not payload["data"].get("keywords"):
        print("FAIL expand_query")
        return 1

    result = await mcp_server._search_semantic_impl({
        "query": "借钱",
        "top_k": 5
    })
    payload = _parse_payload(result)
    if not payload.get("ok") or "available" not in payload["data"]:
        print("FAIL search_semantic")
        return 1

    result = await mcp_server._filter_by_person_impl({
        "messages": messages,
        "target_person": "冯天奇",
        "use_llm": False
    })
    payload = _parse_payload(result)
    if not payload.get("ok"):
        print("FAIL filter_by_person")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))

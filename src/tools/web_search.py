import json
import os
import urllib.error
import urllib.parse
import urllib.response
import urllib.request
from typing import Any

from claude_agent_sdk import tool, create_sdk_mcp_server

DEFAULT_TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_USER_AGENT = "benedictjun-agent/1.0"


def _read_response(
    response: urllib.response.addinfourl,
    max_bytes: int,
) -> tuple[str, str]:
    content_type = response.headers.get("Content-Type", "")
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip()

    raw = response.read(max_bytes)
    text = raw.decode(charset, errors="replace")
    return content_type, text


def _http_request_json(
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        _, text = _read_response(resp, max_bytes=2_000_000)
    return json.loads(text)


def _validate_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed.")
    return url


@tool(
    "web_search",
    "Search the web with Tavily",
    {
        "query": str,
        "max_results": int,
        "search_depth": str,
    },
)
async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Missing TAVILY_API_KEY environment variable.",
                }
            ]
        }

    query = (args.get("query") or "").strip()
    if not query:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Query is required for web_search.",
                }
            ]
        }

    max_results = int(args.get("max_results") or 5)
    search_depth = args.get("search_depth") or "basic"

    try:
        response = _http_request_json(
            DEFAULT_TAVILY_ENDPOINT,
            {
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": search_depth,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=20,
        )
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Tavily search failed: {exc}",
                }
            ]
        }

    results = response.get("results") or []
    if not results:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "No results returned.",
                }
            ]
        }

    lines: list[str] = []
    for item in results:
        title = item.get("title") or "(untitled)"
        url = item.get("url") or ""
        snippet = item.get("content") or item.get("snippet") or ""
        lines.append(f"- {title}\n  {url}\n  {snippet}".strip())

    return {
        "content": [
            {
                "type": "text",
                "text": "\n\n".join(lines),
            }
        ]
    }


@tool(
    "web_fetch",
    "Fetch a web page over HTTP",
    {
        "url": str,
        "max_bytes": int,
    },
)
async def web_fetch(args: dict[str, Any]) -> dict[str, Any]:
    url = (args.get("url") or "").strip()
    if not url:
        return {
            "content": [
                {"type": "text", "text": "url is required for web_fetch."}
            ]
        }

    try:
        _validate_http_url(url)
    except ValueError as exc:
        return {"content": [{"type": "text", "text": str(exc)}]}

    max_bytes = int(args.get("max_bytes") or 200_000)
    max_bytes = min(max_bytes, 2_000_000)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            content_type, text = _read_response(resp, max_bytes=max_bytes)
    except urllib.error.URLError as exc:
        return {"content": [{"type": "text", "text": f"Fetch failed: {exc}"}]}

    snippet = text[:4000]
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Status: {status}\n"
                    f"Content-Type: {content_type}\n\n"
                    f"{snippet}"
                ),
            }
        ]
    }


def create_web_mcp_server():
    return create_sdk_mcp_server(
        name="web",
        version="1.0.0",
        tools=[web_search, web_fetch],
    )

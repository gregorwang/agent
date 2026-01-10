"""
Basic Session Agent - Demonstrates proper session management with Claude Agent SDK

This is a simplified example showing how to:
1. Use the resume parameter for session continuity
2. Handle session IDs from init messages
3. Continue conversations across multiple queries
"""

import asyncio
import os

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from dotenv import load_dotenv

# Import our session management module
from src.session.persistence import SessionManager
from src.tools.web_search import create_web_mcp_server


async def main() -> None:
    load_dotenv()

    # Map custom env names to SDK defaults if needed
    if not os.getenv("ANTHROPIC_API_KEY") and os.getenv("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

    # Configuration
    model = os.getenv("AGENT_MODEL") or os.getenv("OPENAI_MODEL") or "claude-sonnet-4-5"
    max_turns = int(os.getenv("MAX_TURNS", "4"))
    
    # P0 Fix: Include Task tool for subagent support
    default_tools = (
        "Read,Edit,Write,Glob,Grep,Bash,Task,"
        "mcp__web__web_search,mcp__web__web_fetch"
    )
    allowed_tools = os.getenv("ALLOWED_TOOLS", default_tools).split(",")
    allowed_tools = [tool.strip() for tool in allowed_tools if tool.strip()]
    
    continue_conversation = os.getenv("CONTINUE_CONVERSATION", "1") == "1"

    # P0 Fix: Use proper SessionManager instead of raw file access
    session_manager = SessionManager()
    resume_session_id = session_manager.get_current_session_id()

    # First query
    async for message in query(
        prompt="Hello! Start a minimal session.",
        options=ClaudeAgentOptions(
            model=model,
            max_turns=max_turns,
            allowed_tools=allowed_tools,
            mcp_servers={"web": create_web_mcp_server()},
            resume=resume_session_id,  # P0 Fix: Use resume parameter
            continue_conversation=continue_conversation if not resume_session_id else False,
        ),
    ):
        # P0 Fix: Capture session ID from init message
        if hasattr(message, "subtype") and message.subtype == "init":
            session_id = message.data.get("session_id") if hasattr(message, 'data') else None
            if session_id:
                session_manager.set_current_session_id(session_id)
                print(f"Session started: {session_id}")
            continue

        if isinstance(message, ResultMessage):
            print(message.result)
            # Update session with new session ID if provided
            if message.session_id:
                session_manager.set_current_session_id(message.session_id)

    # Second query - continue the same session
    session_id = session_manager.get_current_session_id()
    if session_id:
        print(f"\nContinuing session: {session_id}")
        async for message in query(
            prompt="Continue the same session.",
            options=ClaudeAgentOptions(
                resume=session_id,  # P0 Fix: Use resume parameter
                max_turns=max_turns,
                allowed_tools=allowed_tools,
                mcp_servers={"web": create_web_mcp_server()},
            ),
        ):
            if isinstance(message, ResultMessage):
                print(message.result)


if __name__ == "__main__":
    asyncio.run(main())

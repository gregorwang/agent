import os
import sys

os.environ["CHATLOG_MAX_RETURN_CHARS"] = "500"
os.environ["POE_API_KEY"] = ""
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.chatlog.mcp_server import query_chatlog_sync  # noqa: E402


def main() -> int:
    question = "借钱"
    result = query_chatlog_sync(question=question, max_results=1000)
    length = len(result or "")

    print(f"query length: {length}")
    if length > 520:
        print("FAIL: output exceeds limit")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

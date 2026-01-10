import asyncio
import os
import sys

os.environ["POE_API_KEY"] = ""
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.chatlog.cleaner import ChatlogCleaner  # noqa: E402
from src.chatlog.metadata_index_loader import get_index_loader  # noqa: E402


async def _run() -> int:
    loader = get_index_loader()
    loader.load_index()
    available = loader.available_topics

    cleaner = ChatlogCleaner()
    question = "冯天奇向我借钱我该借钱吗"
    _, metadata = await cleaner.expand_query(
        question, target_person="冯天奇", available_topics=available
    )
    topics = metadata.get("topics", [])

    required = [t for t in ["借贷", "金钱", "工资", "职业", "消费习惯", "评价"] if t in available]
    missing = [t for t in required if t not in topics]

    print(f"topics: {topics}")
    if missing:
        print(f"FAIL missing: {missing}")
        return 1

    print("PASS")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())

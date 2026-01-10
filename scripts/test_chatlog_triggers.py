import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.chatlog.trigger import should_use_chatlog_chain


def main() -> int:
    positives = [
        "请查找聊天记录：冯天奇的工资有多少？",
        "查询聊天记录里他说过存款吗？",
        "聊天记录中他在哪个地方上班呢？",
        "我需要查找聊天记录",
        "结合聊天记录判断我该不该借钱",
        "根据聊天记录给出建议",
    ]
    for text in positives:
        if not should_use_chatlog_chain(text):
            print(f"FAIL should trigger: {text}")
            return 1

    negatives = [
        "你好",
        "今天天气怎么样",
        "冯天奇的工资有多少？",
        "他在哪个地方上班呢？",
    ]
    for text in negatives:
        if should_use_chatlog_chain(text):
            print(f"FAIL should not trigger: {text}")
            return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

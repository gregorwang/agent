import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.chatlog.semantic_index import get_semantic_index


def main() -> None:
    chatlog_path = os.getenv("CHATLOG_PATH", "cleaned_chatlog.jsonl")
    index = get_semantic_index()
    count, npy_path, index_path = index.build_from_chatlog(chatlog_path)
    print(f"Built {count} embeddings")
    print(f"Saved: {npy_path}")
    print(f"Index: {index_path}")


if __name__ == "__main__":
    main()

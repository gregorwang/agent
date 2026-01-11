"""Semantic index for chatlog retrieval (local npy + json)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from urllib import request

import numpy as np


@dataclass
class SemanticIndexConfig:
    model: str = "embedding-3"
    api_key_env: str = "ZHIPU_API_KEY"
    api_url_env: str = "ZHIPU_EMBEDDINGS_URL"
    api_url_default: str = "https://open.bigmodel.cn/api/paas/v4/embeddings"
    embeddings_path: str = "cleaned_chatlog_embeddings.npy"
    index_path: str = "cleaned_chatlog_embeddings_index.json"
    batch_size: int = 32


class SemanticIndex:
    """Loads and queries semantic embeddings for chatlog lines."""

    def __init__(self, config: Optional[SemanticIndexConfig] = None) -> None:
        self.config = config or SemanticIndexConfig()
        self._embeddings: Optional[np.ndarray] = None
        self._line_numbers: Optional[List[int]] = None
        self._loaded = False

    def _api_key(self) -> str:
        return os.getenv(self.config.api_key_env, "").strip()

    def _api_url(self) -> str:
        return os.getenv(self.config.api_url_env, self.config.api_url_default)

    def is_available(self) -> bool:
        return os.path.exists(self.config.embeddings_path) and os.path.exists(
            self.config.index_path
        )

    def load(self) -> bool:
        if self._loaded:
            return True
        if not self.is_available():
            return False
        try:
            self._embeddings = np.load(self.config.embeddings_path)
            with open(self.config.index_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._line_numbers = payload.get("line_numbers", [])
            self._loaded = True
            return True
        except Exception:
            return False

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        api_key = self._api_key()
        if not api_key:
            raise RuntimeError("ZHIPU_API_KEY not configured")
        payload = json.dumps({
            "model": self.config.model,
            "input": texts,
        }).encode("utf-8")
        req = request.Request(
            self._api_url(),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                with request.urlopen(req, timeout=60) as resp:
                    raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                items = data.get("data", [])
                return [item.get("embedding", []) for item in items]
            except Exception as exc:
                last_err = exc
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Embedding request failed: {last_err}")

    def build_from_chatlog(self, chatlog_path: str) -> Tuple[int, str, str]:
        """Build embeddings from chatlog jsonl."""
        api_key = self._api_key()
        if not api_key:
            raise RuntimeError("ZHIPU_API_KEY not configured")

        line_numbers: List[int] = []
        texts: List[str] = []

        with open(chatlog_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = record.get("content", "")
                if not content:
                    continue
                line_numbers.append(line_num)
                texts.append(content)

        embeddings: List[List[float]] = []
        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i:i + self.config.batch_size]
            embeddings.extend(self._embed_texts(batch))
            time.sleep(0.2)  # gentle pacing to avoid rate spikes

        matrix = np.asarray(embeddings, dtype=np.float32)
        np.save(self.config.embeddings_path, matrix)
        with open(self.config.index_path, "w", encoding="utf-8") as f:
            json.dump({
                "line_numbers": line_numbers,
                "model": self.config.model,
                "created_at": int(time.time()),
            }, f, ensure_ascii=False, indent=2)
        self._embeddings = matrix
        self._line_numbers = line_numbers
        self._loaded = True
        return len(line_numbers), self.config.embeddings_path, self.config.index_path

    def search(self, query: str, top_k: int = 50) -> List[Tuple[int, float]]:
        if not self.load():
            return []
        if self._embeddings is None or self._line_numbers is None:
            return []
        query_vec = self._embed_texts([query])[0]
        q = np.asarray(query_vec, dtype=np.float32)
        if q.size == 0:
            return []
        q = q / (np.linalg.norm(q) + 1e-12)
        mat = self._embeddings
        denom = np.linalg.norm(mat, axis=1) + 1e-12
        sims = (mat @ q) / denom
        if sims.size == 0:
            return []
        top_k = min(top_k, sims.size)
        idx = np.argpartition(-sims, top_k - 1)[:top_k]
        ranked = sorted(((int(i), float(sims[i])) for i in idx), key=lambda x: x[1], reverse=True)
        return [(self._line_numbers[i], score) for i, score in ranked]


_semantic_index: Optional[SemanticIndex] = None


def get_semantic_index() -> SemanticIndex:
    global _semantic_index
    if _semantic_index is None:
        config = SemanticIndexConfig(
            model=os.getenv("CHATLOG_EMBEDDING_MODEL", "embedding-3"),
            embeddings_path=os.getenv(
                "CHATLOG_EMBEDDINGS_NPY",
                "cleaned_chatlog_embeddings.npy"
            ),
            index_path=os.getenv(
                "CHATLOG_EMBEDDINGS_INDEX",
                "cleaned_chatlog_embeddings_index.json"
            ),
            batch_size=int(os.getenv("CHATLOG_EMBEDDINGS_BATCH", "32")),
        )
        _semantic_index = SemanticIndex(config)
    return _semantic_index

"""
Thin wrapper around ChromaDB used as the agent's semantic memory: embeddings
of every published post, queried to (a) avoid re-covering a near-duplicate
topic and (b) give the writer a "here's what I've already said" context.

Chroma's DEFAULT embedding function downloads a sentence-transformer model
from the internet on first use — which would silently break the "runs fully
offline, no keys, no network" guarantee this system promises for demo/CI
environments. So we supply our own dependency-free hashing embedding
function instead: deterministic, offline, good enough for coarse
near-duplicate detection (which is all it's used for here).
"""
import hashlib
import re
from typing import List

import chromadb

from app.config import get_settings
from app.logging_config import logger

settings = get_settings()

_VECTOR_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class HashingEmbeddingFunction:
    """A minimal, deterministic bag-of-words hashing embedding function.
    Not semantically rich like a real sentence embedding, but requires zero
    network access or model downloads, which matters more here than
    embedding quality — this is used only for coarse duplicate detection.
    """

    def __call__(self, input: List[str]) -> List[List[float]]:
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> List[float]:
        vec = [0.0] * _VECTOR_DIM
        tokens = _TOKEN_RE.findall(text.lower())
        for tok in tokens:
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % _VECTOR_DIM
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def name(self) -> str:
        return "hashing-bow-256"


class VectorMemory:
    def __init__(self):
        self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        try:
            self._collection = self._client.get_or_create_collection(
                name="published_posts", embedding_function=HashingEmbeddingFunction()
            )
            self._available = True
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"ChromaDB unavailable, semantic memory disabled: {exc}")
            self._collection = None
            self._available = False

    def add_post(self, post_id: str, title: str, text: str, topic: str) -> None:
        if not self._available:
            return
        try:
            self._collection.upsert(
                ids=[post_id],
                documents=[f"{title}\n{text}"],
                metadatas=[{"topic": topic}],
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Vector memory add_post failed (non-fatal): {exc}")

    def most_similar_topic_score(self, topic: str, query_text: str) -> float:
        """Returns the highest similarity (0..1, higher = more similar) between
        query_text and any previously published post. Returns 0.0 if memory is
        empty or unavailable (fails open: never blocks the pipeline).
        """
        if not self._available:
            return 0.0
        try:
            count = self._collection.count()
            if count == 0:
                return 0.0
            results = self._collection.query(query_texts=[query_text], n_results=min(3, count))
            distances = results.get("distances", [[]])[0]
            if not distances:
                return 0.0
            # Vectors are L2-normalized by our hashing embedder, so squared L2
            # distance maps cleanly to cosine similarity: dist = 2 - 2*cos.
            best_distance = min(distances)
            similarity = max(0.0, 1.0 - best_distance / 2.0)
            return similarity
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Vector memory similarity query failed (non-fatal): {exc}")
            return 0.0

    def recent_context(self, topic: str, n: int = 3) -> List[str]:
        if not self._available:
            return []
        try:
            count = self._collection.count()
            if count == 0:
                return []
            results = self._collection.query(query_texts=[topic], n_results=min(n, count))
            return results.get("documents", [[]])[0]
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Vector memory context query failed (non-fatal): {exc}")
            return []


_vector_memory: VectorMemory | None = None


def get_vector_memory() -> VectorMemory:
    global _vector_memory
    if _vector_memory is None:
        _vector_memory = VectorMemory()
    return _vector_memory

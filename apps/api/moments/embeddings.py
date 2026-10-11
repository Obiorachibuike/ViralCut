"""Text embeddings for semantic search and duplicate-moment detection.

Default backend is a deterministic hashing vectoriser over word + character
n-grams. It has no model download and no network dependency, which keeps the
duplicate detector available in every deployment.

If `sentence-transformers` is installed and `VIRALCUT_EMBEDDING_MODEL` is set,
that backend is used instead and the vectors are compatible with the pgvector
column on `TranscriptSegment.embedding`.

Either way the vectors are L2-normalised, so cosine similarity is a dot product.
"""

from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger("viralcut.embeddings")

HASH_DIM = 1536  # matches vector(1536) in the Prisma schema
_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    """a an and are as at be but by for from had has have he her his i if in is it its
    me my of on or our she so that the their them then there these they this to was we
    were what when which who will with you your not just like really about into out
    up down over under again more most other some such no nor only own same than too
    very can because do does did doing would should could might must am been being""".split()
)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS and len(t) > 1]


def _char_ngrams(text: str, n: int = 4) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").lower().strip())
    return [cleaned[i : i + n] for i in range(max(0, len(cleaned) - n + 1))]


def _bucket(token: str, dim: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


def _sign(token: str) -> float:
    """Signed hashing cancels collisions instead of accumulating them."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=1, person=b"vcsign").digest()
    return 1.0 if digest[0] & 1 else -1.0


class Embedder(ABC):
    name = "abstract"
    dim = HASH_DIM

    @abstractmethod
    def embed(self, text: str) -> np.ndarray: ...

    def embed_many(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.embed(t) for t in texts])


class HashingEmbedder(Embedder):
    """Deterministic, dependency-free embedder (signed feature hashing)."""

    name = "hashing"

    def __init__(self, dim: int = HASH_DIM, *, char_weight: float = 0.45) -> None:
        self.dim = dim
        self.char_weight = char_weight

    def embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        tokens = _tokens(text)
        for token in tokens:
            vector[_bucket(token, self.dim)] += _sign(token)
        # Word bigrams carry phrase meaning ("biggest mistake" != "biggest", "mistake").
        for a, b in zip(tokens, tokens[1:]):
            bigram = f"{a}_{b}"
            vector[_bucket(bigram, self.dim)] += _sign(bigram) * 0.8
        for gram in _char_ngrams(text):
            vector[_bucket(gram, self.dim)] += _sign(gram) * self.char_weight
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector


class SentenceTransformerEmbedder(Embedder):
    """Optional semantic backend. Used only when the model is installed."""

    def __init__(self, model_name: str, *, device: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # optional dependency

        self._model = SentenceTransformer(model_name, device=device)
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.name = model_name

    def embed(self, text: str) -> np.ndarray:
        vector = np.asarray(self._model.encode(text or " ", normalize_embeddings=True), dtype=np.float32)
        return vector

    def embed_many(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.asarray(
            self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False),
            dtype=np.float32,
        )


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    return vectors @ vectors.T


_default: Embedder | None = None


def get_embedder() -> Embedder:
    global _default
    if _default is not None:
        return _default
    import os

    model_name = os.environ.get("VIRALCUT_EMBEDDING_MODEL", "")
    if model_name:
        try:
            _default = SentenceTransformerEmbedder(model_name)
            logger.info("using sentence-transformers embedder %s", model_name)
            return _default
        except Exception as err:  # pragma: no cover - optional dependency
            logger.warning(
                "sentence-transformers unavailable (%s); falling back to hashing embedder", err
            )
    _default = HashingEmbedder()
    return _default


def set_embedder(embedder: Embedder | None) -> None:
    """Test seam."""
    global _default
    _default = embedder

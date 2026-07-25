from __future__ import annotations

from hashlib import sha256
from typing import List, Protocol, Sequence


class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...
    @property
    def dimensions(self) -> int: ...
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]: ...
    def embed_query(self, text: str) -> List[float]: ...


class SentenceTransformerEmbeddingProvider:
    """Lazy, reusable local Sentence Transformers provider."""

    def __init__(
        self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str = "cpu", batch_size: int = 32, max_characters: int = 12000,
    ) -> None:
        self._model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.max_characters = max_characters
        self._model = None
        self._dimensions = 384 if model_name.endswith("all-MiniLM-L6-v2") else None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            self._load()
        return int(self._dimensions)

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed; install project requirements"
                ) from exc
            try:
                self._model = SentenceTransformer(self._model_name, device=self.device)
                self._dimensions = self._model.get_sentence_embedding_dimension()
            except Exception as exc:
                raise RuntimeError(
                    f"Unable to load local embedding model {self._model_name!r}: {exc}"
                ) from exc
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        cleaned = [str(text).strip()[:self.max_characters] for text in texts]
        if any(not text for text in cleaned):
            raise ValueError("Cannot embed empty text.")
        vectors = self._load().encode(
            cleaned, batch_size=self.batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class DeterministicEmbeddingProvider:
    """Small dependency-free provider intended for unit tests and local smoke tests."""

    def __init__(self, dimensions: int = 32) -> None:
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return "deterministic-test-v1"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        result = []
        for text in texts:
            if not text.strip():
                raise ValueError("Cannot embed empty text.")
            values = [0.0] * self._dimensions
            for token in text.casefold().split():
                digest = sha256(token.encode("utf-8")).digest()
                values[int.from_bytes(digest[:2], "big") % self._dimensions] += 1.0
            norm = sum(value * value for value in values) ** 0.5 or 1.0
            result.append([value / norm for value in values])
        return result

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

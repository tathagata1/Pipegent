from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


@dataclass
class VectorRecord:
    id: str
    vector: List[float]
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorSearchResult:
    id: str
    score: float
    payload: Dict[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    def initialise(self) -> None: ...
    def upsert(self, records: List[VectorRecord]) -> None: ...
    def search(
        self, vector: List[float], *, top_k: int, filters: Dict[str, Any],
    ) -> List[VectorSearchResult]: ...
    def delete(self, record_ids: List[str]) -> None: ...
    def healthcheck(self) -> bool: ...


class InMemoryVectorStore:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        self.records: Dict[str, VectorRecord] = {}

    def initialise(self) -> None:
        return None

    def upsert(self, records: List[VectorRecord]) -> None:
        for record in records:
            if len(record.vector) != self.dimensions:
                raise ValueError("Vector dimension mismatch.")
            self.records[record.id] = record

    def search(
        self, vector: List[float], *, top_k: int, filters: Dict[str, Any],
    ) -> List[VectorSearchResult]:
        def matches(payload):
            return all(
                payload.get(key) in value if isinstance(value, (list, tuple, set))
                else payload.get(key) == value for key, value in filters.items()
            )
        norm = math.sqrt(sum(value * value for value in vector)) or 1
        results = []
        for record in self.records.values():
            if not matches(record.payload):
                continue
            other_norm = math.sqrt(sum(value * value for value in record.vector)) or 1
            score = sum(a * b for a, b in zip(vector, record.vector)) / (norm * other_norm)
            results.append(VectorSearchResult(record.id, score, record.payload))
        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    def delete(self, record_ids: List[str]) -> None:
        for record_id in record_ids:
            self.records.pop(record_id, None)

    def healthcheck(self) -> bool:
        return True


class QdrantVectorStore:
    """Qdrant adapter; qdrant classes do not escape this module."""

    def __init__(
        self, url: str, collection_name: str, dimensions: int,
        api_key: str = "", client: Any = None, timeout: float = 3.0,
    ) -> None:
        self.url, self.collection_name = url, collection_name
        self.dimensions, self.api_key, self._client = dimensions, api_key, client
        self.timeout = timeout

    @property
    def client(self):
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError as exc:
                raise RuntimeError("qdrant-client is not installed") from exc
            self._client = QdrantClient(
                url=self.url, api_key=self.api_key or None, timeout=self.timeout
            )
        return self._client

    def initialise(self) -> None:
        from qdrant_client.models import Distance, VectorParams
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                self.collection_name,
                vectors_config=VectorParams(size=self.dimensions, distance=Distance.COSINE),
            )

    def upsert(self, records: List[VectorRecord]) -> None:
        from qdrant_client.models import PointStruct
        self.client.upsert(
            self.collection_name,
            [PointStruct(id=item.id, vector=item.vector, payload=item.payload)
             for item in records],
            wait=True,
        )

    def search(
        self, vector: List[float], *, top_k: int, filters: Dict[str, Any],
    ) -> List[VectorSearchResult]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
        conditions = []
        for key, value in filters.items():
            match = MatchAny(any=list(value)) if isinstance(value, (list, tuple, set)) \
                else MatchValue(value=value)
            conditions.append(FieldCondition(key=key, match=match))
        query_filter = Filter(must=conditions)
        if hasattr(self.client, "query_points"):
            points = self.client.query_points(
                self.collection_name, query=vector, query_filter=query_filter,
                limit=top_k, with_payload=True,
            ).points
        else:
            points = self.client.search(
                self.collection_name, query_vector=vector, query_filter=query_filter,
                limit=top_k, with_payload=True,
            )
        return [
            VectorSearchResult(str(item.id), float(item.score), dict(item.payload or {}))
            for item in points
        ]

    def delete(self, record_ids: List[str]) -> None:
        from qdrant_client.models import PointIdsList
        self.client.delete(
            self.collection_name, points_selector=PointIdsList(points=record_ids), wait=True
        )

    def healthcheck(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

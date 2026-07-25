from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class DocumentChunk:
    chunk_id: str
    position: int
    content: str
    heading: str
    checksum: str


class DocumentChunker:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120) -> None:
        if chunk_size <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("Invalid chunk configuration.")
        self.chunk_size, self.chunk_overlap = chunk_size, chunk_overlap

    def chunk(self, document_id: str, text: str) -> List[DocumentChunk]:
        text = text.replace("\r\n", "\n").strip()
        chunks, start, position, heading = [], 0, 0, ""
        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            if end < len(text):
                boundary = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
                if boundary > start + self.chunk_size // 2:
                    end = boundary + 1
            content = text[start:end].strip()
            headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", content)
            if headings:
                heading = headings[-1].strip()
            if content:
                checksum = hashlib.sha256(content.encode()).hexdigest()
                chunks.append(DocumentChunk(
                    f"{document_id}:{position}", position, content, heading, checksum
                ))
                position += 1
            if end >= len(text):
                break
            start = end - self.chunk_overlap
        return chunks


class DocumentIngestionService:
    ALLOWED_SUFFIXES = {".txt", ".md", ".markdown"}

    def __init__(self, memory_service, chunker: Optional[DocumentChunker] = None,
                 max_bytes: int = 5_000_000) -> None:
        self.memory_service, self.chunker = memory_service, chunker or DocumentChunker()
        self.max_bytes = max_bytes

    def ingest(
        self, path: Path, *, tenant_id: str, user_id: Optional[str],
        project_id: Optional[str], metadata: Optional[Dict] = None,
    ) -> Dict:
        if path.suffix.casefold() not in self.ALLOWED_SUFFIXES:
            raise ValueError("Only plain text and Markdown documents are supported.")
        size = path.stat().st_size
        if size > self.max_bytes:
            raise ValueError("Document exceeds configured size limit.")
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        document_id = hashlib.sha256(
            f"{tenant_id}:{path.name}:{checksum}".encode()
        ).hexdigest()[:32]
        text = raw.decode("utf-8")
        chunks = self.chunker.chunk(document_id, text)
        ids = self.memory_service.create_document_chunks(
            document_id=document_id, chunks=chunks, tenant_id=tenant_id,
            user_id=user_id, project_id=project_id, title=path.stem,
            filename=path.name, source_type=path.suffix.lstrip("."),
            checksum=checksum, metadata=metadata or {},
        )
        return {
            "document_id": document_id, "checksum": checksum,
            "chunks_created": len(ids), "memory_ids": ids,
        }

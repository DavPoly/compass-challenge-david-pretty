"""Shape of an indexed chunk of a document."""

from enum import StrEnum

from pydantic import BaseModel


class ChunkKind(StrEnum):
    """Kind of content held by a chunk."""

    TEXT = "text"
    TABLE = "table"


class Chunk(BaseModel):
    """A retrievable piece of a document with its metadata."""

    doc_id: str
    chunk_id: str
    chunk_kind: ChunkKind
    doc_type: str
    doc_date: str | None
    identifiers: list[str]
    lang: str
    text: str
    version: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None

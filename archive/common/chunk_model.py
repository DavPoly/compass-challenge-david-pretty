"""Shape of an indexed chunk of a document."""

from enum import StrEnum

from pydantic import BaseModel


class ChunkKind(StrEnum):
    """Kind of content held by a chunk."""

    TEXT = "text"
    TABLE = "table"


class DocType(StrEnum):
    """Document family; `Chunk.doc_type` holds one of these values."""

    INVOICE = "invoice"
    CONTRACT = "contract"
    MONTHLY_REPORT = "monthly_report"
    MINUTES = "minutes"
    EMAIL = "email"
    NEWSLETTER = "newsletter"
    MEMO = "memo"
    POLICY = "policy"
    DIRECTORY = "directory"
    TECHNICAL_NOTE = "technical_note"
    PROJECT_SHEET = "project_sheet"
    UNKNOWN = "unknown"


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
    series: str | None = None

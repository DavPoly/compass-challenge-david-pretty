"""Search over the indexed chunks: filters, identifiers, hybrid search.

`SearchService` owns the shared embedded index and exposes
`hybrid_search` and `list_by_filter`.
"""

import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import TracebackType

from qdrant_client import models

from archive.common.chunk_model import Chunk
from archive.ingest.index_builder_service import load_manifest
from archive.ingest.metadata_service import extract_metadata
from archive.ingest.pdf_parse_gateway import ParsedDoc
from archive.retrieval.qdrant_constants import (
    FIELD_DOC_DATE,
    FIELD_DOC_TYPE,
    FIELD_IDENTIFIERS,
)
from archive.retrieval.qdrant_gateway import QdrantGateway
from archive.retrieval.search_constants import QUERY_DOC_ID, UNRANKED_SCORE
from archive.retrieval.sparse_encoding_utils import sparse_vector


@dataclass(frozen=True)
class SearchFilters:
    """Payload filters; empty lists and None dates mean no constraint.

    Attributes:
        identifiers: Match chunks holding any of these codes.
        doc_types: Match chunks of any of these document types.
        date_from: Inclusive ISO lower bound on `doc_date`.
        date_to: Inclusive ISO upper bound on `doc_date`.
    """

    identifiers: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


@dataclass(frozen=True)
class SearchHit:
    """A retrieved chunk and its score (0.0 when unranked)."""

    chunk: Chunk
    score: float


def to_qdrant_filter(
    filters: SearchFilters | None,
) -> models.Filter | None:
    """Convert filters to a Qdrant filter, or None when unconstrained.

    Dates use `DatetimeRange` on the ISO `doc_date` payload, which the
    embedded (local) mode evaluates; chunks without a date never match
    a date bound.
    """
    if filters is None:
        return None
    must: list[models.Condition] = []
    if filters.identifiers:
        must.append(_match_any(FIELD_IDENTIFIERS, filters.identifiers))
    if filters.doc_types:
        must.append(_match_any(FIELD_DOC_TYPE, filters.doc_types))
    if filters.date_from or filters.date_to:
        must.append(
            models.FieldCondition(
                key=FIELD_DOC_DATE,
                range=models.DatetimeRange(
                    gte=filters.date_from, lte=filters.date_to
                ),
            )
        )
    return models.Filter(must=must) if must else None


def _match_any(key: str, values: list[str]) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchAny(any=values))


def find_identifiers(text: str) -> list[str]:
    """Canonical identifiers (codes, emails) mentioned in `text`."""
    doc = ParsedDoc(doc_id=QUERY_DOC_ID, pages=[text])
    return extract_metadata(doc).identifiers


class SearchService:
    """Thread-safe search over one shared embedded index."""

    def __init__(self, gateway: QdrantGateway, index_dir: Path) -> None:
        self._gateway = gateway
        self._read_lock = threading.Lock()
        self._doc_ids = frozenset(load_manifest(index_dir))

    @classmethod
    def open(cls, index_dir: Path) -> "SearchService":
        """Open the index under `index_dir` and its manifest.

        Raises:
            IndexOpenError: if the storage is missing or unusable.
            ManifestError: if the manifest is missing or invalid.
        """
        gateway = QdrantGateway.open_existing(index_dir)
        is_opened = False
        try:
            service = cls(gateway, index_dir)
            is_opened = True
            return service
        finally:
            if not is_opened:
                gateway.close()

    def known_doc_ids(self) -> frozenset[str]:
        """Ids of every indexed document, from the manifest."""
        return self._doc_ids

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        """Return the top `k` chunks for a query, best first.

        Sparse only for now. Identifiers found in the query are merged
        with `filters.identifiers` into a payload filter; when that
        filtered search is empty it is retried without the identifier
        constraint (other filters kept).
        """
        base = filters or SearchFilters()
        codes = sorted({*base.identifiers, *find_identifiers(query)})
        vector = sparse_vector(query)
        if not vector.indices:
            return []
        if codes:
            hits = self._query(vector, replace(base, identifiers=codes), k)
            if hits:
                return hits
        return self._query(vector, replace(base, identifiers=[]), k)

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        """Return up to `cap` chunks matching the filters, unranked."""
        with self._read_lock:
            chunks = self._gateway.scroll(to_qdrant_filter(filters), cap)
        return [SearchHit(chunk, UNRANKED_SCORE) for chunk in chunks]

    def close(self) -> None:
        """Release the index."""
        self._gateway.close()

    def __enter__(self) -> "SearchService":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _query(
        self,
        vector: models.SparseVector,
        filters: SearchFilters,
        k: int,
    ) -> list[SearchHit]:
        with self._read_lock:
            scored = self._gateway.query_sparse(
                vector, to_qdrant_filter(filters), k
            )
        return [SearchHit(chunk, score) for chunk, score in scored]

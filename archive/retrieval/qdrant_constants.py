"""Constants of the Qdrant gateway."""

COLLECTION_NAME = "archive_chunks"
SPARSE_VECTOR_NAME = "bm25"
QDRANT_SUBDIR = "qdrant"
UPSERT_BATCH_SIZE = 64
SCROLL_PAGE_SIZE = 256
HASH_INDEX_MASK = 0x7FFFFFFF
POINT_ID_NAMESPACE_NAME = "archive.chunk"
KEYWORD_PAYLOAD_FIELDS = ("identifiers", "doc_type", "doc_id")
TOKEN_SPLIT_PATTERN = r"[^a-z0-9]+"
# Hyphenated word, e.g. f-2023-0042 (kept only when it has a digit).
CODE_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)+"
TF_SATURATION_K1 = 1.2

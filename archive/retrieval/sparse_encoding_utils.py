"""Text to sparse-vector encoding and deterministic point ids."""

import re
import uuid
import zlib
from collections import Counter

from qdrant_client import models

from archive.common.constants import STOPWORDS
from archive.ingest.text_normalize_utils import normalize_for_match
from archive.retrieval.qdrant_constants import (
    CODE_PATTERN,
    HASH_INDEX_MASK,
    POINT_ID_NAMESPACE_NAME,
    TF_SATURATION_K1,
    TOKEN_SPLIT_PATTERN,
)

_POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, POINT_ID_NAMESPACE_NAME)
_SPLIT = re.compile(TOKEN_SPLIT_PATTERN)
_CODE = re.compile(CODE_PATTERN)


def tokenize(text: str) -> list[str]:
    """Split text into match tokens.

    Hyphenated codes containing a digit (e.g. `F-2023-0042`) are
    indexed both as one whole token (`f-2023-0042`) and as parts, so
    exact-code queries match strongly and partial ones still match.
    Stopwords and empty tokens are dropped.
    """
    folded = normalize_for_match(text)
    tokens = [
        code
        for code in _CODE.findall(folded)
        if any(char.isdigit() for char in code)
    ]
    tokens.extend(_SPLIT.split(folded))
    return [token for token in tokens if token and token not in STOPWORDS]


def _saturate(term_count: int) -> float:
    return (
        term_count * (TF_SATURATION_K1 + 1) / (term_count + TF_SATURATION_K1)
    )


def sparse_vector(text: str) -> models.SparseVector:
    """Hash tokens to sparse indices with saturated term frequencies.

    The hash is `crc32` masked to 31 bits, stable across processes.
    Colliding tokens have their counts summed; indices are sorted.
    Values are `tf * (k1 + 1) / (tf + k1)` (BM25 saturation, no length
    normalization) so a frequent common part cannot outweigh a rare
    whole code.
    """
    counts: Counter[int] = Counter()
    for token in tokenize(text):
        index = zlib.crc32(token.encode("utf-8")) & HASH_INDEX_MASK
        counts[index] += 1
    indices = sorted(counts)
    return models.SparseVector(
        indices=indices, values=[_saturate(counts[i]) for i in indices]
    )


def point_id(chunk_id: str) -> str:
    """Deterministic UUID for a chunk id."""
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, chunk_id))

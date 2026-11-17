"""Constants for identifier expansion and the hop loop."""

from archive.common.chunk_model import DocType

# Expand

EXPAND_SOURCE_HITS = 3
EXPAND_SHARED_MIN_HITS = 2
EXPAND_MAX_CODES = 6
EXPAND_PER_CODE_CAP = 4
EXPAND_CAP = 8
EMAIL_MARKER = "@"
EXPAND_DOC_TYPES = [DocType.PROJECT_SHEET.value, DocType.CONTRACT.value]

# Loop

MULTI_HOP_MAX_DRAFTS = 3
SAFETY_NET_MAX_DRAFTS = 2
HOP_TIME_BUDGET_S = 35.0
HOP_NEW_HITS_MAX = 6
MIN_ORIGINAL_SLOTS = 4
FOLLOW_UP_K = 8
FOLLOW_UP_TYPED_K = 5
FOLLOW_UP_DOC_TYPES = [
    DocType.DIRECTORY.value,
    DocType.PROJECT_SHEET.value,
    DocType.CONTRACT.value,
]
MISSING_QUERY_MAX_CHARS = 300
HOP_LOG_MISSING_MAX_CHARS = 120
LOG_DRAFT = "question %s: draft %d status=%s sufficient=%s missing=%r"
LOG_FOLLOW_UP = "question %s: hop %d added %d new chunks"
LOG_NO_NEW_CHUNKS = "question %s: hop %d found no new chunk, stopping"

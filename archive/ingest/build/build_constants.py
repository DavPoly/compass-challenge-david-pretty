"""Constants of the index build and its manifest."""

MANIFEST_FILE_NAME = "manifest.json"
MANIFEST_TMP_SUFFIX = ".tmp"
MANIFEST_INDENT = 1
BUILD_FLUSH_CHUNKS = 512
BUILD_MAP_CHUNKSIZE = 8
FILE_HASH_BLOCK_BYTES = 1 << 20
LOG_SYNC_FULL_BUILD = "no usable index at %s (%s): running a full build"
LOG_SYNC_SKIPPED = "skipped %s: %s"
REASON_NO_STORAGE = "no Qdrant storage"
REASON_NO_COLLECTION = "no collection"
LOG_SYNC_DONE = (
    "index sync: %d added, %d changed, %d removed, %d failed, %d sparse-only"
)
DENSE_BATCH_SIZE = 32
DENSE_LOG_EVERY_BATCHES = 16
SYNC_DENSE_BUDGET_S = 180.0
LOG_DENSE_PROGRESS = "dense embedding: %d chunks done"
LOG_DENSE_BUDGET_SPENT = (
    "dense budget of %.0f s spent: %d chunks indexed sparse-only"
)
LOG_DENSE_FAILED = "dense embedding failed (%s): %d chunks indexed sparse-only"
LOG_DENSE_INDEX_SPARSE = "index has no dense vector: syncing sparse-only"

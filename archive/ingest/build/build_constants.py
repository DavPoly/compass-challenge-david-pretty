"""Constants of the index build and its manifest."""

MANIFEST_FILE_NAME = "manifest.json"
MANIFEST_TMP_SUFFIX = ".tmp"
MANIFEST_INDENT = 1
BUILD_FLUSH_CHUNKS = 512
BUILD_MAP_CHUNKSIZE = 8
FILE_HASH_BLOCK_BYTES = 1 << 20
LOG_SYNC_FULL_BUILD = "no usable index at %s (%s): running a full build"
LOG_SYNC_SKIPPED = "skipped %s: %s"
LOG_SYNC_DONE = "index sync: %d added, %d changed, %d removed, %d failed"

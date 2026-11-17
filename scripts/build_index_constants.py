"""Constants of the index build script."""

SQLITE_NAME = "storage.sqlite"
BYTES_PER_MB = 1024 * 1024
STORAGE_SIZE_LIMIT_MB = 100
MSG_NO_PDFS = "No PDFs found in {path}. Pass --corpus with the PDF directory."
MSG_NO_EMBEDDER = (
    "The dense model could not be loaded (see the warning above). "
    "Fix the download or pass --sparse-only to build a BM25-only index."
)
MSG_SIZE = "storage.sqlite size: {size_mb:.1f} MB"
MSG_SIZE_OVER_LIMIT = (
    "WARNING: storage.sqlite is {size_mb:.1f} MB, at or above the "
    "{limit_mb} MB limit. Shrink the index before committing it."
)

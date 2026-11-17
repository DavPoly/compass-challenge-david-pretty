"""Constants for the run pipeline."""

WORKER_COUNT = 8
QUESTION_BUDGET_S = 60.0
GLOBAL_DEADLINE_S = 17 * 60.0
POLL_INTERVAL_S = 0.5

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

ANSWERS_ENCODING = "utf-8"

MSG_NO_CORPUS = (
    "No PDF found in corpus directory {path}. Run the command from the "
    "repo root and put the PDFs in corpus/."
)
MSG_IO_ERROR = "I/O error while answering {path}: {reason}"
MSG_INDEX_OPEN = "Cannot open the index at {path}: {reason}"
LOG_DOC_IDS_DIFFER = (
    "manifest and corpus doc ids differ: %d in manifest, %d in corpus, "
    "%d valid; rebuild the index if the corpus changed"
)
LOG_QUESTION_INVALID = "question %s invalid (%s): not_found"
LOG_QUESTION_ISSUE = "question %s: %s"
LOG_DROPPED_CITATIONS = "question %s: dropped citations %s"
LOG_LLM_UNAVAILABLE = "question %s: LLM unavailable: %s"
LOG_UNEXPECTED_ERROR = "question %s: unexpected error"
LOG_LATE_RESULT = "question %s: late result discarded"
LOG_OVER_BUDGET = "question %s: over %.0f s budget, not_found"
LOG_DEADLINE_REACHED = "question %s: global deadline reached, not_found"
LOG_SYNC_FAILED = "index sync failed, using the existing index"
LOG_SYNC_REPORT = (
    "index sync: %d added, %d changed, %d removed, %d failed, "
    "%d sparse-only in %.1f s"
)
LOG_MODELS_ACTIVE = "search models: dense=%s, rerank=%s"
LOG_DENSE_UNAVAILABLE = "dense model unavailable: BM25-only search"
MODEL_LOAD_WORKERS = 2

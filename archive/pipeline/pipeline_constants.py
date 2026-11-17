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
LOG_GROUNDING_CONFIDENCE = "question %s: grounding confidence %s"
LOG_GROUNDING_FAILED = "question %s: grounding check failed"
LOG_DROPPED_CITATIONS = "question %s: dropped citations %s"
LOG_LLM_UNAVAILABLE = "question %s: LLM unavailable: %s"
LOG_UNEXPECTED_ERROR = "question %s: unexpected error"
LOG_LATE_RESULT = "question %s: late result discarded"
LOG_OVER_BUDGET = "question %s: over %.0f s budget, not_found"
LOG_DEADLINE_REACHED = "question %s: global deadline reached, not_found"
MSG_LATE_TRACE = (
    "late result discarded: the question was already answered "
    "not_found (over budget or global deadline)"
)
MSG_OVER_BUDGET_TRACE = "over the per-question budget: answered not_found"
MSG_DEADLINE_TRACE = "global deadline reached: answered not_found"
LOG_SYNC_FAILED = "index sync failed, using the existing index"
LOG_SYNC_REPORT = (
    "index sync: %d added, %d changed, %d removed, %d failed, "
    "%d sparse-only in %.1f s"
)
LOG_MODELS_ACTIVE = "search models: dense=%s, rerank=%s"
LOG_DENSE_UNAVAILABLE = "dense model unavailable: BM25-only search"
MODEL_LOAD_WORKERS = 2
LOG_TRACE_WRITE_FAILED = "question %s: trace not written"
LOG_VIEWER_READY = "viewer ready: open %s in a browser"
LOG_VIEWER_FAILED = "viewer not built; answers are unaffected"
RUN_ID_FORMAT = "%Y%m%d-%H%M%S"
TRACE_SUFFIX = ".json"
TRACE_ENCODING = "utf-8"
TRACE_TEMP_SUFFIX = ".tmp"
TRACE_JSON_INDENT = 2
TRACE_SAFE_NAME_PATTERN = r"[^A-Za-z0-9_.-]"
TRACE_UNSAFE_REPLACEMENT = "_"
TRACE_FALLBACK_NAME = "question"
TRACE_HASH_CHARS = 8
TRACE_HASH_SEPARATOR = "-"
TRACE_VERSION = 1

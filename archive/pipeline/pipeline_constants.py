"""Constants for the run pipeline."""

WORKER_COUNT = 8
SEARCH_TOP_K = 8
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
MSG_CANNOT_WRITE = (
    "Cannot write answers file {path}: {reason}. Choose a writable path."
)
MSG_INDEX_OPEN = "Cannot open the index at {path}: {reason}"
MSG_DOC_IDS_DIFFER = (
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
LOG_DUPLICATE_ID = "duplicate question id %s ignored"

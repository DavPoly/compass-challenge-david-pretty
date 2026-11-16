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

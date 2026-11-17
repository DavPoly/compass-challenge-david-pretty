"""Constants of the viewer build script."""

SCRIPT_DESCRIPTION = "Build the static HTML viewer of a run from its traces."
HELP_TRACE_DIR = "directory of the run traces, e.g. traces/<run_id>"
HELP_SCORES = (
    "scores JSON from: python score.py answers.jsonl --json --details"
)
HELP_OUT = "output directory (default: viewer/<trace directory name>)"
HELP_CORPUS = "directory of the source PDFs (default: corpus/)"
MSG_NO_TRACE_DIR = (
    "Trace directory {path} not found. Run answer.py first, then pass "
    "the traces/<run_id> directory it wrote."
)
MSG_VIEWER_READY = "viewer written: {path}"
MSG_BUILD_FAILED = "Cannot build the viewer: {reason}"

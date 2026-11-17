"""Constants of the live server script."""

LIVE_DIRNAME = "live"
SERVER_DIRNAME = "server"
EMPTY_RUN_DIRNAME = "no-run"

SCRIPT_DESCRIPTION = (
    "Serve the viewer on localhost and answer questions typed in it."
)
HELP_RUN = "finished answer.py run to show, e.g. traces/<run_id>"
HELP_PORT = "port to listen on, 127.0.0.1 only (default: {port})"
HELP_CORPUS = "directory of the source PDFs (default: corpus/)"

MSG_NO_RUN_DIR = (
    "Trace directory {path} not found. Pass a traces/<run_id> directory "
    "written by answer.py, or omit --run."
)
MSG_BUILD_FAILED = "Cannot build the viewer: {reason}"
MSG_PORT_BUSY = (
    "Cannot listen on port {port}: {reason}. Choose another port with --port."
)
MSG_READY = "Server ready: http://{host}:{port}"
MSG_STOPPED = "Server stopped."
LOG_PAGE_REBUILT = "page rebuilt with the new question"

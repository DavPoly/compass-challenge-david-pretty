"""Constants of the live server script."""

LIVE_DIRNAME = "live"
SERVER_DIRNAME = "server"
EMPTY_RUN_DIRNAME = "no-run"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

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
    "Impossible d'écouter sur le port {port} : {reason}. "
    "Choisissez un autre port avec --port."
)
MSG_READY = "Serveur prêt : http://{host}:{port}"
MSG_STOPPED = "Serveur arrêté."
LOG_PAGE_REBUILT = "page rebuilt with the new question"

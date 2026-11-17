"""Constants of the live question server."""

from archive.common.step_constants import STEP_LABELS

__all__ = ["STEP_LABELS"]

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_BODY_BYTES = 8 * 1024
MAX_QUESTION_CHARS = 500
REQUEST_TIMEOUT_S = 30.0
LINGER_LIMIT_BYTES = 64 * 1024
ENCODING = "utf-8"

LIVE_RUN_ID = "live"
LIVE_ID_PREFIX = "live-"
LIVE_ID_FORMAT = LIVE_ID_PREFIX + "{number:03d}"
LIVE_ID_PATTERN = r"live-(\d+)"
LIVE_TRACE_SUFFIX = ".json"

ROUTE_INDEX = "/"
ROUTE_PAGES_PREFIX = "/pages/"
ROUTE_HEALTH = "/api/health"
ROUTE_ASK = "/api/ask"
PAGES_DIRNAME = "pages"
INDEX_FILENAME = "index.html"
IMAGE_MIME_PREFIX = "image/"

CONTENT_TYPE_HTML = "text/html; charset=utf-8"
CONTENT_TYPE_JSON = "application/json; charset=utf-8"
CONTENT_TYPE_SSE = "text/event-stream"
JSON_MEDIA_TYPE = "application/json"
LOCAL_HOST_NAMES = (HOST, "localhost")
HOST_FORMAT = "{name}:{port}"
ORIGIN_FORMAT = "http://{name}:{port}"
CACHE_NO_CACHE = "no-cache"
UNSAFE_NAME_CHARS = ("/", "\\", ":", "\0")
PARENT_REF = ".."

EVENT_STEP = "step"
EVENT_RESULT = "result"
EVENT_ERROR = "error"
SSE_FORMAT = "event: {name}\ndata: {data}\n\n"

MSG_BUSY = (
    "Une question est déjà en cours de traitement. Réessayez dans un instant."
)
MSG_EMPTY_QUESTION = "La question est vide. Saisissez une question."
MSG_QUESTION_TOO_LONG = (
    "La question dépasse {limit} caractères. Raccourcissez-la."
)
MSG_BAD_REQUEST = 'Requête invalide : envoyez un JSON {{"question": "..."}}.'
MSG_UNSUPPORTED_MEDIA_TYPE = (
    "Requête invalide : le Content-Type doit être application/json."
)
MSG_FORBIDDEN = (
    "Requête refusée : seule la page servie par ce serveur local peut "
    "l'utiliser."
)
MSG_BODY_TOO_LARGE = "La requête est trop volumineuse."
MSG_LLM_UNAVAILABLE = (
    "Le modèle de langue est indisponible : vérifiez LLM_API_KEY, "
    "LLM_MODEL et LLM_BASE_URL."
)
MSG_UNEXPECTED = (
    "Une erreur inattendue est survenue ; consultez les logs du serveur."
)
MSG_NOT_FOUND = "Ressource introuvable."

LOG_REQUEST = "%s - %s"
LOG_CLIENT_GONE = "client disconnected during question %s"
LOG_ASK_FAILED = "question failed unexpectedly"
LOG_LLM_UNAVAILABLE = "LLM unavailable: %s"
LOG_RESULT_HOOK_FAILED = "result hook failed"
LOG_REBUILD_FAILED = "page rebuild failed; the page keeps its content"
LOG_REQUEST_REFUSED = "refused request from %s: Host=%r Origin=%r"
LOG_BODY_NOT_READ = "request body not received from %s: %s"
LOG_QUESTION_SAVED = "live question %s answered in %.1f s"

HTML_SUFFIX = ".html"
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_CONTENT_LENGTH = "Content-Length"
HEADER_HOST = "Host"
HEADER_ORIGIN = "Origin"
HEADER_CACHE_CONTROL = "Cache-Control"
KEY_READY = "ready"
KEY_BUSY = "busy"
KEY_ERROR = "error"
STEP_ELAPSED_DECIMALS = 2
WINDOWS_OS_NAME = "nt"

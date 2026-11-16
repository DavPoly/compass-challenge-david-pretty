"""Constants for the LLM gateway."""

TEMPERATURE = 0
REQUEST_TIMEOUT_S = 12.0

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 1.0
BACKOFF_FACTOR = 2
BACKOFF_CAP_S = 4.0
RETRY_AFTER_CAP_S = 8.0
RETRY_AFTER_HEADER = "retry-after"

HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_REQUEST_TIMEOUT = 408
HTTP_CONFLICT = 409
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR_MIN = 500
RETRYABLE_CLIENT_STATUSES = frozenset(
    {HTTP_REQUEST_TIMEOUT, HTTP_CONFLICT, HTTP_TOO_MANY_REQUESTS}
)
AUTH_STATUSES = frozenset({HTTP_UNAUTHORIZED, HTTP_FORBIDDEN})

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

KEY_MODEL = "model"
KEY_MESSAGES = "messages"
KEY_TEMPERATURE = "temperature"
KEY_RESPONSE_FORMAT = "response_format"
KEY_ROLE = "role"
KEY_CONTENT = "content"

RESPONSE_FORMAT_JSON_SCHEMA = "json_schema"
KEY_TYPE = "type"
KEY_NAME = "name"
KEY_SCHEMA = "schema"
KEY_STRICT = "strict"
SCHEMA_IS_STRICT = False

SCHEMA_REJECTION_MARKERS = (
    KEY_RESPONSE_FORMAT,
    RESPONSE_FORMAT_JSON_SCHEMA,
)
MAX_VALIDATION_ERROR_CHARS = 1500

JSON_IN_TEXT_INSTRUCTION = (
    "Reply with a single JSON object and nothing else (no prose, no "
    "code fences). It must validate against this JSON Schema:\n{schema}"
)

REPAIR_INSTRUCTION = (
    "Your previous reply was not valid. Problem:\n{error}\n"
    "Reply again with the corrected JSON object only, matching the "
    "required schema."
)

AUTH_HINT = "check LLM_API_KEY (and that it matches LLM_BASE_URL)"
NOT_FOUND_HINT = "check LLM_MODEL and LLM_BASE_URL"
REJECTED_HINT = (
    "the provider rejected the request; check that LLM_MODEL accepts "
    "it and see the provider status"
)

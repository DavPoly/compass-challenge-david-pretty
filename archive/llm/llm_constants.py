"""Constants for the LLM gateway."""

TEMPERATURE = 0
REQUEST_TIMEOUT_S = 12.0

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 4.0
RETRY_AFTER_CAP_S = 8.0
RETRY_AFTER_HEADER = "retry-after"

HTTP_BAD_REQUEST = 400
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR_MIN = 500

SCHEMA_REJECTION_MARKERS = ("response_format", "json_schema")
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

UNAVAILABLE_AUTH_HINT = "check LLM_API_KEY and LLM_MODEL (and LLM_BASE_URL)"

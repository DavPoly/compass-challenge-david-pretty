"""Gateway to the hosted LLM (OpenAI-compatible chat completions)."""

import json
import logging
import random
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from archive.common.config import AppConfig
from archive.llm.llm_constants import (
    AUTH_HINT,
    AUTH_STATUSES,
    BACKOFF_BASE_S,
    BACKOFF_CAP_S,
    BACKOFF_FACTOR,
    HTTP_BAD_REQUEST,
    HTTP_NOT_FOUND,
    HTTP_SERVER_ERROR_MIN,
    JSON_IN_TEXT_INSTRUCTION,
    KEY_CONTENT,
    KEY_MESSAGES,
    KEY_MODEL,
    KEY_NAME,
    KEY_RESPONSE_FORMAT,
    KEY_ROLE,
    KEY_SCHEMA,
    KEY_STRICT,
    KEY_TEMPERATURE,
    KEY_TYPE,
    MAX_ATTEMPTS,
    MAX_VALIDATION_ERROR_CHARS,
    NOT_FOUND_HINT,
    REJECTED_HINT,
    REPAIR_INSTRUCTION,
    REQUEST_TIMEOUT_S,
    RESPONSE_FORMAT_JSON_SCHEMA,
    RETRY_AFTER_CAP_S,
    RETRY_AFTER_HEADER,
    RETRYABLE_CLIENT_STATUSES,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    SCHEMA_IS_STRICT,
    SCHEMA_REJECTION_MARKERS,
    TEMPERATURE,
)

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)
Messages = Sequence[Mapping[str, str]]
_INVALID_OUTPUT = (ValidationError, ValueError)


class LlmUnavailableError(Exception):
    """The LLM cannot be used: retries exhausted or a fatal API error."""


class LlmResponseError(LlmUnavailableError):
    """Output still failed schema validation after the repair re-prompt.

    Subclasses `LlmUnavailableError` so callers that degrade on an
    unusable LLM need a single handler.
    """


def extract_json_object(text: str) -> str:
    """Return the first balanced `{...}` in `text`, or `text` stripped.

    Handles code fences and surrounding prose; braces inside JSON
    strings are ignored.
    """
    start = text.find("{")
    if start < 0:
        return text.strip()
    end = _find_object_end(text, start)
    if end is None:
        return text[start:].strip()
    return text[start : end + 1]


def _find_object_end(text: str, start: int) -> int | None:
    """Index of the `}` closing the object opened at `start`."""
    depth = 0
    in_string = False
    is_escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if is_escaped:
            is_escaped = False
        elif in_string:
            is_escaped = char == "\\"
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def parse_retry_after(value: str | None) -> float | None:
    """Parse a `Retry-After` header (seconds or HTTP date) to seconds."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


class LlmGateway:
    """Thread-safe JSON-returning chat client with retries.

    One instance (and its HTTP client) may be shared across threads.

    Args:
        config: supplies the model, base URL and API key.
        client: OpenAI-compatible client; built from `config` if None.
        sleep: delay function used between retries (injectable).
        rng: random source for backoff jitter (injectable).
    """

    def __init__(
        self,
        config: AppConfig,
        client: OpenAI | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._model = config.llm_model
        self._client = client or OpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            max_retries=0,
            timeout=REQUEST_TIMEOUT_S,
        )
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._is_schema_format_rejected = False

    def complete_json(
        self, messages: Messages, schema: type[ModelT]
    ) -> ModelT:
        """Get a reply validated against `schema`.

        Sends the request with a `json_schema` response format (or
        JSON-in-text if the provider rejected it), then re-prompts once
        if the output is not valid.

        Raises:
            LlmUnavailableError: retries exhausted or fatal API error
                (e.g. bad key or model).
            LlmResponseError: output invalid even after the repair.
        """
        content = self._request(messages, schema)
        try:
            return self._parse(content, schema)
        except _INVALID_OUTPUT as first_error:
            logger.warning("LLM output invalid, sending repair prompt")
            repair = self._repair_messages(messages, content, first_error)
        content = self._request(repair, schema)
        try:
            return self._parse(content, schema)
        except _INVALID_OUTPUT as error:
            raise LlmResponseError(
                "LLM output failed validation against "
                f"{schema.__name__} after one repair attempt: "
                f"{self._short_error(error)}. Retry the question or "
                "check that LLM_MODEL follows JSON instructions."
            ) from error

    @staticmethod
    def _parse(content: str, schema: type[ModelT]) -> ModelT:
        return schema.model_validate_json(extract_json_object(content))

    @staticmethod
    def _short_error(error: Exception) -> str:
        return str(error)[:MAX_VALIDATION_ERROR_CHARS]

    def _repair_messages(
        self, messages: Messages, bad_output: str, error: Exception
    ) -> list[Mapping[str, str]]:
        """Append the bad reply and a correction request.

        A blank reply is left out: some backends reject empty
        assistant turns.
        """
        repair_turn = {
            KEY_ROLE: ROLE_USER,
            KEY_CONTENT: REPAIR_INSTRUCTION.format(
                error=self._short_error(error)
            ),
        }
        if not bad_output.strip():
            return [*messages, repair_turn]
        bad_turn = {KEY_ROLE: ROLE_ASSISTANT, KEY_CONTENT: bad_output}
        return [*messages, bad_turn, repair_turn]

    def _build_kwargs(
        self, messages: Messages, schema: type[ModelT]
    ) -> dict[str, Any]:
        # Any: kwargs are forwarded to the OpenAI SDK (real boundary).
        with self._lock:
            is_text_mode = self._is_schema_format_rejected
        kwargs: dict[str, Any] = {
            KEY_MODEL: self._model,
            KEY_TEMPERATURE: TEMPERATURE,
            KEY_MESSAGES: list(messages),
        }
        json_schema = schema.model_json_schema()
        if is_text_mode:
            instruction = JSON_IN_TEXT_INSTRUCTION.format(
                schema=json.dumps(json_schema)
            )
            kwargs[KEY_MESSAGES] = [
                {KEY_ROLE: ROLE_SYSTEM, KEY_CONTENT: instruction},
                *messages,
            ]
        else:
            kwargs[KEY_RESPONSE_FORMAT] = {
                KEY_TYPE: RESPONSE_FORMAT_JSON_SCHEMA,
                RESPONSE_FORMAT_JSON_SCHEMA: {
                    KEY_NAME: schema.__name__,
                    KEY_SCHEMA: json_schema,
                    KEY_STRICT: SCHEMA_IS_STRICT,
                },
            }
        return kwargs

    def _call_once(self, messages: Messages, schema: type[ModelT]) -> str:
        """One API call; resent in JSON-in-text mode if refused."""
        kwargs = self._build_kwargs(messages, schema)
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.APIStatusError as error:
            if self._reject_schema_format(error, kwargs):
                return self._call_once(messages, schema)
            raise
        return response.choices[0].message.content or ""

    def _request(self, messages: Messages, schema: type[ModelT]) -> str:
        """Call the API with retries; return the message content."""
        attempt = 1
        while True:
            try:
                return self._call_once(messages, schema)
            except openai.APIStatusError as error:
                if not self._is_retryable_status(error.status_code):
                    raise self._fatal(error) from error
                self._backoff_or_raise(attempt, error, error.status_code)
            except openai.APIConnectionError as error:
                # Also covers APITimeoutError.
                self._backoff_or_raise(attempt, error, None)
            attempt += 1

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return (
            status_code in RETRYABLE_CLIENT_STATUSES
            or status_code >= HTTP_SERVER_ERROR_MIN
        )

    def _reject_schema_format(
        self, error: openai.APIStatusError, kwargs: Mapping[str, Any]
    ) -> bool:
        """Switch to JSON-in-text when the provider refuses json_schema.

        Returns True when the request should be rebuilt and resent.
        """
        if error.status_code != HTTP_BAD_REQUEST:
            return False
        if KEY_RESPONSE_FORMAT not in kwargs:
            return False
        text = str(error).lower()
        if not any(marker in text for marker in SCHEMA_REJECTION_MARKERS):
            return False
        logger.warning("Provider rejected json_schema; using JSON-in-text")
        with self._lock:
            self._is_schema_format_rejected = True
        return True

    @staticmethod
    def _fatal(error: openai.APIStatusError) -> LlmUnavailableError:
        status = error.status_code
        logger.error("LLM request failed with status %s", status)
        if status in AUTH_STATUSES:
            hint = AUTH_HINT
        elif status == HTTP_NOT_FOUND:
            hint = NOT_FOUND_HINT
        else:
            hint = REJECTED_HINT
        return LlmUnavailableError(
            f"LLM request failed with HTTP {status} "
            f"({type(error).__name__}); {hint}."
        )

    def _backoff_or_raise(
        self, attempt: int, error: Exception, status_code: int | None
    ) -> None:
        logger.warning(
            "LLM call failed (attempt %d/%d, status=%s, %s)",
            attempt,
            MAX_ATTEMPTS,
            status_code,
            type(error).__name__,
        )
        if attempt >= MAX_ATTEMPTS:
            raise LlmUnavailableError(
                f"LLM unavailable after {MAX_ATTEMPTS} attempts "
                f"(last error: {type(error).__name__}, "
                f"status={status_code}). Check network access to "
                "LLM_BASE_URL and the provider status, then retry."
            ) from error
        self._sleep(self._delay_s(attempt, error))

    def _delay_s(self, attempt: int, error: Exception) -> float:
        if isinstance(error, openai.APIStatusError):
            header = error.response.headers.get(RETRY_AFTER_HEADER)
            retry_after = parse_retry_after(header)
            if retry_after is not None:
                return min(retry_after, RETRY_AFTER_CAP_S)
        ceiling = min(
            BACKOFF_CAP_S, BACKOFF_BASE_S * BACKOFF_FACTOR ** (attempt - 1)
        )
        return self._rng.uniform(0.0, ceiling)

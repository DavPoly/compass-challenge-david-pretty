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
    BACKOFF_BASE_S,
    BACKOFF_CAP_S,
    HTTP_BAD_REQUEST,
    HTTP_SERVER_ERROR_MIN,
    HTTP_TOO_MANY_REQUESTS,
    JSON_IN_TEXT_INSTRUCTION,
    MAX_ATTEMPTS,
    MAX_VALIDATION_ERROR_CHARS,
    REPAIR_INSTRUCTION,
    REQUEST_TIMEOUT_S,
    RETRY_AFTER_CAP_S,
    RETRY_AFTER_HEADER,
    SCHEMA_REJECTION_MARKERS,
    TEMPERATURE,
    UNAVAILABLE_AUTH_HINT,
)

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)
Messages = Sequence[Mapping[str, str]]


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
    depth = 0
    in_string = False
    is_escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if is_escaped:
                is_escaped = False
            elif char == "\\":
                is_escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:].strip()


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
        except (ValidationError, ValueError) as first_error:
            logger.warning("LLM output invalid, sending repair prompt")
            repair = self._repair_messages(messages, content, first_error)
        content = self._request(repair, schema)
        try:
            return self._parse(content, schema)
        except (ValidationError, ValueError) as error:
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
        return [
            *messages,
            {"role": "assistant", "content": bad_output},
            {
                "role": "user",
                "content": REPAIR_INSTRUCTION.format(
                    error=self._short_error(error)
                ),
            },
        ]

    def _build_kwargs(
        self, messages: Messages, schema: type[ModelT]
    ) -> dict[str, Any]:
        with self._lock:
            is_text_mode = self._is_schema_format_rejected
        kwargs: dict[str, Any] = {
            "model": self._model,
            "temperature": TEMPERATURE,
            "messages": list(messages),
        }
        json_schema = schema.model_json_schema()
        if is_text_mode:
            instruction = JSON_IN_TEXT_INSTRUCTION.format(
                schema=json.dumps(json_schema)
            )
            kwargs["messages"] = [
                {"role": "system", "content": instruction},
                *messages,
            ]
        else:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": False,
                },
            }
        return kwargs

    def _request(self, messages: Messages, schema: type[ModelT]) -> str:
        """Call the API with retries; return the message content."""
        attempt = 1
        while True:
            kwargs = self._build_kwargs(messages, schema)
            try:
                response = self._client.chat.completions.create(**kwargs)
            except openai.APIStatusError as error:
                if self._reject_schema_format(error, kwargs):
                    continue
                if not self._is_retryable_status(error.status_code):
                    raise self._fatal(error) from error
                self._backoff_or_raise(attempt, error, error.status_code)
            except (openai.APITimeoutError, openai.APIConnectionError) as e:
                self._backoff_or_raise(attempt, e, None)
            else:
                return response.choices[0].message.content or ""
            attempt += 1

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return (
            status_code == HTTP_TOO_MANY_REQUESTS
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
        if "response_format" not in kwargs:
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
        return LlmUnavailableError(
            f"LLM request failed with HTTP {status} "
            f"({type(error).__name__}); {UNAVAILABLE_AUTH_HINT}."
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
        ceiling = min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (attempt - 1))
        return self._rng.uniform(0.0, ceiling)

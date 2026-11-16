"""Tests for the LLM gateway using a scripted fake client."""

import random
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import openai
import pytest
from openai import OpenAI
from pydantic import BaseModel

from archive.common.config import AppConfig
from archive.llm.llm_constants import MAX_ATTEMPTS, RETRY_AFTER_CAP_S
from archive.llm.llm_gateway import (
    LlmGateway,
    LlmResponseError,
    LlmUnavailableError,
    parse_retry_after,
)

REQUEST = httpx.Request("POST", "https://llm.test/v1/chat/completions")
GOOD = '{"text": "hi", "score": 3}'
MESSAGES = [{"role": "user", "content": "question"}]


class Answer(BaseModel):
    text: str
    score: int


def make_status_error(
    cls: type[openai.APIStatusError],
    status: int,
    headers: dict[str, str] | None = None,
    message: str = "boom",
) -> openai.APIStatusError:
    response = httpx.Response(
        status, headers=headers, request=REQUEST, json={"error": message}
    )
    return cls(message, response=response, body=None)


def reply(content: str | None) -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    """Plays back scripted replies or exceptions in order."""

    def __init__(self, script: list[Any]) -> None:
        self.script = deque(script)
        self.calls: list[dict[str, Any]] = []
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.script.popleft()
        if isinstance(item, Exception):
            raise item
        return item


def make_gateway(
    script: list[Any],
) -> tuple[LlmGateway, FakeClient, list[float]]:
    config = AppConfig(
        llm_base_url="https://llm.test/v1",
        llm_api_key="secret-key",
        llm_model="test-model",
        corpus_dir=Path("corpus"),
        index_dir=Path("index"),
    )
    client = FakeClient(script)
    sleeps: list[float] = []
    gateway = LlmGateway(
        config,
        client=cast(OpenAI, client),
        sleep=sleeps.append,
        rng=random.Random(0),
    )
    return gateway, client, sleeps


def test_happy_path_sends_json_schema() -> None:
    gateway, client, sleeps = make_gateway([reply(GOOD)])

    result = gateway.complete_json(MESSAGES, Answer)

    assert result == Answer(text="hi", score=3)
    kwargs = client.calls[0]
    assert kwargs["model"] == "test-model"
    assert kwargs["temperature"] == 0
    assert kwargs["response_format"]["type"] == "json_schema"
    schema = kwargs["response_format"]["json_schema"]["schema"]
    assert "text" in schema["properties"]
    assert sleeps == []


def test_rate_limit_honours_retry_after() -> None:
    error = make_status_error(openai.RateLimitError, 429, {"Retry-After": "7"})
    gateway, _, sleeps = make_gateway([error, reply(GOOD)])

    gateway.complete_json(MESSAGES, Answer)

    assert sleeps == [7.0]


def test_retry_after_is_capped() -> None:
    error = make_status_error(
        openai.RateLimitError, 429, {"Retry-After": "9999"}
    )
    gateway, _, sleeps = make_gateway([error, reply(GOOD)])

    gateway.complete_json(MESSAGES, Answer)

    assert sleeps == [RETRY_AFTER_CAP_S]


def test_timeout_then_success() -> None:
    error = openai.APITimeoutError(request=REQUEST)
    gateway, client, sleeps = make_gateway([error, reply(GOOD)])

    result = gateway.complete_json(MESSAGES, Answer)

    assert result.score == 3
    assert len(client.calls) == 2
    assert len(sleeps) == 1


def test_server_errors_exhaust_retries() -> None:
    errors = [
        make_status_error(openai.InternalServerError, 503)
        for _ in range(MAX_ATTEMPTS)
    ]
    gateway, client, sleeps = make_gateway(errors)

    with pytest.raises(LlmUnavailableError):
        gateway.complete_json(MESSAGES, Answer)

    assert len(client.calls) == MAX_ATTEMPTS
    assert len(sleeps) == MAX_ATTEMPTS - 1


def test_auth_error_is_not_retried() -> None:
    error = make_status_error(openai.AuthenticationError, 401)
    gateway, client, sleeps = make_gateway([error])

    with pytest.raises(LlmUnavailableError) as raised:
        gateway.complete_json(MESSAGES, Answer)

    assert len(client.calls) == 1
    assert sleeps == []
    assert "LLM_API_KEY" in str(raised.value)
    assert "secret-key" not in str(raised.value)


def test_bad_json_then_repair_succeeds() -> None:
    gateway, client, _ = make_gateway([reply("not json"), reply(GOOD)])

    result = gateway.complete_json(MESSAGES, Answer)

    assert result.text == "hi"
    repair_messages = client.calls[1]["messages"]
    assert repair_messages[-2] == {
        "role": "assistant",
        "content": "not json",
    }
    assert repair_messages[-1]["role"] == "user"


def test_repair_failure_raises() -> None:
    bad = '{"text": "hi"}'
    gateway, client, _ = make_gateway([reply(bad), reply(bad)])

    with pytest.raises(LlmResponseError):
        gateway.complete_json(MESSAGES, Answer)

    assert len(client.calls) == 2


def test_empty_content_triggers_repair() -> None:
    gateway, _, _ = make_gateway([reply(None), reply(GOOD)])

    assert gateway.complete_json(MESSAGES, Answer).score == 3


def test_fenced_json_with_prose_is_extracted() -> None:
    content = 'Sure!\n```json\n{"text": "a } b", "score": 1}\n```\nDone'
    gateway, client, _ = make_gateway([reply(content)])

    result = gateway.complete_json(MESSAGES, Answer)

    assert result == Answer(text="a } b", score=1)
    assert len(client.calls) == 1


def test_rejected_response_format_falls_back_and_sticks() -> None:
    rejection = make_status_error(
        openai.BadRequestError,
        400,
        message="response_format json_schema unsupported",
    )
    gateway, client, _ = make_gateway([rejection, reply(GOOD), reply(GOOD)])

    gateway.complete_json(MESSAGES, Answer)
    gateway.complete_json(MESSAGES, Answer)

    assert "response_format" in client.calls[0]
    for call in client.calls[1:]:
        assert "response_format" not in call
        assert call["messages"][0]["role"] == "system"
        assert "JSON Schema" in call["messages"][0]["content"]


def test_unrelated_bad_request_is_fatal() -> None:
    error = make_status_error(
        openai.BadRequestError, 400, message="context too long"
    )
    gateway, client, _ = make_gateway([error])

    with pytest.raises(LlmUnavailableError):
        gateway.complete_json(MESSAGES, Answer)

    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", 3.0), ("-5", 0.0), (None, None), ("garbage", None)],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value) == expected


def test_parse_retry_after_http_date_in_past() -> None:
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0

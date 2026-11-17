"""HTTP gateway of the live server: static files, health and ask."""

import json
import logging
import mimetypes
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ValidationError

from archive.common.step_model import StepEvent
from archive.llm.llm_gateway import LlmUnavailableError
from archive.server.ask_service import BusyError
from archive.server.server_constants import (
    CACHE_NO_CACHE,
    CONTENT_TYPE_HTML,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_SSE,
    ENCODING,
    EVENT_ERROR,
    EVENT_RESULT,
    EVENT_STEP,
    HEADER_CACHE_CONTROL,
    HEADER_CONTENT_LENGTH,
    HEADER_CONTENT_TYPE,
    HOST,
    HTML_SUFFIX,
    IMAGE_MIME_PREFIX,
    INDEX_FILENAME,
    KEY_BUSY,
    KEY_ERROR,
    KEY_READY,
    LOG_ASK_FAILED,
    LOG_CLIENT_GONE,
    LOG_LLM_UNAVAILABLE,
    LOG_REQUEST,
    LOG_RESULT_HOOK_FAILED,
    MAX_BODY_BYTES,
    MAX_QUESTION_CHARS,
    MSG_BAD_REQUEST,
    MSG_BODY_TOO_LARGE,
    MSG_BUSY,
    MSG_EMPTY_QUESTION,
    MSG_LLM_UNAVAILABLE,
    MSG_NOT_FOUND,
    MSG_QUESTION_TOO_LONG,
    MSG_UNEXPECTED,
    PAGES_DIRNAME,
    PARENT_REF,
    ROUTE_ASK,
    ROUTE_HEALTH,
    ROUTE_INDEX,
    ROUTE_PAGES_PREFIX,
    STEP_ELAPSED_DECIMALS,
    STEP_LABELS,
    UNSAFE_NAME_CHARS,
    WINDOWS_OS_NAME,
)
from archive.server.server_model import (
    AskRequest,
    ErrorPayload,
    ResultPayload,
    StepPayload,
    format_sse,
)
from archive.viewer.viewer_model import QuestionView

logger = logging.getLogger(__name__)


class AskPort(Protocol):
    """What the gateway needs from the ask service."""

    @property
    def is_busy(self) -> bool:
        """Whether a question is being answered."""

    def ask(
        self, text: str, emit: Callable[[StepEvent], None]
    ) -> QuestionView:
        """Answer one question, reporting each step to ``emit``."""


@dataclass(frozen=True)
class ServerContext:
    """What the request handlers serve from.

    ``on_result`` runs after each answered question (page rebuild).
    """

    ask: AskPort
    out_dir: Path
    on_result: Callable[[], None]


def is_safe_page_name(name: str) -> bool:
    """Whether ``name`` is a plain file name, not a path."""
    if not name or PARENT_REF in name:
        return False
    return not any(char in name for char in UNSAFE_NAME_CHARS)


def find_page_image(pages_dir: Path, name: str) -> Path | None:
    """The image ``name`` inside ``pages_dir``, or None when unsafe."""
    if not is_safe_page_name(name):
        return None
    root = pages_dir.resolve()
    target = (root / name).resolve()
    if target.parent != root or not target.is_file():
        return None
    mime, _ = mimetypes.guess_type(target.name)
    if mime is None or not mime.startswith(IMAGE_MIME_PREFIX):
        return None
    return target


def validate_question(text: str) -> str | None:
    """A French error for an unusable question, else None."""
    stripped = text.strip()
    if not stripped:
        return MSG_EMPTY_QUESTION
    if len(stripped) > MAX_QUESTION_CHARS:
        return MSG_QUESTION_TOO_LONG.format(limit=MAX_QUESTION_CHARS)
    return None


class _EventStream:
    """Server-sent events on one response, tolerant of disconnects."""

    def __init__(self, handler: BaseHTTPRequestHandler) -> None:
        self._handler = handler
        self._started_s = time.monotonic()
        self._is_open = False
        self._is_gone = False

    def send(self, name: str, payload: BaseModel) -> None:
        """Write and flush one event; a gone client is remembered."""
        if self._is_gone:
            return
        try:
            self._open()
            self._handler.wfile.write(format_sse(name, payload))
            self._handler.wfile.flush()
        except OSError:  # BrokenPipe/ConnectionReset: the client left
            self._is_gone = True
            logger.info(LOG_CLIENT_GONE, self._handler.client_address)

    def send_step(self, event: StepEvent) -> None:
        """Write the ``step`` event of a pipeline step."""
        elapsed_s = time.monotonic() - self._started_s
        payload = StepPayload(
            step=event.step.value,
            label=STEP_LABELS[event.step],
            detail=event.detail,
            elapsed_s=round(elapsed_s, STEP_ELAPSED_DECIMALS),
        )
        self.send(EVENT_STEP, payload)

    def _open(self) -> None:
        if self._is_open:
            return
        self._is_open = True
        self._handler.send_response(200)
        self._handler.send_header(HEADER_CONTENT_TYPE, CONTENT_TYPE_SSE)
        self._handler.send_header(HEADER_CACHE_CONTROL, CACHE_NO_CACHE)
        self._handler.end_headers()


class _Handler(BaseHTTPRequestHandler):
    """Routes of the live server; ``context`` is set by the factory."""

    context: ServerContext

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.info(LOG_REQUEST, self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802
        """Serve the page, an evidence image or the health check."""
        path = urlsplit(self.path).path
        if path == ROUTE_INDEX:
            self._send_file(self.context.out_dir / INDEX_FILENAME)
        elif path == ROUTE_HEALTH:
            self._send_json(
                200, {KEY_READY: True, KEY_BUSY: self.context.ask.is_busy}
            )
        elif path.startswith(ROUTE_PAGES_PREFIX):
            name = unquote(path[len(ROUTE_PAGES_PREFIX) :])
            pages_dir = self.context.out_dir / PAGES_DIRNAME
            self._send_file(find_page_image(pages_dir, name))
        else:
            self._send_error(404, MSG_NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        """Answer a question as a stream of server-sent events."""
        if urlsplit(self.path).path != ROUTE_ASK:
            self._send_error(404, MSG_NOT_FOUND)
            return
        text = self._read_question()
        if text is not None:
            self._stream_answer(text)

    def _read_question(self) -> str | None:
        """The validated question, or None after an error reply."""
        try:
            length = int(self.headers.get(HEADER_CONTENT_LENGTH, ""))
        except ValueError:
            length = -1
        if length < 0:
            self._send_error(400, MSG_BAD_REQUEST)
            return None
        if length > MAX_BODY_BYTES:
            self._send_error(413, MSG_BODY_TOO_LARGE)
            return None
        try:
            body = AskRequest.model_validate_json(self.rfile.read(length))
        except ValidationError:
            self._send_error(400, MSG_BAD_REQUEST)
            return None
        problem = validate_question(body.question)
        if problem is not None:
            self._send_error(400, problem)
            return None
        return body.question.strip()

    def _stream_answer(self, text: str) -> None:
        stream = _EventStream(self)
        try:
            view = self.context.ask.ask(text, stream.send_step)
        except BusyError:
            self._send_error(409, MSG_BUSY)
            return
        except LlmUnavailableError as error:
            logger.warning(LOG_LLM_UNAVAILABLE, error)
            stream.send(EVENT_ERROR, ErrorPayload(message=MSG_LLM_UNAVAILABLE))
            return
        except Exception:  # noqa: BLE001 - boundary: report, keep serving
            logger.exception(LOG_ASK_FAILED)
            stream.send(EVENT_ERROR, ErrorPayload(message=MSG_UNEXPECTED))
            return
        _run_hook(self.context.on_result)
        stream.send(EVENT_RESULT, ResultPayload(question=view))

    def _send_file(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            self._send_error(404, MSG_NOT_FOUND)
            return
        mime = CONTENT_TYPE_HTML
        if path.suffix != HTML_SUFFIX:
            mime = mimetypes.guess_type(path.name)[0] or mime
        self._send_bytes(200, mime, path.read_bytes())

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode(ENCODING)
        self._send_bytes(status, CONTENT_TYPE_JSON, data)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {KEY_ERROR: message})

    def _send_bytes(self, status: int, mime: str, data: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header(HEADER_CONTENT_TYPE, mime)
            self.send_header(HEADER_CONTENT_LENGTH, str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            logger.info(LOG_CLIENT_GONE, self.client_address)


def _run_hook(hook: Callable[[], None]) -> None:
    try:
        hook()
    except Exception:  # noqa: BLE001 - a stale page must not fail the ask
        logger.exception(LOG_RESULT_HOOK_FAILED)


class _LocalServer(ThreadingHTTPServer):
    """Threaded server that refuses a port another process holds.

    On Windows SO_REUSEADDR would let a second server share the port.
    """

    allow_reuse_address = os.name != WINDOWS_OS_NAME


def create_server(port: int, context: ServerContext) -> ThreadingHTTPServer:
    """Bind ``127.0.0.1:port`` (0 = any free port) and return the server.

    Raises:
        OSError: the port cannot be bound (for example already in use).
    """
    handler = type("Handler", (_Handler,), {"context": context})
    return _LocalServer((HOST, port), handler)

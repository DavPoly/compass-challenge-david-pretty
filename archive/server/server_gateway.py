"""HTTP gateway of the live server: static files, health and ask."""

import json
import logging
import mimetypes
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import (
    BaseHTTPRequestHandler,
    HTTPServer,
    ThreadingHTTPServer,
)
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
    HEADER_HOST,
    HEADER_ORIGIN,
    HOST,
    HOST_FORMAT,
    HTML_SUFFIX,
    IMAGE_MIME_PREFIX,
    INDEX_FILENAME,
    JSON_MEDIA_TYPE,
    KEY_BUSY,
    KEY_ERROR,
    KEY_READY,
    LINGER_LIMIT_BYTES,
    LOCAL_HOST_NAMES,
    LOG_ASK_FAILED,
    LOG_BODY_NOT_READ,
    LOG_CLIENT_GONE,
    LOG_LLM_UNAVAILABLE,
    LOG_REQUEST,
    LOG_REQUEST_REFUSED,
    LOG_RESULT_HOOK_FAILED,
    MAX_BODY_BYTES,
    MAX_QUESTION_CHARS,
    MSG_BAD_REQUEST,
    MSG_BODY_TOO_LARGE,
    MSG_BUSY,
    MSG_EMPTY_QUESTION,
    MSG_FORBIDDEN,
    MSG_LLM_UNAVAILABLE,
    MSG_NOT_FOUND,
    MSG_QUESTION_TOO_LONG,
    MSG_UNEXPECTED,
    MSG_UNSUPPORTED_MEDIA_TYPE,
    ORIGIN_FORMAT,
    PAGES_DIRNAME,
    PARENT_REF,
    REQUEST_TIMEOUT_S,
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

    ``on_result`` runs right after each answered question is sent and
    must not block (it schedules the page rebuild).
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
        self._handler.send_response(HTTPStatus.OK)
        self._handler.send_header(HEADER_CONTENT_TYPE, CONTENT_TYPE_SSE)
        self._handler.send_header(HEADER_CACHE_CONTROL, CACHE_NO_CACHE)
        self._handler.end_headers()


class _Handler(BaseHTTPRequestHandler):
    """Routes of the live server; ``context`` is set by the factory."""

    context: ServerContext
    server: HTTPServer
    timeout = REQUEST_TIMEOUT_S

    def finish(self) -> None:
        """Flush the reply, then absorb what the client still sends.

        Closing with unread request bytes makes the OS reset the
        connection, which can discard the reply the client has not read.
        """
        super().finish()
        _discard_pending(self.connection)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        logger.info(LOG_REQUEST, self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802
        """Serve the page, an evidence image or the health check."""
        if not self._is_local_request():
            return
        path = urlsplit(self.path).path
        if path == ROUTE_INDEX:
            self._send_file(self.context.out_dir / INDEX_FILENAME)
        elif path == ROUTE_HEALTH:
            self._send_json(
                HTTPStatus.OK,
                {KEY_READY: True, KEY_BUSY: self.context.ask.is_busy},
            )
        elif path.startswith(ROUTE_PAGES_PREFIX):
            name = unquote(path[len(ROUTE_PAGES_PREFIX) :])
            pages_dir = self.context.out_dir / PAGES_DIRNAME
            self._send_file(find_page_image(pages_dir, name))
        else:
            self._send_error(HTTPStatus.NOT_FOUND, MSG_NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        """Answer a question as a stream of server-sent events."""
        if not self._is_local_request():
            return
        if urlsplit(self.path).path != ROUTE_ASK:
            self._send_error(HTTPStatus.NOT_FOUND, MSG_NOT_FOUND)
            return
        text = self._read_question()
        if text is not None:
            self._stream_answer(text)

    def _is_local_request(self) -> bool:
        """Whether Host and Origin name this server; else 403 sent.

        Refusing a foreign Host stops DNS rebinding; refusing a foreign
        Origin stops other sites from driving the server through the
        user's browser.
        """
        port = self.server.server_port
        hosts = {
            HOST_FORMAT.format(name=name, port=port)
            for name in LOCAL_HOST_NAMES
        }
        origins = {
            ORIGIN_FORMAT.format(name=name, port=port)
            for name in LOCAL_HOST_NAMES
        }
        host = self.headers.get(HEADER_HOST)
        origin = self.headers.get(HEADER_ORIGIN)
        host_ok = host is not None and host.lower() in hosts
        origin_ok = origin is None or origin.lower() in origins
        if host_ok and origin_ok:
            return True
        logger.warning(
            LOG_REQUEST_REFUSED, self.address_string(), host, origin
        )
        self._send_error(HTTPStatus.FORBIDDEN, MSG_FORBIDDEN)
        return False

    def _read_body(self) -> bytes | None:
        """The request body, or None after an error reply."""
        if self.headers.get_content_type() != JSON_MEDIA_TYPE:
            self._send_error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE, MSG_UNSUPPORTED_MEDIA_TYPE
            )
            return None
        try:
            length = int(self.headers.get(HEADER_CONTENT_LENGTH, ""))
        except ValueError:
            length = -1
        if length < 0:
            self._send_error(HTTPStatus.BAD_REQUEST, MSG_BAD_REQUEST)
            return None
        if length > MAX_BODY_BYTES:
            self._send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, MSG_BODY_TOO_LARGE
            )
            return None
        try:
            return self.rfile.read(length)
        except OSError as error:  # timeout or reset: the client stalled
            logger.info(LOG_BODY_NOT_READ, self.client_address, error)
            self.close_connection = True
            return None

    def _read_question(self) -> str | None:
        """The validated question, or None after an error reply."""
        raw = self._read_body()
        if raw is None:
            return None
        try:
            body = AskRequest.model_validate_json(raw)
        except ValidationError:
            self._send_error(HTTPStatus.BAD_REQUEST, MSG_BAD_REQUEST)
            return None
        problem = validate_question(body.question)
        if problem is not None:
            self._send_error(HTTPStatus.BAD_REQUEST, problem)
            return None
        return body.question.strip()

    def _stream_answer(self, text: str) -> None:
        stream = _EventStream(self)
        try:
            view = self.context.ask.ask(text, stream.send_step)
        except BusyError:
            self._send_error(HTTPStatus.CONFLICT, MSG_BUSY)
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
            self._send_error(HTTPStatus.NOT_FOUND, MSG_NOT_FOUND)
            return
        mime = CONTENT_TYPE_HTML
        if path.suffix != HTML_SUFFIX:
            mime = mimetypes.guess_type(path.name)[0] or mime
        self._send_bytes(HTTPStatus.OK, mime, path.read_bytes())

    def _send_json(
        self, status: HTTPStatus, payload: dict[str, object]
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode(ENCODING)
        self._send_bytes(status, CONTENT_TYPE_JSON, data)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {KEY_ERROR: message})

    def _send_bytes(self, status: HTTPStatus, mime: str, data: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header(HEADER_CONTENT_TYPE, mime)
            self.send_header(HEADER_CONTENT_LENGTH, str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            logger.info(LOG_CLIENT_GONE, self.client_address)


def _discard_pending(connection: socket.socket) -> None:
    """Half-close ``connection`` and drain a bounded amount of input."""
    try:
        connection.shutdown(socket.SHUT_WR)
        remaining = LINGER_LIMIT_BYTES
        while remaining > 0:
            chunk = connection.recv(remaining)
            if not chunk:
                return
            remaining -= len(chunk)
    except OSError:  # already closed or timed out: nothing left to save
        return


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

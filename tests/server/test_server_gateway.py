import http.client
import json
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from archive.common.step_model import PipelineStep, StepEvent
from archive.llm.llm_gateway import LlmUnavailableError
from archive.server import server_gateway
from archive.server.ask_service import BusyError
from archive.server.server_gateway import (
    ServerContext,
    create_server,
    find_page_image,
)
from archive.viewer.viewer_model import QuestionView

LONG_QUESTION = "x" * 501
BUSY_ERROR = (
    "Une question est déjà en cours de traitement. Réessayez dans un instant."
)
WAIT_S = 5
PNG_BYTES = b"\x89PNG"
HTTP_LINE_END = "\r\n"


def make_view() -> QuestionView:
    return QuestionView(
        id="live-001",
        question="Q ?",
        family=None,
        status="not_found",
        answer="Non trouvé",
        citations=[],
        confidence=None,
        confidence_reasons=[],
        ungrounded_values=[],
        dropped_citations=[],
        note=None,
        error=None,
        elapsed_s=1.0,
        is_correct=None,
        expected_answer=None,
        retrieved=[],
        evidence=[],
        is_live=True,
    )


class FakeAsk:
    def __init__(self) -> None:
        self.busy = False
        self.error: Exception | None = None
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    @property
    def is_busy(self) -> bool:
        return self.busy

    def ask(
        self, text: str, emit: Callable[[StepEvent], None]
    ) -> QuestionView:
        if self.busy:
            raise BusyError("busy")
        self.busy = True
        try:
            emit(StepEvent(PipelineStep.ROUTE, "factual"))
            self.entered.set()
            if self.gate is not None:
                self.gate.wait(timeout=WAIT_S)
            if self.error is not None:
                raise self.error
            emit(StepEvent(PipelineStep.RENDER))
            return make_view()
        finally:
            self.busy = False


class Running:
    def __init__(self, port: int, ask: FakeAsk) -> None:
        self.port = port
        self.ask = ask
        self.rebuilds = 0

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=WAIT_S
        )
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            return response.status, headers, response.read()
        finally:
            conn.close()

    def post(
        self, payload: object, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        return self.request(
            "POST",
            "/api/ask",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json", **(headers or {})},
        )


@pytest.fixture
def running(tmp_path: Path) -> Iterator[Running]:
    out_dir = tmp_path / "out"
    (out_dir / "pages").mkdir(parents=True)
    (out_dir / "index.html").write_text("<p>page é</p>", encoding="utf-8")
    (out_dir / "pages" / "a_crop.png").write_bytes(PNG_BYTES)
    (out_dir / "secret.png").write_bytes(b"secret")
    ask = FakeAsk()
    state = Running(0, ask)

    def on_result() -> None:
        state.rebuilds += 1

    server = create_server(0, ServerContext(ask, out_dir, on_result))
    state.port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=WAIT_S)


def parse_events(raw: bytes) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in raw.decode("utf-8").strip().split("\n\n"):
        name_line, data_line = block.split("\n")
        events.append(
            (
                name_line.removeprefix("event: "),
                json.loads(data_line.removeprefix("data: ")),
            )
        )
    return events


def test_index_is_served_as_html(running: Running) -> None:
    status, headers, body = running.request("GET", "/")

    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert body.decode("utf-8") == "<p>page é</p>"


def test_page_image_is_served(running: Running) -> None:
    status, headers, body = running.request("GET", "/pages/a_crop.png")

    assert (status, headers["content-type"], body) == (
        200,
        "image/png",
        PNG_BYTES,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/pages/../secret.png",
        "/pages/%2e%2e/secret.png",
        "/pages/..%2Fsecret.png",
        "/pages/..%5Csecret.png",
        "/pages/%2Fetc%2Fpasswd",
        "/pages/C:secret.png",
        "/pages/missing.png",
        "/pages/",
        "/other",
    ],
)
def test_unsafe_or_unknown_paths_are_404(running: Running, path: str) -> None:
    status, _, _ = running.request("GET", path)

    assert status == 404


def test_find_page_image_rejects_non_images(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    assert find_page_image(tmp_path, "notes.txt") is None


def test_health_reports_ready_and_not_busy(running: Running) -> None:
    status, _, body = running.request("GET", "/api/health")

    assert status == 200
    assert json.loads(body) == {"ready": True, "busy": False}


def test_ask_streams_steps_then_result(running: Running) -> None:
    status, headers, body = running.post({"question": " Q ? "})

    events = parse_events(body)
    assert status == 200
    assert headers["content-type"] == "text/event-stream"
    assert headers["cache-control"] == "no-cache"
    assert [name for name, _ in events] == ["step", "step", "result"]
    first = events[0][1]
    assert first["step"] == "route"
    assert first["label"] == "Routage de la question"
    assert first["detail"] == "factual"
    assert isinstance(first["elapsed_s"], float)
    assert events[1][1]["detail"] is None
    question = events[2][1]["question"]
    assert isinstance(question, dict)
    assert question["is_live"] is True
    assert running.rebuilds == 1


@pytest.mark.parametrize(
    "payload",
    [{"question": ""}, {"question": "  \n"}, {"question": LONG_QUESTION}],
)
def test_unusable_question_is_400_with_french_error(
    running: Running, payload: dict[str, str]
) -> None:
    status, _, body = running.post(payload)

    assert status == 400
    assert json.loads(body)["error"]


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"q": "x"}', b""])
def test_invalid_json_is_400(running: Running, body: bytes) -> None:
    status, _, _ = running.request(
        "POST", "/api/ask", body, {"Content-Type": "application/json"}
    )

    assert status == 400


def test_question_of_exactly_the_limit_is_accepted(
    running: Running,
) -> None:
    status, _, _ = running.post({"question": "x" * 500})

    assert status == 200


def test_oversized_body_is_413(running: Running) -> None:
    status, _, _ = running.post({"question": "x" * 9000})

    assert status == 413


def test_ask_while_busy_is_409(running: Running) -> None:
    gate = threading.Event()
    running.ask.gate = gate
    first: list[int] = []
    worker = threading.Thread(
        target=lambda: first.append(running.post({"question": "Q1"})[0])
    )
    worker.start()
    assert running.ask.entered.wait(timeout=WAIT_S)

    _, _, health = running.request("GET", "/api/health")
    status, _, body = running.post({"question": "Q2"})
    gate.set()
    worker.join(timeout=WAIT_S)

    assert json.loads(health)["busy"] is True
    assert status == 409
    assert json.loads(body)["error"] == BUSY_ERROR
    assert first == [200]


def test_llm_unavailable_becomes_an_error_event(running: Running) -> None:
    running.ask.error = LlmUnavailableError("down")

    status, _, body = running.post({"question": "Q"})

    events = parse_events(body)
    assert status == 200
    assert [name for name, _ in events] == ["step", "error"]
    assert "LLM_API_KEY" in str(events[1][1]["message"])
    assert running.rebuilds == 0


def test_unexpected_failure_hides_details(running: Running) -> None:
    running.ask.error = RuntimeError("secret detail")

    _, _, body = running.post({"question": "Q"})

    assert b"secret detail" not in body
    assert parse_events(body)[-1][0] == "error"


def test_server_survives_a_disconnect_mid_stream(running: Running) -> None:
    gate = threading.Event()
    running.ask.gate = gate
    conn = http.client.HTTPConnection(
        "127.0.0.1", running.port, timeout=WAIT_S
    )
    conn.request(
        "POST",
        "/api/ask",
        json.dumps({"question": "Q"}),
        {"Content-Type": "application/json"},
    )
    assert running.ask.entered.wait(timeout=WAIT_S)
    conn.close()
    gate.set()

    status, _, _ = running.request("GET", "/api/health")

    assert status == 200


def test_charset_parameter_on_the_json_content_type_is_accepted(
    running: Running,
) -> None:
    status, _, _ = running.post(
        {"question": "Q"},
        {"Content-Type": "application/json; charset=utf-8"},
    )

    assert status == 200


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/x-www-form-urlencoded", ""]
)
def test_non_json_content_type_is_415(
    running: Running, content_type: str
) -> None:
    status, _, body = running.post(
        {"question": "Q"}, {"Content-Type": content_type}
    )

    assert status == 415
    assert json.loads(body)["error"]
    assert running.rebuilds == 0


def test_missing_content_type_is_415(running: Running) -> None:
    body = json.dumps({"question": "Q"}).encode()

    status, _, _ = running.request("POST", "/api/ask", body)

    assert status == 415


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "null", "https://127.0.0.1:{port}"]
)
def test_foreign_origin_is_403(running: Running, origin: str) -> None:
    status, _, body = running.post(
        {"question": "Q"},
        {"Origin": origin.format(port=running.port)},
    )

    assert status == 403
    assert json.loads(body)["error"]
    assert running.rebuilds == 0


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:{port}", "http://localhost:{port}"]
)
def test_local_origin_is_accepted(running: Running, origin: str) -> None:
    status, _, _ = running.post(
        {"question": "Q"}, {"Origin": origin.format(port=running.port)}
    )

    assert status == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:{port}"])
@pytest.mark.parametrize("method_path", [("GET", "/"), ("GET", "/api/health")])
def test_foreign_host_is_403_on_every_route(
    running: Running, host: str, method_path: tuple[str, str]
) -> None:
    method, path = method_path

    status, _, _ = running.request(
        method, path, headers={"Host": host.format(port=running.port)}
    )

    assert status == 403


def test_foreign_host_cannot_ask(running: Running) -> None:
    status, _, _ = running.post({"question": "Q"}, {"Host": "evil.example"})

    assert status == 403


def test_localhost_host_is_accepted(running: Running) -> None:
    status, _, _ = running.request(
        "GET", "/api/health", headers={"Host": f"localhost:{running.port}"}
    )

    assert status == 200


def test_stalled_body_is_dropped_after_the_timeout(
    running: Running, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_gateway._Handler, "timeout", 0.3)
    sock = socket.create_connection(("127.0.0.1", running.port), WAIT_S)
    sock.settimeout(WAIT_S)
    request_head = (
        "POST /api/ask HTTP/1.1",
        f"Host: 127.0.0.1:{running.port}",
        "Content-Type: application/json",
        "Content-Length: 50",
        "",
        "{",
    )
    sock.sendall(HTTP_LINE_END.join(request_head).encode())
    try:
        reply = sock.recv(1024)
    finally:
        sock.close()

    status, _, _ = running.request("GET", "/api/health")
    assert reply == b""
    assert status == 200


def test_second_server_on_a_taken_port_fails(running: Running) -> None:
    context = ServerContext(running.ask, Path("."), lambda: None)

    with pytest.raises(OSError):
        create_server(running.port, context)

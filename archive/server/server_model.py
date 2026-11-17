"""Request and server-sent event shapes of the live server."""

from pydantic import BaseModel, ConfigDict

from archive.server.server_constants import ENCODING, SSE_FORMAT
from archive.viewer.viewer_model import QuestionView


class AskRequest(BaseModel):
    """Body of ``POST /api/ask``."""

    model_config = ConfigDict(extra="ignore")

    question: str


class StepPayload(BaseModel):
    """Data of a ``step`` event."""

    step: str
    label: str
    detail: str | None
    elapsed_s: float


class ResultPayload(BaseModel):
    """Data of the ``result`` event."""

    question: QuestionView


class ErrorPayload(BaseModel):
    """Data of the ``error`` event."""

    message: str


def format_sse(name: str, payload: BaseModel) -> bytes:
    """Encode one server-sent event block (``event:`` + ``data:``)."""
    block = SSE_FORMAT.format(name=name, data=payload.model_dump_json())
    return block.encode(ENCODING)

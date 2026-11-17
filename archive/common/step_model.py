"""Pipeline step events reported while a question is answered."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from archive.common.step_constants import LOG_STEP_CALLBACK_FAILED

logger = logging.getLogger(__name__)


class PipelineStep(StrEnum):
    """The stages a question goes through, in order."""

    ROUTE = "route"
    RETRIEVE = "retrieve"
    DRAFT = "draft"
    HOP = "hop"
    VALIDATE = "validate"
    GROUND = "ground"
    RENDER = "render"


@dataclass(frozen=True)
class StepEvent:
    """A stage that started or finished, with a short detail."""

    step: PipelineStep
    detail: str | None = None


StepCallback = Callable[[StepEvent], None]


def emit_step(
    on_step: StepCallback | None,
    step: PipelineStep,
    detail: str | None = None,
) -> None:
    """Report a step to the callback; a failing callback is ignored.

    Does nothing when ``on_step`` is None. Side effect: a callback
    exception is logged and swallowed so answering never breaks.
    """
    if on_step is None:
        return
    try:
        on_step(StepEvent(step, detail))
    except Exception:  # broad catch at a boundary: progress is optional
        logger.warning(LOG_STEP_CALLBACK_FAILED, step, exc_info=True)

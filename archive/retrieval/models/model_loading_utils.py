"""Run a model construction under a time budget."""

import logging
import threading
from collections.abc import Callable
from typing import TypeVar

from archive.retrieval.models.model_constants import (
    LOG_MODEL_FAILED,
    LOG_MODEL_TIMEOUT,
)

logger = logging.getLogger(__name__)

_Loaded = TypeVar("_Loaded")


def load_with_timeout(
    factory: Callable[[], _Loaded | None],
    model_name: str,
    timeout_s: float,
) -> _Loaded | None:
    """Build a model in a daemon thread, waiting at most ``timeout_s``.

    Args:
        factory: Builds and validates the model; may return None.
        model_name: Model name used in warnings.
        timeout_s: Maximum seconds to wait for ``factory``.

    Returns:
        The factory result, or None after one warning when the
        factory raises or does not finish in time. On timeout the
        daemon thread keeps running in the background.
    """
    outcome: list[_Loaded | None] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            outcome.append(factory())
        except Exception as error:  # noqa: BLE001 - best-effort load
            errors.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        logger.warning(LOG_MODEL_TIMEOUT, model_name, timeout_s)
        return None
    if errors:
        logger.warning(LOG_MODEL_FAILED, model_name, errors[0])
        return None
    return outcome[0] if outcome else None

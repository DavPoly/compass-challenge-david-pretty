"""Rebuild the page in the background without ever blocking a reply."""

import logging
import threading
from collections.abc import Callable

from archive.server.server_constants import LOG_REBUILD_FAILED

logger = logging.getLogger(__name__)


class RebuildScheduler:
    """Runs ``rebuild`` on a worker thread, one run at a time.

    Requests made while a run is in progress are coalesced into a
    single extra run afterwards, so the page always ends up reflecting
    the latest question. A failing rebuild is logged, never raised.
    """

    def __init__(self, rebuild: Callable[[], None]) -> None:
        self._rebuild = rebuild
        self._lock = threading.Lock()
        self._is_running = False
        self._is_dirty = False

    def request(self) -> None:
        """Ask for a rebuild and return at once."""
        with self._lock:
            if self._is_running:
                self._is_dirty = True
                return
            self._is_running = True
        threading.Thread(target=self._run_until_clean, daemon=True).start()

    def _run_until_clean(self) -> None:
        while True:
            try:
                self._rebuild()
            except Exception:  # noqa: BLE001 - keep serving the old page
                logger.exception(LOG_REBUILD_FAILED)
            with self._lock:
                if not self._is_dirty:
                    self._is_running = False
                    return
                self._is_dirty = False

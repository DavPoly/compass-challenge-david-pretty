import logging
import threading

import pytest

from archive.server.rebuild_service import RebuildScheduler

WAIT_S = 5


class Recorder:
    """A rebuild that counts runs and can be held open."""

    def __init__(self) -> None:
        self.runs = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.second_done = threading.Event()
        self.error: Exception | None = None

    def __call__(self) -> None:
        self.runs += 1
        self.entered.set()
        if self.runs == 1:
            assert self.release.wait(timeout=WAIT_S)
        else:
            self.second_done.set()
        if self.error is not None:
            raise self.error


def test_request_returns_while_the_rebuild_is_still_running() -> None:
    rebuild = Recorder()
    scheduler = RebuildScheduler(rebuild)

    scheduler.request()

    assert rebuild.entered.wait(timeout=WAIT_S)
    assert rebuild.runs == 1
    rebuild.release.set()


def test_requests_during_a_run_coalesce_into_one_more_run() -> None:
    rebuild = Recorder()
    scheduler = RebuildScheduler(rebuild)
    scheduler.request()
    assert rebuild.entered.wait(timeout=WAIT_S)

    scheduler.request()
    scheduler.request()
    scheduler.request()
    rebuild.release.set()

    assert rebuild.second_done.wait(timeout=WAIT_S)
    assert rebuild.runs == 2


def test_failed_rebuild_is_logged_and_the_next_one_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rebuild = Recorder()
    rebuild.error = RuntimeError("disk full")
    scheduler = RebuildScheduler(rebuild)
    scheduler.request()
    assert rebuild.entered.wait(timeout=WAIT_S)
    scheduler.request()

    with caplog.at_level(logging.ERROR):
        rebuild.release.set()
        assert rebuild.second_done.wait(timeout=WAIT_S)

    assert "page rebuild failed" in caplog.text

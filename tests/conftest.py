"""Shared test fixtures."""

import os
from pathlib import Path

import pytest

DEFAULT_TEST_CORPUS = "C:/Users/david/Dev/compass-challenge-kit/corpus"


@pytest.fixture(scope="session")
def kit_corpus_dir() -> Path:
    """Kit corpus directory, or skip when it is missing."""
    path = Path(os.environ.get("ARCHIVE_TEST_CORPUS", DEFAULT_TEST_CORPUS))
    if not path.is_dir():
        pytest.skip(f"corpus not found at {path}; set ARCHIVE_TEST_CORPUS")
    return path

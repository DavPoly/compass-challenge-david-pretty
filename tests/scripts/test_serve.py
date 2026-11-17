import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from archive.common.config import AppConfig
from archive.ingest.build.manifest_gateway import ManifestError
from archive.pipeline.engine.engine_service import Engine
from archive.pipeline.pipeline_constants import EXIT_ERROR
from archive.retrieval.qdrant.qdrant_gateway import IndexOpenError
from scripts import serve

ENV_VARS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


@pytest.fixture
def llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.setenv(name, "dummy")


@pytest.fixture(autouse=True)
def no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object) -> None:
        raise AssertionError("the engine must not be opened")

    monkeypatch.setattr(serve, "open_engine", refuse)


def test_missing_env_exits_one_with_the_variables(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    code = serve.main(["--corpus", str(tmp_path)])

    assert code == EXIT_ERROR
    assert "Missing environment variables: LLM_BASE_URL" in (
        capsys.readouterr().err
    )


def test_corpus_without_pdf_exits_one(
    llm_env: None, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    code = serve.main(["--corpus", str(tmp_path)])

    assert code == EXIT_ERROR
    assert "No PDF found in corpus directory" in caplog.text


def test_missing_run_directory_exits_one(
    llm_env: None, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF")

    code = serve.main(
        ["--corpus", str(tmp_path), "--run", str(tmp_path / "nope")]
    )

    assert code == EXIT_ERROR
    assert "omit --run" in caplog.text


def llm_corpus(tmp_path: Path) -> Path:
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    return tmp_path


@pytest.mark.parametrize(
    "error",
    [
        OSError("disk unreadable"),
        IndexOpenError("locked"),
        ManifestError("bad manifest"),
    ],
)
def test_engine_startup_failure_exits_one_without_traceback(
    llm_env: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    error: Exception,
) -> None:
    @contextlib.contextmanager
    def broken_open(config: AppConfig) -> Iterator[Engine]:
        raise error
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(serve, "open_engine", broken_open)

    code = serve.main(["--corpus", str(llm_corpus(tmp_path))])

    assert code == EXIT_ERROR
    assert "Cannot open the index" in caplog.text
    assert str(error) in caplog.text
    assert not any(record.exc_info for record in caplog.records)

from pathlib import Path

import pytest

from archive.pipeline.pipeline_constants import EXIT_ERROR
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

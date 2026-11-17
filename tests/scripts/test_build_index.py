import shutil
from pathlib import Path

import pytest

from archive.ingest.build.index_builder_service import BuildReport
from archive.pipeline.pipeline_constants import EXIT_ERROR, EXIT_OK
from scripts import build_index

FAKE_SIZE_MB = 42.5
PDF_COUNT = 1


class StubEmbedder:
    dim = 8


@pytest.fixture
def corpus(kit_corpus_dir: Path, tmp_path: Path) -> Path:
    directory = tmp_path / "corpus"
    directory.mkdir()
    first_pdf = sorted(kit_corpus_dir.glob("*.pdf"))[0]
    shutil.copy(first_pdf, directory / first_pdf.name)
    return directory


@pytest.fixture
def recorded_build(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Replace the build by a recorder of its embedder argument."""
    embedders: list[object] = []

    def fake_build(
        corpus_dir: Path,
        index_dir: Path,
        workers: int | None = None,
        embedder: object = None,
    ) -> BuildReport:
        embedders.append(embedder)
        return BuildReport(PDF_COUNT, PDF_COUNT, [], 0.1)

    monkeypatch.setattr(build_index, "build", fake_build)
    monkeypatch.setattr(build_index, "storage_size_mb", lambda _: FAKE_SIZE_MB)
    return embedders


def run_main(corpus: Path, tmp_path: Path, *extra: str) -> int:
    return build_index.main(
        ["--corpus", str(corpus), "--index", str(tmp_path / "i"), *extra]
    )


def test_missing_embedder_fails_without_building(
    corpus: Path,
    tmp_path: Path,
    recorded_build: list[object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(build_index, "load_embedder", lambda timeout_s: None)
    assert run_main(corpus, tmp_path) == EXIT_ERROR
    assert "--sparse-only" in capsys.readouterr().err
    assert recorded_build == []


def test_sparse_only_builds_without_loading_the_model(
    corpus: Path,
    tmp_path: Path,
    recorded_build: list[object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(timeout_s: float) -> None:
        raise AssertionError("the model must not be loaded")

    monkeypatch.setattr(build_index, "load_embedder", forbidden)
    assert run_main(corpus, tmp_path, "--sparse-only") == EXIT_OK
    assert recorded_build == [None]
    assert "42.5 MB" in capsys.readouterr().out


def test_loaded_embedder_is_passed_to_the_build(
    corpus: Path,
    tmp_path: Path,
    recorded_build: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = StubEmbedder()
    monkeypatch.setattr(build_index, "load_embedder", lambda _: embedder)
    assert run_main(corpus, tmp_path) == EXIT_OK
    assert recorded_build == [embedder]


def test_size_at_limit_warns_on_stderr(
    corpus: Path,
    tmp_path: Path,
    recorded_build: list[object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(build_index, "STORAGE_SIZE_LIMIT_MB", FAKE_SIZE_MB)
    assert run_main(corpus, tmp_path, "--sparse-only") == EXIT_OK
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "WARNING" not in captured.out


def test_size_below_limit_does_not_warn(
    corpus: Path,
    tmp_path: Path,
    recorded_build: list[object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_main(corpus, tmp_path, "--sparse-only") == EXIT_OK
    assert "WARNING" not in capsys.readouterr().err


def test_storage_size_sums_sqlite_files(tmp_path: Path) -> None:
    storage = tmp_path / "qdrant" / "collection"
    storage.mkdir(parents=True)
    (storage / "storage.sqlite").write_bytes(b"x" * 1024 * 1024)
    assert build_index.storage_size_mb(tmp_path) == pytest.approx(1.0)

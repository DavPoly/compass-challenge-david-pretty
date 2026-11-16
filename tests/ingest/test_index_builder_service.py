import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from archive.ingest import index_builder_service
from archive.ingest.index_builder_service import (
    IndexBuildError,
    ManifestError,
    _clear_previous_index,
    _parse_file,
    build,
    load_manifest,
)
from archive.retrieval.search_service import SearchFilters, SearchService

DOC_COUNT = 4
WORKERS = 2
LIST_CAP = 1000


@pytest.fixture
def mini_corpus(kit_corpus_dir: Path, tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for path in sorted(kit_corpus_dir.glob("*.pdf"))[:DOC_COUNT]:
        shutil.copy(path, corpus / path.name)
    return corpus


def count_chunks(index_dir: Path) -> int:
    with SearchService.open(index_dir) as service:
        return len(service.list_by_filter(SearchFilters(), LIST_CAP))


def test_build_indexes_documents_and_writes_manifest(
    mini_corpus: Path, tmp_path: Path
) -> None:
    index_dir = tmp_path / "index"
    report = build(mini_corpus, index_dir, WORKERS)
    manifest = load_manifest(index_dir)
    assert report.docs == DOC_COUNT == len(manifest)
    assert report.failed_docs == []
    assert report.chunks >= DOC_COUNT
    assert list(manifest) == sorted(manifest)
    assert all(set(entry) == {"size", "sha1"} for entry in manifest.values())
    assert count_chunks(index_dir) == report.chunks


def test_rebuild_replaces_previous_index(
    mini_corpus: Path, tmp_path: Path
) -> None:
    index_dir = tmp_path / "index"
    build(mini_corpus, index_dir, WORKERS)
    report = build(mini_corpus, index_dir, WORKERS)
    assert count_chunks(index_dir) == report.chunks


def test_unreadable_pdf_is_skipped_and_counted(
    mini_corpus: Path, tmp_path: Path
) -> None:
    (mini_corpus / "broken.pdf").write_bytes(b"not a pdf")
    index_dir = tmp_path / "index"
    report = build(mini_corpus, index_dir, WORKERS)
    assert report.failed_docs == ["broken"]
    assert report.docs == DOC_COUNT
    assert "broken" not in load_manifest(index_dir)


def test_load_manifest_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="build_index"):
        load_manifest(tmp_path)


def test_load_manifest_invalid_json_raises(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{oops")
    with pytest.raises(ManifestError):
        load_manifest(tmp_path)


def test_load_manifest_roundtrip(tmp_path: Path) -> None:
    expected = {"doc_1": {"size": 3, "sha1": "ab"}}
    (tmp_path / "manifest.json").write_text(json.dumps(expected))
    assert load_manifest(tmp_path) == expected


def test_rebuild_failure_to_clear_leaves_no_manifest(
    mini_corpus: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = tmp_path / "index"
    build(mini_corpus, index_dir, WORKERS)

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(index_builder_service.shutil, "rmtree", refuse)
    with pytest.raises(IndexBuildError, match="previous index"):
        build(mini_corpus, index_dir, WORKERS)
    assert not (index_dir / "manifest.json").exists()


def test_aborted_build_leaves_no_manifest(
    mini_corpus: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = tmp_path / "index"
    build(mini_corpus, index_dir, WORKERS)

    def abort(*_args: Any, **_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(index_builder_service, "_parse_all", abort)
    with pytest.raises(KeyboardInterrupt):
        build(mini_corpus, index_dir, WORKERS)
    assert not (index_dir / "manifest.json").exists()


def test_clear_previous_index_handles_missing_storage(
    tmp_path: Path,
) -> None:
    (tmp_path / "manifest.json").write_text("{}")
    _clear_previous_index(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_unexpected_worker_error_is_a_counted_failure(
    mini_corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(index_builder_service, "chunk_document", explode)
    path = sorted(mini_corpus.glob("*.pdf"))[0]
    parsed = _parse_file(path)
    assert parsed.entry is None
    assert parsed.doc_id == path.stem
    assert parsed.error == "ValueError: boom"

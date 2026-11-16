import json
import shutil
from pathlib import Path

import pytest

from archive.ingest.index_builder_service import (
    ManifestError,
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

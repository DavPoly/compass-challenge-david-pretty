import json
import shutil
from pathlib import Path

import pytest

from archive.common.chunk_model import Chunk, ChunkKind
from archive.ingest.build import index_builder_service, index_sync_service
from archive.ingest.build.index_builder_service import build
from archive.ingest.build.index_sync_service import (
    _refresh_series,
    sync_index,
)
from archive.ingest.build.manifest_gateway import load_manifest
from archive.retrieval.qdrant.qdrant_gateway import QdrantGateway
from archive.retrieval.search_service import SearchFilters, SearchService

BASE_DOCS = 3
WORKERS = 2
LIST_CAP = 1000


@pytest.fixture(scope="module")
def base(
    kit_corpus_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path, list[Path]]:
    root = tmp_path_factory.mktemp("sync_base")
    pdfs = sorted(kit_corpus_dir.glob("*.pdf"))[: BASE_DOCS + 1]
    corpus = root / "corpus"
    corpus.mkdir()
    for path in pdfs[:BASE_DOCS]:
        shutil.copy(path, corpus)
    build(corpus, root / "index", WORKERS)
    return corpus, root / "index", pdfs


@pytest.fixture
def synced(
    base: tuple[Path, Path, list[Path]], tmp_path: Path
) -> tuple[Path, Path, list[Path]]:
    corpus, index, pdfs = base
    shutil.copytree(corpus, tmp_path / "corpus")
    shutil.copytree(index, tmp_path / "index")
    return tmp_path / "corpus", tmp_path / "index", pdfs


def doc_ids(index_dir: Path) -> set[str]:
    with SearchService.open(index_dir) as service:
        hits = service.list_by_filter(SearchFilters(), LIST_CAP)
    return {hit.chunk.doc_id for hit in hits}


def test_added_pdf_is_indexed(
    synced: tuple[Path, Path, list[Path]],
) -> None:
    corpus, index, pdfs = synced
    shutil.copy(pdfs[BASE_DOCS], corpus)
    report = sync_index(corpus, index, WORKERS)
    assert report.added == [pdfs[BASE_DOCS].stem]
    assert report.changed == report.removed == report.failed == []
    assert (
        doc_ids(index)
        == set(load_manifest(index))
        == {path.stem for path in corpus.glob("*.pdf")}
    )


def test_changed_pdf_is_reparsed(
    synced: tuple[Path, Path, list[Path]],
) -> None:
    corpus, index, pdfs = synced
    target = corpus / pdfs[0].name
    shutil.copy(pdfs[BASE_DOCS], target)
    report = sync_index(corpus, index, WORKERS)
    assert report.changed == [pdfs[0].stem]
    assert report.added == report.removed == []
    assert (
        load_manifest(index)[pdfs[0].stem]["sha1"]
        != (index_builder_service.file_entry(pdfs[0])["sha1"])
    )
    assert pdfs[0].stem in doc_ids(index)


def test_removed_pdf_is_dropped(
    synced: tuple[Path, Path, list[Path]],
) -> None:
    corpus, index, pdfs = synced
    (corpus / pdfs[0].name).unlink()
    report = sync_index(corpus, index, WORKERS)
    assert report.removed == [pdfs[0].stem]
    assert pdfs[0].stem not in doc_ids(index)
    assert pdfs[0].stem not in load_manifest(index)


def test_unchanged_corpus_touches_nothing(
    synced: tuple[Path, Path, list[Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus, index, _ = synced

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("sync must not touch Qdrant or the pool")

    monkeypatch.setattr(QdrantGateway, "open", forbidden)
    monkeypatch.setattr(index_sync_service, "parse_all", forbidden)
    report = sync_index(corpus, index, WORKERS)
    assert not (
        report.added or report.changed or report.removed or report.failed
    )


def test_unparsable_pdf_is_reported_and_retried(
    synced: tuple[Path, Path, list[Path]],
) -> None:
    corpus, index, _ = synced
    (corpus / "broken.pdf").write_bytes(b"not a pdf")
    first = sync_index(corpus, index, WORKERS)
    assert first.failed == ["broken"]
    assert "broken" not in load_manifest(index)
    assert sync_index(corpus, index, WORKERS).failed == ["broken"]


def test_missing_manifest_runs_full_build(
    synced: tuple[Path, Path, list[Path]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    corpus, index, _ = synced
    (index / "manifest.json").unlink()
    report = sync_index(corpus, index, WORKERS)
    assert sorted(report.added) == sorted(load_manifest(index))
    assert len(report.added) == BASE_DOCS
    assert "full build" in caplog.text


def test_missing_index_runs_full_build(
    synced: tuple[Path, Path, list[Path]], tmp_path: Path
) -> None:
    corpus, _, _ = synced
    report = sync_index(corpus, tmp_path / "fresh", WORKERS)
    assert len(report.added) == BASE_DOCS


def series_chunk(chunk_id: str, effective_from: str) -> Chunk:
    return Chunk(
        doc_id=chunk_id.split("#", maxsplit=1)[0],
        chunk_id=chunk_id,
        chunk_kind=ChunkKind.TEXT,
        doc_type="policy",
        doc_date=None,
        identifiers=[],
        lang="fr",
        text=chunk_id,
        series="leave",
        version="1",
        effective_from=effective_from,
    )


def test_refresh_series_recomputes_stored_chunks(tmp_path: Path) -> None:
    gateway = QdrantGateway.open(tmp_path)
    try:
        gateway.ensure_collection()
        gateway.upsert(
            [
                series_chunk("a#0", "2023-01-01"),
                series_chunk("b#0", "2024-01-01"),
            ]
        )
        _refresh_series(gateway)
        ends = {c.chunk_id: c.effective_to for c in gateway.scroll_series()}
    finally:
        gateway.close()
    assert ends == {"a#0": "2024-01-01", "b#0": None}


def test_orphan_chunks_of_unlisted_doc_are_deleted(
    synced: tuple[Path, Path, list[Path]],
) -> None:
    corpus, index, pdfs = synced
    doc_id = pdfs[0].stem
    manifest_path = index / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest[doc_id]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    orphan_id = f"{doc_id}#orphan"
    gateway = QdrantGateway.open(index)
    try:
        gateway.upsert([series_chunk(orphan_id, "2023-01-01")])
    finally:
        gateway.close()
    report = sync_index(corpus, index, WORKERS)
    assert report.added == [doc_id]
    with SearchService.open(index) as service:
        hits = service.list_by_filter(SearchFilters(), LIST_CAP)
    assert orphan_id not in {hit.chunk.chunk_id for hit in hits}


def test_removing_latest_version_resets_previous_effective_to(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    index = tmp_path / "index"
    gateway = QdrantGateway.open(index)
    try:
        gateway.ensure_collection()
        gateway.upsert(
            [
                series_chunk("a#0", "2023-01-01").model_copy(
                    update={"effective_to": "2024-01-01"}
                ),
                series_chunk("b#0", "2024-01-01"),
            ]
        )
        index_sync_service._drop_stale(gateway, index, ["b"], {"b": {}})  # type: ignore[typeddict-item]
        ends = {c.chunk_id: c.effective_to for c in gateway.scroll_series()}
    finally:
        gateway.close()
    assert ends == {"a#0": None}

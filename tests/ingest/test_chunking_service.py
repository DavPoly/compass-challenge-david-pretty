"""Tests for document chunking."""

from archive.common.chunk_model import Chunk, ChunkKind
from archive.ingest.chunking_service import chunk_document
from archive.ingest.metadata.metadata_service import DocMetadata
from archive.ingest.parse.pdf_parse_gateway import ParsedDoc

METADATA = DocMetadata(
    doc_type="unknown",
    doc_date="2024-03-12",
    identifiers=["BRV-2023-06"],
    lang="en",
)


def _words(count: int, start: int = 0) -> str:
    return " ".join(f"w{number}" for number in range(start, start + count))


def _chunk(text: str) -> list[Chunk]:
    return chunk_document(ParsedDoc("doc_1", [text]), METADATA)


def test_empty_doc_gives_no_chunk() -> None:
    assert chunk_document(ParsedDoc("d", []), METADATA) == []
    assert chunk_document(ParsedDoc("d", ["", " \n "]), METADATA) == []


def test_short_doc_is_one_chunk_with_metadata() -> None:
    chunks = _chunk("Bonjour\u00a0le  monde")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_id == "doc_1#0"
    assert chunk.doc_id == "doc_1"
    assert chunk.chunk_kind == ChunkKind.TEXT
    assert chunk.text == "Bonjour le monde"
    assert chunk.doc_date == "2024-03-12"
    assert chunk.identifiers == ["BRV-2023-06"]
    assert chunk.lang == "en"
    assert chunk.version is None
    assert chunk.effective_from is None
    assert chunk.effective_to is None


def test_doc_exactly_at_threshold_stays_one_chunk() -> None:
    assert len(_chunk(_words(800))) == 1


def test_doc_just_over_threshold_is_split() -> None:
    chunks = _chunk(_words(801))

    assert len(chunks) > 1
    assert chunks[-1].text.endswith("w800")


def test_chunks_overlap_by_fifty_words_without_paragraphs() -> None:
    chunks = _chunk(_words(1000))

    first = chunks[0].text.split()
    second = chunks[1].text.split()
    assert len(first) == 400
    assert first[-50:] == second[:50]
    assert second[0] == "w350"


def test_every_word_is_covered_and_ids_are_sequential() -> None:
    chunks = _chunk(_words(2000))

    assert [chunk.chunk_id for chunk in chunks] == [
        f"doc_1#{index}" for index in range(len(chunks))
    ]
    covered = {word for chunk in chunks for word in chunk.text.split()}
    assert covered == set(_words(2000).split())


def test_chunk_breaks_at_paragraph_near_window_end() -> None:
    text = _words(380) + "\n\n" + _words(600, start=380)

    chunks = _chunk(text)

    assert chunks[0].text.split()[-1] == "w379"
    assert chunks[1].text.split()[0] == "w330"


def test_paragraph_outside_snap_zone_is_ignored() -> None:
    text = _words(100) + "\n\n" + _words(900, start=100)

    chunks = _chunk(text)

    assert len(chunks[0].text.split()) == 400


def test_pages_are_joined_as_paragraphs() -> None:
    doc = ParsedDoc("d", [_words(380), _words(600, start=380)])

    chunks = chunk_document(doc, METADATA)

    assert chunks[0].text.split()[-1] == "w379"


def test_chunk_identifiers_are_independent_copies() -> None:
    chunks = _chunk(_words(900))

    chunks[0].identifiers.append("x")

    assert METADATA.identifiers == ["BRV-2023-06"]
    assert chunks[1].identifiers == ["BRV-2023-06"]


def test_version_fields_are_copied_onto_every_chunk() -> None:
    metadata = DocMetadata(
        doc_type="policy",
        doc_date="2024-05-26",
        identifiers=[],
        lang="fr",
        version="3",
        effective_from="2024-05-26",
        series="politique de teletravail",
    )

    chunks = chunk_document(ParsedDoc("doc_1", [_words(1000)]), metadata)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.version == "3"
        assert chunk.effective_from == "2024-05-26"
        assert chunk.series == "politique de teletravail"
        assert chunk.effective_to is None

from archive.common.chunk_model import Chunk, ChunkKind
from archive.ingest.build.version_series_utils import with_effective_to


def make_chunk(
    chunk_id: str,
    series: str | None = "leave",
    version: str | None = "1",
    effective_from: str | None = "2023-01-01",
) -> Chunk:
    return Chunk(
        doc_id=chunk_id.split("#", maxsplit=1)[0],
        chunk_id=chunk_id,
        chunk_kind=ChunkKind.TEXT,
        doc_type="policy",
        doc_date=None,
        identifiers=[],
        lang="fr",
        text="text",
        series=series,
        version=version,
        effective_from=effective_from,
    )


def ends(chunks: list[Chunk]) -> dict[str, str | None]:
    return {chunk.chunk_id: chunk.effective_to for chunk in chunks}


def test_unsorted_versions_get_next_effective_from() -> None:
    result = with_effective_to(
        [
            make_chunk("c#0", version="3", effective_from="2025-01-01"),
            make_chunk("a#0", version="1", effective_from="2023-01-01"),
            make_chunk("b#0", version="2", effective_from="2024-01-01"),
        ]
    )
    assert ends(result) == {
        "c#0": None,
        "a#0": "2024-01-01",
        "b#0": "2025-01-01",
    }
    assert [chunk.chunk_id for chunk in result] == ["c#0", "a#0", "b#0"]


def test_single_version_has_no_end() -> None:
    assert ends(with_effective_to([make_chunk("a#0")])) == {"a#0": None}


def test_chunks_of_one_version_share_the_end() -> None:
    result = with_effective_to(
        [
            make_chunk("a#0"),
            make_chunk("a#1"),
            make_chunk("b#0", version="2", effective_from="2024-01-01"),
        ]
    )
    assert ends(result)["a#0"] == ends(result)["a#1"] == "2024-01-01"


def test_same_date_versions_share_the_next_end() -> None:
    result = with_effective_to(
        [
            make_chunk("a#0", version="1"),
            make_chunk("b#0", version="2"),
            make_chunk("c#0", version="3", effective_from="2024-01-01"),
        ]
    )
    assert ends(result) == {
        "a#0": "2024-01-01",
        "b#0": "2024-01-01",
        "c#0": None,
    }


def test_series_are_independent() -> None:
    result = with_effective_to(
        [
            make_chunk("a#0", series="leave"),
            make_chunk("b#0", series="travel", effective_from="2024-01-01"),
        ]
    )
    assert ends(result) == {"a#0": None, "b#0": None}


def test_chunks_without_series_or_date_are_unchanged() -> None:
    plain = make_chunk("p#0", series=None)
    undated = make_chunk("u#0", effective_from=None)
    result = with_effective_to([plain, undated, make_chunk("a#0")])
    assert result[0] is plain
    assert result[1] is undated


def test_input_is_not_mutated() -> None:
    first = make_chunk("a#0")
    with_effective_to([first, make_chunk("b#0", effective_from="2024-01-01")])
    assert first.effective_to is None

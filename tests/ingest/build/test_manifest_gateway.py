from pathlib import Path

from archive.ingest.build.build_constants import (
    MANIFEST_FILE_NAME,
    MANIFEST_TMP_SUFFIX,
)
from archive.ingest.build.manifest_gateway import (
    ManifestEntry,
    file_entry,
    load_manifest,
    write_manifest,
)

EXPECTED_SIZE = 5
EXPECTED_SHA1 = "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"


def test_write_manifest_round_trips_and_leaves_no_tmp(
    tmp_path: Path,
) -> None:
    index_dir = tmp_path / "index"
    manifest = {"doc": ManifestEntry(size=1, sha1="abc")}

    write_manifest(index_dir, manifest)

    assert load_manifest(index_dir) == manifest
    assert not (
        index_dir / (MANIFEST_FILE_NAME + MANIFEST_TMP_SUFFIX)
    ).exists()


def test_write_manifest_replaces_previous_content(tmp_path: Path) -> None:
    write_manifest(tmp_path, {"old": ManifestEntry(size=1, sha1="a")})
    write_manifest(tmp_path, {"new": ManifestEntry(size=2, sha1="b")})

    assert list(load_manifest(tmp_path)) == ["new"]
    assert [path.name for path in tmp_path.iterdir()] == [MANIFEST_FILE_NAME]


def test_file_entry_hashes_size_and_content(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"hello")

    assert file_entry(path) == {"size": EXPECTED_SIZE, "sha1": EXPECTED_SHA1}

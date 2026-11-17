"""Read and write the index manifest (`manifest.json`)."""

import hashlib
import json
import os
from pathlib import Path
from typing import TypedDict

from archive.ingest.build.build_constants import (
    FILE_HASH_BLOCK_BYTES,
    MANIFEST_FILE_NAME,
    MANIFEST_INDENT,
    MANIFEST_TMP_SUFFIX,
)


class ManifestError(Exception):
    """Raised when the index manifest is missing or invalid."""


class ManifestEntry(TypedDict):
    """Size in bytes and SHA-1 of an indexed PDF."""

    size: int
    sha1: str


def load_manifest(index_dir: Path) -> dict[str, ManifestEntry]:
    """Read `<index_dir>/manifest.json`.

    Raises:
        ManifestError: if the file is missing or not valid JSON.
    """
    path = index_dir / MANIFEST_FILE_NAME
    try:
        content = path.read_text(encoding="utf-8")
        manifest: dict[str, ManifestEntry] = json.loads(content)
    except (OSError, ValueError) as error:
        raise ManifestError(
            f"Cannot read the index manifest {path}: {error}. Build the "
            "index with scripts/build_index.py."
        ) from error
    return manifest


def write_manifest(
    index_dir: Path, manifest: dict[str, ManifestEntry]
) -> None:
    """Write `<index_dir>/manifest.json` atomically.

    The content goes to a temporary sibling file that then replaces the
    manifest, so a reader never sees a partial file.

    Args:
        index_dir: Index directory; created when missing.
        manifest: Entries keyed by doc id.

    Raises:
        OSError: if the file cannot be written or replaced.
    """
    index_dir.mkdir(parents=True, exist_ok=True)
    target = index_dir / MANIFEST_FILE_NAME
    temporary = target.with_name(target.name + MANIFEST_TMP_SUFFIX)
    temporary.write_text(
        json.dumps(manifest, sort_keys=True, indent=MANIFEST_INDENT) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def file_entry(path: Path) -> ManifestEntry:
    """Return the size and SHA-1 of a file."""
    digest = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as handle:
        while block := handle.read(FILE_HASH_BLOCK_BYTES):
            digest.update(block)
    return ManifestEntry(size=path.stat().st_size, sha1=digest.hexdigest())

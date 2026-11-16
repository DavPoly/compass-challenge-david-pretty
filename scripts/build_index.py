"""CLI: build the committed index from a corpus directory."""

import argparse
import logging
import sys
from pathlib import Path

# Allow `python scripts/build_index.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.common.constants import (  # noqa: E402
    CORPUS_DIR_NAME,
    INDEX_DIR_NAME,
    PDF_GLOB,
    REPO_ROOT,
)
from archive.ingest.index_builder_service import build  # noqa: E402
from archive.pipeline.pipeline_constants import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
)
from archive.retrieval.qdrant_constants import QDRANT_SUBDIR  # noqa: E402

logger = logging.getLogger("build_index")
SQLITE_NAME = "storage.sqlite"
BYTES_PER_MB = 1024 * 1024


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, default=REPO_ROOT / CORPUS_DIR_NAME
    )
    parser.add_argument(
        "--index", type=Path, default=REPO_ROOT / INDEX_DIR_NAME
    )
    parser.add_argument("--workers", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build the index; return the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    if not any(args.corpus.glob(PDF_GLOB)):
        logger.error(
            "No PDFs found in %s. Pass --corpus with the PDF directory.",
            args.corpus,
        )
        return EXIT_ERROR
    report = build(args.corpus, args.index, args.workers)
    sizes = [
        path.stat().st_size
        for path in (args.index / QDRANT_SUBDIR).rglob(SQLITE_NAME)
    ]
    logger.info(
        "docs=%d chunks=%d failures=%d seconds=%.1f sqlite_mb=%.1f",
        report.docs,
        report.chunks,
        len(report.failed_docs),
        report.seconds,
        sum(sizes) / BYTES_PER_MB,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

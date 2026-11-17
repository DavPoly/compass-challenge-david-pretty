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
from archive.ingest.build.index_builder_service import build  # noqa: E402
from archive.pipeline.pipeline_constants import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
)
from archive.retrieval.models.embedding_gateway import (  # noqa: E402
    EmbeddingPort,
    load_embedder,
)
from archive.retrieval.models.model_constants import (  # noqa: E402
    MODEL_LOAD_TIMEOUT_S,
)
from archive.retrieval.qdrant.qdrant_constants import QDRANT_SUBDIR  # noqa: E402
from scripts.build_index_constants import (  # noqa: E402
    BYTES_PER_MB,
    MSG_NO_EMBEDDER,
    MSG_NO_PDFS,
    MSG_SIZE,
    MSG_SIZE_OVER_LIMIT,
    SQLITE_NAME,
    STORAGE_SIZE_LIMIT_MB,
)

logger = logging.getLogger("build_index")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path, default=REPO_ROOT / CORPUS_DIR_NAME
    )
    parser.add_argument(
        "--index", type=Path, default=REPO_ROOT / INDEX_DIR_NAME
    )
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument(
        "--sparse-only",
        action="store_true",
        help="build a BM25-only index without loading the dense model",
    )
    return parser.parse_args(argv)


def storage_size_mb(index_dir: Path) -> float:
    """Total size in MB of the Qdrant `storage.sqlite` files."""
    sizes = [
        path.stat().st_size
        for path in (index_dir / QDRANT_SUBDIR).rglob(SQLITE_NAME)
    ]
    return sum(sizes) / BYTES_PER_MB


def _report_size(index_dir: Path) -> None:
    size_mb = storage_size_mb(index_dir)
    print(MSG_SIZE.format(size_mb=size_mb))
    if size_mb >= STORAGE_SIZE_LIMIT_MB:
        message = MSG_SIZE_OVER_LIMIT.format(
            size_mb=size_mb, limit_mb=STORAGE_SIZE_LIMIT_MB
        )
        print(message, file=sys.stderr)


def _load_dense(sparse_only: bool) -> tuple[bool, EmbeddingPort | None]:
    """Return (ok, embedder); not ok when the dense model is required."""
    if sparse_only:
        return True, None
    embedder = load_embedder(MODEL_LOAD_TIMEOUT_S)
    return embedder is not None, embedder


def main(argv: list[str] | None = None) -> int:
    """Build the index; return the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    if not any(args.corpus.glob(PDF_GLOB)):
        logger.error(MSG_NO_PDFS.format(path=args.corpus))
        return EXIT_ERROR
    is_ready, embedder = _load_dense(args.sparse_only)
    if not is_ready:
        print(MSG_NO_EMBEDDER, file=sys.stderr)
        return EXIT_ERROR
    report = build(args.corpus, args.index, args.workers, embedder)
    logger.info(
        "docs=%d chunks=%d dense=%d failures=%d seconds=%.1f",
        report.docs,
        report.chunks,
        report.dense_chunks,
        len(report.failed_docs),
        report.seconds,
    )
    _report_size(args.index)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

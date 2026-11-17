"""CLI: build the static HTML viewer of a run from its traces."""

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/build_viewer.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.common.constants import (  # noqa: E402
    CORPUS_DIR_NAME,
    REPO_ROOT,
    VIEWER_DIR_NAME,
)
from archive.pipeline.pipeline_constants import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
)
from archive.viewer.page_render_gateway import render_evidence  # noqa: E402
from archive.viewer.viewer_build_service import (  # noqa: E402
    ViewerBudget,
    ViewerRequest,
    build_viewer,
)
from scripts.build_viewer_constants import (  # noqa: E402
    HELP_CORPUS,
    HELP_OUT,
    HELP_SCORES,
    HELP_TRACE_DIR,
    MSG_BUILD_FAILED,
    MSG_NO_TRACE_DIR,
    MSG_VIEWER_READY,
    SCRIPT_DESCRIPTION,
)

logger = logging.getLogger("build_viewer")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=SCRIPT_DESCRIPTION)
    parser.add_argument("trace_dir", type=Path, help=HELP_TRACE_DIR)
    parser.add_argument("--scores", type=Path, default=None, help=HELP_SCORES)
    parser.add_argument("--out", type=Path, default=None, help=HELP_OUT)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPO_ROOT / CORPUS_DIR_NAME,
        help=HELP_CORPUS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build the viewer; return the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    if not args.trace_dir.is_dir():
        logger.error(MSG_NO_TRACE_DIR.format(path=args.trace_dir))
        return EXIT_ERROR
    out_dir = args.out or REPO_ROOT / VIEWER_DIR_NAME / args.trace_dir.name
    request = ViewerRequest(
        trace_dir=args.trace_dir,
        corpus_dir=args.corpus,
        out_dir=out_dir,
        budget=ViewerBudget(None, time.monotonic),
        render=render_evidence,
        scores_path=args.scores,
    )
    try:
        index_path = build_viewer(request)
    except (OSError, ValueError) as error:
        logger.error(MSG_BUILD_FAILED.format(reason=error))
        return EXIT_ERROR
    print(MSG_VIEWER_READY.format(path=index_path))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

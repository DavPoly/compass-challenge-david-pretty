"""CLI: serve the viewer on localhost and answer live questions.

Usage: python scripts/serve.py [--run traces/<run>] [--port 8000]
Environment: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL (all required).
Exit codes: 0 stopped by the user, 1 unusable configuration, corpus,
index or port, 2 wrong usage.
"""

import argparse
import dataclasses
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/serve.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.common.config import AppConfig, ConfigError  # noqa: E402
from archive.common.constants import (  # noqa: E402
    CORPUS_DIR_NAME,
    PDF_GLOB,
    REPO_ROOT,
)
from archive.ingest.build.manifest_gateway import ManifestError  # noqa: E402
from archive.pipeline.engine.engine_service import (  # noqa: E402
    Engine,
    open_engine,
)
from archive.pipeline.pipeline_constants import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
    MSG_INDEX_OPEN,
    MSG_NO_CORPUS,
)
from archive.retrieval.qdrant.qdrant_gateway import (  # noqa: E402
    IndexOpenError,
)
from archive.server.ask_service import AskService  # noqa: E402
from archive.server.server_constants import DEFAULT_PORT, HOST  # noqa: E402
from archive.server.server_gateway import (  # noqa: E402
    ServerContext,
    create_server,
)
from archive.viewer.page_render_gateway import render_evidence  # noqa: E402
from archive.viewer.viewer_build_service import (  # noqa: E402
    ViewerBudget,
    ViewerRequest,
    build_viewer,
)
from scripts.serve_constants import (  # noqa: E402
    EMPTY_RUN_DIRNAME,
    HELP_CORPUS,
    HELP_PORT,
    HELP_RUN,
    LIVE_DIRNAME,
    LOG_FORMAT,
    LOG_PAGE_REBUILT,
    MSG_BUILD_FAILED,
    MSG_NO_RUN_DIR,
    MSG_PORT_BUSY,
    MSG_READY,
    MSG_STOPPED,
    SCRIPT_DESCRIPTION,
    SERVER_DIRNAME,
)

logger = logging.getLogger("serve")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=SCRIPT_DESCRIPTION)
    parser.add_argument("--run", type=Path, default=None, help=HELP_RUN)
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=HELP_PORT.format(port=DEFAULT_PORT),
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=REPO_ROOT / CORPUS_DIR_NAME,
        help=HELP_CORPUS,
    )
    return parser.parse_args(argv)


def _has_pdfs(corpus_dir: Path) -> bool:
    return corpus_dir.is_dir() and any(corpus_dir.glob(PDF_GLOB))


def _viewer_request(
    config: AppConfig, run_dir: Path | None, live_dir: Path
) -> ViewerRequest:
    """Request for the page: the optional run plus the live questions."""
    return ViewerRequest(
        trace_dir=run_dir or config.traces_dir / EMPTY_RUN_DIRNAME,
        corpus_dir=config.corpus_dir,
        out_dir=config.viewer_dir / SERVER_DIRNAME,
        budget=ViewerBudget(None, time.monotonic),
        render=render_evidence,
        extra_trace_dirs=(live_dir,),
        live=True,
    )


def _serve(engine: Engine, args: argparse.Namespace) -> int:
    config = engine.config
    live_dir = config.traces_dir / LIVE_DIRNAME
    request = _viewer_request(config, args.run, live_dir)

    def rebuild_page() -> None:
        # Re-renders every image: fine for a handful of live questions.
        build_viewer(request)
        logger.info(LOG_PAGE_REBUILT)

    try:
        rebuild_page()
    except (OSError, ValueError) as error:
        logger.error(MSG_BUILD_FAILED.format(reason=error))
        return EXIT_ERROR
    context = ServerContext(
        AskService(engine, request, live_dir), request.out_dir, rebuild_page
    )
    try:
        server = create_server(args.port, context)
    except OSError as error:
        logger.error(MSG_PORT_BUSY.format(port=args.port, reason=error))
        return EXIT_ERROR
    ready = MSG_READY.format(host=HOST, port=server.server_address[1])
    print(ready)
    logger.info(ready)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info(MSG_STOPPED)
    finally:
        server.server_close()
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Start the live server; return the process exit code."""
    logging.basicConfig(
        level=logging.INFO, format=LOG_FORMAT, stream=sys.stderr
    )
    args = _parse_args(argv)
    try:
        config = AppConfig.from_env()
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_ERROR
    config = dataclasses.replace(config, corpus_dir=args.corpus)
    if not _has_pdfs(config.corpus_dir):
        logger.error(MSG_NO_CORPUS.format(path=config.corpus_dir))
        return EXIT_ERROR
    if args.run is not None and not args.run.is_dir():
        logger.error(MSG_NO_RUN_DIR.format(path=args.run))
        return EXIT_ERROR
    try:
        with open_engine(config) as engine:
            return _serve(engine, args)
    except (IndexOpenError, ManifestError) as error:
        logger.error(
            MSG_INDEX_OPEN.format(path=config.index_dir, reason=error)
        )
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Answer questions about the corpus in ./corpus/.

Usage: python answer.py questions.jsonl answers.jsonl

Input: questions.jsonl, one {"id", "question"} object per line.
Output: answers.jsonl, one {"id", "answer", "citations", "status"}
object per question (status: answered, not_found or conflict).
Environment: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL (all required).
Exit codes: 0 run completed, 1 unusable input or configuration,
2 wrong usage.
"""

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from archive.common.config import AppConfig, ConfigError
from archive.pipeline.pipeline_constants import EXIT_ERROR, EXIT_USAGE
from archive.pipeline.run_service import run

USAGE = "usage: python answer.py questions.jsonl answers.jsonl"
EXPECTED_ARG_COUNT = 2
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main(argv: Sequence[str]) -> int:
    """Run the command on `argv` (without the program name)."""
    if len(argv) != EXPECTED_ARG_COUNT:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    try:
        config = AppConfig.from_env()
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_ERROR
    return run(Path(argv[0]), Path(argv[1]), config)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format=LOG_FORMAT, stream=sys.stderr
    )
    sys.exit(main(sys.argv[1:]))

"""Build the draft prompt and ask the LLM for a structured answer."""

import logging
import re
from collections.abc import Sequence

from archive.agent.prompt_constants import (
    DOCUMENT_CLOSE,
    DOCUMENT_OPEN,
    DOCUMENT_TAG_ESCAPE,
    DOCUMENT_TAG_PATTERN,
    MAX_PROMPT_CHUNKS,
    NO_DOCUMENTS_MISSING,
    SYSTEM_PROMPT,
    USER_PROMPT,
)
from archive.llm.llm_gateway import LlmGateway, Messages
from archive.retrieval.search_service import SearchHit
from archive.validation.answer_model import AnswerStatus, DraftAnswer
from archive.validation.input_model import Question
from archive.validation.validation_constants import NOT_FOUND_ANSWER

logger = logging.getLogger(__name__)

_DOCUMENT_TAG = re.compile(DOCUMENT_TAG_PATTERN, re.IGNORECASE)


def format_documents(hits: Sequence[SearchHit]) -> str:
    """Wrap the top chunks in untrusted-data delimiters, keyed by doc id."""
    blocks = []
    for hit in hits[:MAX_PROMPT_CHUNKS]:
        text = _DOCUMENT_TAG.sub(DOCUMENT_TAG_ESCAPE, hit.chunk.text)
        opening = DOCUMENT_OPEN.format(doc_id=hit.chunk.doc_id)
        blocks.append(f"{opening}\n{text}\n{DOCUMENT_CLOSE}")
    return "\n\n".join(blocks)


def build_messages(question: Question, hits: Sequence[SearchHit]) -> Messages:
    """Return the system and user messages of the draft call."""
    user = USER_PROMPT.format(
        documents=format_documents(hits), question=question.question
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def draft(
    question: Question, hits: Sequence[SearchHit], llm: LlmGateway
) -> DraftAnswer:
    """Draft an answer from the retrieved chunks.

    Without any hit it returns a not_found draft and makes no LLM call.

    Raises:
        LlmUnavailableError: the LLM could not give a valid draft.
    """
    if not hits:
        logger.info("question %s: no hits, skipping the LLM", question.id)
        return DraftAnswer(
            answer=NOT_FOUND_ANSWER,
            status=AnswerStatus.NOT_FOUND,
            citations=[],
            evidence_sufficient=False,
            missing=NO_DOCUMENTS_MISSING,
        )
    return llm.complete_json(build_messages(question, hits), DraftAnswer)

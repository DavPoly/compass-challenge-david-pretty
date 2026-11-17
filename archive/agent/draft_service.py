"""Build the draft prompt and ask the LLM for a structured answer."""

import logging
from collections.abc import Sequence

from archive.agent.prompt_constants import (
    DOCUMENT_ID_ATTRIBUTE,
    MAX_PROMPT_CHUNKS,
    NO_DOCUMENTS_MISSING,
    NOTE_SECTION,
    SYSTEM_PROMPT,
    USER_PROMPT,
)
from archive.common.constants import DOCUMENT_TAG
from archive.common.text.prompt_delimit_utils import (
    escape_untrusted,
    wrap_untrusted,
)
from archive.llm.llm_gateway import LlmGateway, Messages
from archive.retrieval.search_service import SearchHit
from archive.validation.answer_model import AnswerStatus, DraftAnswer
from archive.validation.input_model import Question
from archive.validation.validation_constants import NOT_FOUND_ANSWER

logger = logging.getLogger(__name__)


def format_documents(hits: Sequence[SearchHit]) -> str:
    """Wrap the top chunks in untrusted-data delimiters, keyed by doc id."""
    blocks = [
        wrap_untrusted(
            DOCUMENT_TAG,
            hit.chunk.text,
            DOCUMENT_ID_ATTRIBUTE.format(doc_id=hit.chunk.doc_id),
        )
        for hit in hits[:MAX_PROMPT_CHUNKS]
    ]
    return "\n\n".join(blocks)


def build_messages(
    question: Question,
    hits: Sequence[SearchHit],
    note: str | None = None,
) -> Messages:
    """Return the system and user messages of the draft call.

    A `note` is rendered between the documents and the question.
    """
    user = USER_PROMPT.format(
        documents=format_documents(hits),
        note=NOTE_SECTION.format(note=note) if note else "",
        question=escape_untrusted(DOCUMENT_TAG, question.question),
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def draft(
    question: Question,
    hits: Sequence[SearchHit],
    llm: LlmGateway,
    note: str | None = None,
) -> DraftAnswer:
    """Draft an answer from the retrieved chunks and an optional note.

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
    return llm.complete_json(build_messages(question, hits, note), DraftAnswer)

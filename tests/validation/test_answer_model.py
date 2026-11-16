import json

import pytest
from pydantic import ValidationError

from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    FinalAnswer,
)


def test_final_answer_line_has_exactly_four_keys() -> None:
    final = FinalAnswer(
        id="q1",
        answer="Léa",
        citations=["doc_0001"],
        status=AnswerStatus.ANSWERED,
    )

    payload = json.loads(final.to_jsonl_line())

    assert set(payload) == {"id", "answer", "citations", "status"}
    assert payload["status"] == "answered"


def test_jsonl_line_keeps_non_ascii_and_has_no_newline() -> None:
    final = FinalAnswer(
        id="q1",
        answer=["Raphaël", "Zoé"],
        citations=[],
        status=AnswerStatus.ANSWERED,
    )

    line = final.to_jsonl_line()

    assert "Raphaël" in line
    assert "\n" not in line


def test_not_found_factory_is_empty_abstention() -> None:
    final = FinalAnswer.not_found("q9")

    assert final.answer == ""
    assert final.citations == []
    assert final.status is AnswerStatus.NOT_FOUND


def test_final_answer_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        FinalAnswer.model_validate(
            {
                "id": "q1",
                "answer": "x",
                "citations": [],
                "status": "answered",
                "evidence": [],
            }
        )


def test_draft_defaults_and_schema_descriptions() -> None:
    draft = DraftAnswer(
        answer="x",
        status=AnswerStatus.ANSWERED,
        citations=[],
        evidence_sufficient=True,
    )

    assert draft.evidence == []
    assert draft.missing is None
    schema = DraftAnswer.model_json_schema()
    assert "description" in schema["properties"]["answer"]

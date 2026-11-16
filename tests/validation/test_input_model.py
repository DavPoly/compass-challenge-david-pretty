import logging
from pathlib import Path

import pytest

from archive.validation.input_model import (
    QuestionsFileError,
    load_questions,
)


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "questions.jsonl"
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_lines_load_and_extra_keys_are_ignored(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, '{"id": "s01", "question": "Q?", "lang": "fr"}\n')

    questions = load_questions(path)

    assert [(q.id, q.question, q.is_valid) for q in questions] == [
        ("s01", "Q?", True)
    ]


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = _write(tmp_path, '\n{"id": "a", "question": "Q"}\n   \n')

    assert [q.id for q in load_questions(path)] == ["a"]


def test_invalid_json_gets_line_id_and_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path, '{"id": "a", "question": "Q"}\n{oops\n')

    with caplog.at_level(logging.WARNING):
        questions = load_questions(path)

    assert questions[1].id == "line-2"
    assert not questions[1].is_valid
    assert "line 2" in caplog.text


def test_missing_question_keeps_recovered_id(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"id": "s05"}\n')

    question = load_questions(path)[0]

    assert question.id == "s05"
    assert not question.is_valid


def test_empty_question_is_invalid(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"id": "s06", "question": "  "}\n')

    question = load_questions(path)[0]

    assert question.id == "s06"
    assert not question.is_valid


def test_missing_id_and_non_object_line(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"question": "Q"}\n[1, 2]\n')

    questions = load_questions(path)

    assert [q.id for q in questions] == ["line-1", "line-2"]
    assert not any(q.is_valid for q in questions)


def test_duplicate_ids_are_kept_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(
        tmp_path,
        '{"id": "a", "question": "Q1"}\n{"id": "a", "question": "Q2"}\n',
    )

    with caplog.at_level(logging.WARNING):
        questions = load_questions(path)

    assert len(questions) == 2
    assert "appears 2 times" in caplog.text


def test_missing_file_error_names_path_and_fix(tmp_path: Path) -> None:
    missing = tmp_path / "nope.jsonl"

    with pytest.raises(QuestionsFileError) as error:
        load_questions(missing)

    assert str(missing) in str(error.value)
    assert "existing questions.jsonl" in str(error.value)

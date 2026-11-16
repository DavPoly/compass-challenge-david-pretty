import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path

import pytest

from archive.common.config import AppConfig
from archive.ingest.index_builder_service import build
from archive.llm.llm_gateway import LlmUnavailableError, Messages
from archive.pipeline import run_service
from archive.pipeline.pipeline_constants import (
    EXIT_ERROR,
    EXIT_OK,
    GLOBAL_DEADLINE_S,
    QUESTION_BUDGET_S,
    WORKER_COUNT,
)
from archive.retrieval.search_service import SearchFilters, SearchService
from archive.validation.answer_model import AnswerStatus, DraftAnswer

DOC_COUNT = 4
BUILD_WORKERS = 2
QUERY_WORDS = 8
ANSWER_KEYS = {"id", "answer", "citations", "status"}
STOP_ONLY_QUESTION = "le la les"
SLOW_MARK = "SLOWQUESTION"
TICK_SLEEP_S = 0.001
JOIN_TIMEOUT_S = 5.0
EXPECTED_VALID_STATUSES = {s.value for s in AnswerStatus}


class FakeClock:
    """Manual clock: `sleep` advances it, so polling loops end fast."""

    def __init__(self) -> None:
        self.now_s = 0.0

    def clock(self) -> float:
        return self.now_s

    def sleep(self, seconds: float) -> None:
        self.now_s += seconds
        time.sleep(TICK_SLEEP_S)


class FakeLlm:
    """Cites the first document of the prompt; blocks on SLOW_MARK."""

    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.release = threading.Event()
        self.finished = threading.Event()
        self.call_count = 0
        self._lock = threading.Lock()

    def complete_json(
        self, messages: Messages, schema: type[DraftAnswer]
    ) -> DraftAnswer:
        with self._lock:
            self.call_count += 1
        prompt = messages[-1]["content"]
        if SLOW_MARK in prompt:
            self.release.wait(JOIN_TIMEOUT_S * 2)
            self.finished.set()
        if self.failure:
            raise self.failure
        doc_id = re.search(r'<document id="([^"]+)">', prompt)
        assert doc_id
        return DraftAnswer(
            answer="42",
            status=AnswerStatus.ANSWERED,
            citations=[doc_id.group(1), "doc_unknown"],
            evidence_sufficient=True,
        )


@pytest.fixture(scope="module")
def indexed(
    kit_corpus_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[AppConfig, str]:
    root = tmp_path_factory.mktemp("run")
    corpus = root / "corpus"
    corpus.mkdir()
    for path in sorted(kit_corpus_dir.glob("*.pdf"))[:DOC_COUNT]:
        shutil.copy(path, corpus / path.name)
    index = root / "index"
    build(corpus, index, BUILD_WORKERS)
    with SearchService.open(index) as service:
        text = service.list_by_filter(SearchFilters(), 1)[0].chunk.text
    config = AppConfig("http://x", "secret", "model", corpus, index)
    return config, " ".join(text.split()[:QUERY_WORDS])


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    llm = FakeLlm()
    monkeypatch.setattr(run_service, "LlmGateway", lambda config: llm)
    return llm


def write_questions(path: Path, rows: list[object]) -> Path:
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def read_answers(path: Path) -> dict[str, dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    answers = {row["id"]: row for row in parsed}
    assert len(answers) == len(parsed), "duplicate answer lines"
    return answers


def run_with_clock(
    questions: Path, answers: Path, config: AppConfig
) -> tuple[int, FakeClock]:
    fake = FakeClock()
    code = run_service.run(questions, answers, config, fake.clock, fake.sleep)
    return code, fake


def test_end_to_end_writes_one_valid_line_per_question(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl",
        [
            {"id": "q1", "question": query},
            {"id": "q2", "question": query},
            "not json",
        ],
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config)

    rows = read_answers(answers)
    known = {p.stem for p in config.corpus_dir.glob("*.pdf")}
    assert code == EXIT_OK
    assert set(rows) == {"q1", "q2", "line-3"}
    assert all(set(row) == ANSWER_KEYS for row in rows.values())
    assert all(r["status"] in EXPECTED_VALID_STATUSES for r in rows.values())
    assert rows["q1"]["status"] == "answered"
    assert len(rows["q1"]["citations"]) == 1  # type: ignore[arg-type]
    assert set(rows["q1"]["citations"]) <= known  # type: ignore[call-overload]
    assert rows["line-3"]["status"] == "not_found"
    assert rows["line-3"]["citations"] == []


def test_zero_hits_makes_no_llm_call(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": STOP_ONLY_QUESTION}]
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, indexed[0])

    assert code == EXIT_OK
    assert read_answers(answers)["q1"]["status"] == "not_found"
    assert fake_llm.call_count == 0


def test_llm_unavailable_gives_not_found(
    indexed: tuple[AppConfig, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    llm = FakeLlm(LlmUnavailableError("down"))
    monkeypatch.setattr(run_service, "LlmGateway", lambda config: llm)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config)

    assert code == EXIT_OK
    assert read_answers(answers)["q1"]["status"] == "not_found"


def test_unexpected_error_is_contained_per_question(
    indexed: tuple[AppConfig, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = FakeLlm(RuntimeError("boom"))
    monkeypatch.setattr(run_service, "LlmGateway", lambda config: llm)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config)

    assert code == EXIT_OK
    assert read_answers(answers)["q1"]["status"] == "not_found"
    assert "unexpected error" in caplog.text


def test_question_over_budget_gets_not_found_and_late_result_dropped(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl",
        [
            {"id": "fast", "question": query},
            {"id": "slow", "question": f"{query} {SLOW_MARK}"},
        ],
    )
    answers = tmp_path / "a.jsonl"

    code, fake = run_with_clock(questions, answers, config)
    before = answers.read_text(encoding="utf-8")
    fake_llm.release.set()
    assert fake_llm.finished.wait(JOIN_TIMEOUT_S)
    time.sleep(0.05)

    rows = read_answers(answers)
    assert code == EXIT_OK
    assert rows["fast"]["status"] == "answered"
    assert rows["slow"]["status"] == "not_found"
    assert QUESTION_BUDGET_S <= fake.now_s < GLOBAL_DEADLINE_S
    assert answers.read_text(encoding="utf-8") == before


def test_global_deadline_fills_unanswered_questions(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config, query = indexed
    count = WORKER_COUNT + 2
    questions = write_questions(
        tmp_path / "q.jsonl",
        [
            {"id": f"q{n}", "question": f"{query} {SLOW_MARK}"}
            for n in range(count)
        ],
    )
    answers = tmp_path / "a.jsonl"

    with caplog.at_level(logging.ERROR):
        code, fake = run_with_clock(questions, answers, config)
    fake_llm.release.set()

    rows = read_answers(answers)
    assert code == EXIT_OK
    assert len(rows) == count
    assert all(r["status"] == "not_found" for r in rows.values())
    assert fake.now_s >= GLOBAL_DEADLINE_S
    assert "global deadline" in caplog.text


def test_missing_questions_file_exits_one(
    indexed: tuple[AppConfig, str], tmp_path: Path
) -> None:
    code = run_service.run(
        tmp_path / "missing.jsonl", tmp_path / "a.jsonl", indexed[0]
    )

    assert code == EXIT_ERROR


@pytest.mark.parametrize("make_dir", [False, True])
def test_missing_or_empty_corpus_exits_one(
    indexed: tuple[AppConfig, str],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    make_dir: bool,
) -> None:
    corpus = tmp_path / "corpus"
    if make_dir:
        corpus.mkdir()
    config = AppConfig("u", "k", "m", corpus, indexed[0].index_dir)
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])

    code = run_service.run(questions, tmp_path / "a.jsonl", config)

    assert code == EXIT_ERROR
    assert str(corpus) in caplog.text
    assert "corpus/" in caplog.text


def test_index_open_failure_exits_one(
    indexed: tuple[AppConfig, str], tmp_path: Path
) -> None:
    config = AppConfig(
        "u", "k", "m", indexed[0].corpus_dir, tmp_path / "no_index"
    )
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])

    code = run_service.run(questions, tmp_path / "a.jsonl", config)

    assert code == EXIT_ERROR


def test_unwritable_answers_path_exits_one(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])

    code = run_service.run(
        questions, tmp_path / "missing_dir" / "a.jsonl", indexed[0]
    )

    assert code == EXIT_ERROR

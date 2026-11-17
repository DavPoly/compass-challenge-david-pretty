import contextlib
import json
import logging
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from archive.agent import answer_service
from archive.agent.hops.hop_constants import (
    HOP_TIME_BUDGET_S,
    MULTI_HOP_MAX_DRAFTS,
)
from archive.agent.hops.hop_model import HopPolicy
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.common.config import AppConfig
from archive.ingest.build.index_builder_service import (
    IndexBuildError,
    build,
)
from archive.llm.llm_gateway import LlmUnavailableError, Messages
from archive.pipeline import run_service
from archive.pipeline.engine import engine_service
from archive.pipeline.engine.engine_service import Engine
from archive.pipeline.pipeline_constants import (
    EXIT_ERROR,
    EXIT_OK,
    GLOBAL_DEADLINE_S,
    POLL_INTERVAL_S,
    QUESTION_BUDGET_S,
    WORKER_COUNT,
)
from archive.retrieval.search_service import (
    SearchFilters,
    SearchHit,
    SearchService,
)
from archive.validation.answer_model import AnswerStatus, DraftAnswer
from archive.validation.input_model import Question

DOC_COUNT = 4
BUILD_WORKERS = 2
QUERY_WORDS = 8
ANSWER_KEYS = {"id", "answer", "citations", "status"}
STOP_ONLY_QUESTION = "le la les"
SLOW_MARK = "SLOWQUESTION"
TICK_SLEEP_S = 0.001
JOIN_TIMEOUT_S = 5.0
SLOW_PLAN_S = 25.0
SLOW_DRAFT_S = 10.0
INDEX_SCAN_LIMIT = 1000
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


class StubContext:
    """Minimal run context: a stale question never reaches search."""

    deadline_s = QUESTION_BUDGET_S
    run_id = ""
    traces = None
    engine = None

    def clock(self) -> float:
        return 0.0


class FakeLlm:
    """Cites the first document of the prompt; blocks on SLOW_MARK.

    `call_count` counts draft calls only; plan calls answer `direct`.
    """

    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.release = threading.Event()
        self.finished = threading.Event()
        self.call_count = 0
        self._lock = threading.Lock()

    def complete_json(
        self, messages: Messages, schema: type[BaseModel]
    ) -> Any:
        if schema is QuestionPlan:
            return QuestionPlan(family=QuestionFamily.DIRECT)
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
    config = AppConfig(
        "http://x", "secret", "model", corpus, index, root / "traces"
    )
    return config, " ".join(text.split()[:QUERY_WORDS])


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    llm = FakeLlm()
    monkeypatch.setattr(engine_service, "LlmGateway", lambda config: llm)
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


def test_confidence_is_logged_and_the_answer_line_is_unchanged(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    with caplog.at_level(logging.INFO):
        code = run_service.run(questions, answers, config)

    row = read_answers(answers)["q1"]
    assert code == EXIT_OK
    assert "question q1: grounding confidence low" in caplog.text
    assert row == {
        "id": "q1",
        "answer": "42",
        "citations": row["citations"],
        "status": "answered",
    }
    assert len(row["citations"]) == 1  # type: ignore[arg-type]


def test_grounding_failure_leaves_the_answer_line_unchanged(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("grounding bug")

    monkeypatch.setattr(engine_service, "check_grounding", broken)

    with caplog.at_level(logging.INFO):
        code = run_service.run(questions, answers, config)

    row = read_answers(answers)["q1"]
    assert code == EXIT_OK
    assert "question q1: grounding check failed" in caplog.text
    assert row["status"] == "answered"
    assert row["answer"] == "42"


def test_duplicate_id_answers_only_the_first_question(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl",
        [
            {"id": "dup", "question": query},
            {"id": "dup", "question": STOP_ONLY_QUESTION},
        ],
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config)

    lines = answers.read_text(encoding="utf-8").splitlines()
    assert code == EXIT_OK
    assert len(lines) == 1
    assert read_answers(answers)["dup"]["status"] == "answered"
    assert fake_llm.call_count == 1


def test_zero_hits_makes_no_draft_call(
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
    monkeypatch.setattr(engine_service, "LlmGateway", lambda config: llm)
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
    monkeypatch.setattr(engine_service, "LlmGateway", lambda config: llm)
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


def test_engine_startup_oserror_reports_the_index_not_the_answers_file(
    indexed: tuple[AppConfig, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    def broken_open(config: AppConfig) -> Iterator[Engine]:
        raise OSError("disk unreadable")
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(
        run_service, "open_engine", contextlib.contextmanager(broken_open)
    )
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])

    code = run_service.run(questions, tmp_path / "a.jsonl", indexed[0])

    assert code == EXIT_ERROR
    assert "Cannot open the index" in caplog.text
    assert "disk unreadable" in caplog.text
    assert "I/O error while answering" not in caplog.text


def test_unwritable_answers_file_keeps_the_io_message(
    indexed: tuple[AppConfig, str],
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])
    answers = tmp_path / "missing_dir" / "a.jsonl"

    code = run_service.run(questions, answers, indexed[0])

    assert code == EXIT_ERROR
    assert "I/O error while answering" in caplog.text
    assert "Cannot open the index" not in caplog.text


def failing_sync(*_args: object, **_kwargs: object) -> None:
    raise IndexBuildError("cannot clear the index")


def test_unusable_index_after_failed_sync_exits_one(
    indexed: tuple[AppConfig, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(engine_service, "sync_index", failing_sync)
    config = AppConfig(
        "u", "k", "m", indexed[0].corpus_dir, tmp_path / "no_index"
    )
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])

    code = run_service.run(questions, tmp_path / "a.jsonl", config)

    assert code == EXIT_ERROR


def test_missing_index_is_built_by_the_startup_sync(
    indexed: tuple[AppConfig, str], tmp_path: Path
) -> None:
    config = AppConfig(
        "u", "k", "m", indexed[0].corpus_dir, tmp_path / "fresh_index"
    )
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])

    code = run_service.run(questions, tmp_path / "a.jsonl", config)

    assert code == EXIT_OK
    assert (config.index_dir / "manifest.json").is_file()


def test_failed_sync_continues_on_the_existing_index(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(engine_service, "sync_index", failing_sync)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": query}]
    )

    with caplog.at_level(logging.WARNING):
        code = run_service.run(questions, tmp_path / "a.jsonl", config)

    assert code == EXIT_OK
    assert "index sync failed" in caplog.text


def test_unexpected_sync_error_continues_on_the_existing_index(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    def broken_sync(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("pool died")

    monkeypatch.setattr(engine_service, "sync_index", broken_sync)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": query}]
    )

    with caplog.at_level(logging.WARNING):
        code = run_service.run(questions, tmp_path / "a.jsonl", config)

    assert code == EXIT_OK
    assert (tmp_path / "a.jsonl").is_file()
    assert "pool died" in caplog.text


def test_unwritable_answers_path_exits_one(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    questions = write_questions(tmp_path / "q.jsonl", [{"id": "a"}])

    code = run_service.run(
        questions, tmp_path / "missing_dir" / "a.jsonl", indexed[0]
    )

    assert code == EXIT_ERROR


def test_deadline_clock_starts_before_index_loading(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = FakeClock()
    real_open = SearchService.open
    load_cost_s = GLOBAL_DEADLINE_S - QUESTION_BUDGET_S / 2

    def slow_open(index_dir: Path, *models: object) -> SearchService:
        fake.now_s += load_cost_s
        return real_open(index_dir)

    monkeypatch.setattr(SearchService, "open", staticmethod(slow_open))
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": f"{query} {SLOW_MARK}"}]
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config, fake.clock, fake.sleep)
    fake_llm.release.set()

    assert code == EXIT_OK
    assert read_answers(answers)["q"]["status"] == "not_found"
    assert (
        GLOBAL_DEADLINE_S
        <= fake.now_s
        <= (GLOBAL_DEADLINE_S + POLL_INTERVAL_S)
    )


def test_run_returns_by_deadline_when_a_worker_never_returns(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": f"{query} {SLOW_MARK}"}]
    )
    answers = tmp_path / "a.jsonl"

    code, fake = run_with_clock(questions, answers, config)

    assert code == EXIT_OK
    assert not fake_llm.finished.is_set()
    assert fake.now_s <= GLOBAL_DEADLINE_S + POLL_INTERVAL_S
    assert read_answers(answers)["q"]["status"] == "not_found"
    fake_llm.release.set()


def test_citation_outside_the_corpus_is_dropped(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config, query = indexed
    pdfs = sorted(config.corpus_dir.glob("*.pdf"))
    kept, gone = pdfs[0], pdfs[-1]
    partial = tmp_path / "corpus"
    partial.mkdir()
    shutil.copy(kept, partial / kept.name)
    partial_config = AppConfig("u", "k", "m", partial, config.index_dir)

    def only_the_gone_doc(
        service: SearchService,
        text: str,
        filters: SearchFilters | None,
        k: int,
    ) -> list[SearchHit]:
        hits = service.list_by_filter(SearchFilters(), INDEX_SCAN_LIMIT)
        return [hit for hit in hits if hit.chunk.doc_id == gone.stem][:1]

    monkeypatch.setattr(SearchService, "hybrid_search", only_the_gone_doc)
    monkeypatch.setattr(engine_service, "sync_index", failing_sync)
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    with caplog.at_level(logging.WARNING):
        code = run_service.run(questions, answers, partial_config)

    assert code == EXIT_OK
    assert read_answers(answers)["q"]["citations"] == []
    assert gone.stem not in {p.stem for p in partial.glob("*.pdf")}
    assert "doc ids differ" in caplog.text


def test_late_write_to_a_closed_answers_file_is_discarded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = (tmp_path / "a.jsonl").open("w", encoding="utf-8", newline="\n")
    writer = run_service.AnswerWriter(out)
    out.close()
    stale = Question(id="q", question="", is_valid=False, error="empty")

    with caplog.at_level(logging.DEBUG, logger=run_service.__name__):
        run_service._work(
            stale, writer, run_service.StartTimes(), StubContext()
        )

    assert "late result discarded" in caplog.text


class FakeModel:
    """Stands in for both ports; only identity matters here."""

    dim = 8


def install_loaders(
    monkeypatch: pytest.MonkeyPatch,
    embedder: object | None,
    reranker: object | None,
    on_load: Callable[[], None] | None = None,
) -> None:
    def load(model: object | None) -> Callable[[float], object | None]:
        def loader(timeout_s: float) -> object | None:
            if on_load:
                on_load()
            return model

        return loader

    monkeypatch.setattr(engine_service, "load_embedder", load(embedder))
    monkeypatch.setattr(engine_service, "load_reranker", load(reranker))


def test_models_are_passed_to_sync_and_search(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    embedder, reranker = FakeModel(), FakeModel()
    install_loaders(monkeypatch, embedder, reranker)
    seen: dict[str, object] = {}
    real_open = SearchService.open
    real_sync = engine_service.sync_index

    def spy_open(
        index_dir: Path, embedder: object = None, reranker: object = None
    ) -> SearchService:
        seen["search"] = (embedder, reranker)
        return real_open(index_dir)

    def spy_sync(*args: object, **kwargs: object) -> object:
        seen["sync"] = kwargs["embedder"]
        return real_sync(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SearchService, "open", staticmethod(spy_open))
    monkeypatch.setattr(engine_service, "sync_index", spy_sync)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": query}]
    )

    code = run_service.run(questions, tmp_path / "a.jsonl", config)

    assert code == EXIT_OK
    assert seen["search"] == (embedder, reranker)
    assert seen["sync"] is embedder


def test_missing_embedder_warns_and_still_answers(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config)

    assert code == EXIT_OK
    assert read_answers(answers)["q"]["status"] == "answered"
    assert caplog.text.count("dense model unavailable") == 1


def test_model_loading_counts_against_the_global_deadline(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = FakeClock()
    install_loaders(
        monkeypatch,
        None,
        None,
        on_load=lambda: setattr(fake, "now_s", GLOBAL_DEADLINE_S),
    )
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config, fake.clock, fake.sleep)

    assert code == EXIT_OK
    assert read_answers(answers)["q"]["status"] == "not_found"
    assert fake_llm.call_count == 0


class VirtualClock:
    """Time that only moves when the fake LLM spends it."""

    def __init__(self) -> None:
        self.now_s = 0.0

    def __call__(self) -> float:
        return self.now_s


class SlowHopLlm:
    """Plans multi_hop, then drafts insufficient answers, slowly."""

    def __init__(self, clock: VirtualClock) -> None:
        self.clock = clock
        self.draft_count = 0

    def complete_json(
        self, messages: Messages, schema: type[BaseModel]
    ) -> Any:
        if schema is QuestionPlan:
            self.clock.now_s += SLOW_PLAN_S
            return QuestionPlan(family=QuestionFamily.MULTI_HOP)
        self.draft_count += 1
        self.clock.now_s += SLOW_DRAFT_S
        doc_id = re.search(r'<document id="([^"]+)">', messages[-1]["content"])
        assert doc_id
        return DraftAnswer(
            answer="partial",
            status=AnswerStatus.ANSWERED,
            citations=[doc_id.group(1)],
            evidence_sufficient=False,
            missing="the next fact to look up",
        )


def test_hop_budget_runs_from_question_start_and_still_answers(
    indexed: tuple[AppConfig, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock = VirtualClock()
    llm = SlowHopLlm(clock)
    monkeypatch.setattr(engine_service, "LlmGateway", lambda config: llm)
    monkeypatch.setattr(
        answer_service, "time", SimpleNamespace(monotonic=clock)
    )
    monkeypatch.setattr(
        HopPolicy,
        "multi_hop",
        classmethod(
            lambda cls: cls(
                max_drafts=MULTI_HOP_MAX_DRAFTS,
                expand_upfront=True,
                time_budget_s=HOP_TIME_BUDGET_S,
                clock=clock,
            )
        ),
    )
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    code = run_service.run(questions, answers, config)

    assert code == EXIT_OK
    assert read_answers(answers)["q1"]["status"] == "answered"
    assert llm.draft_count == 1
    assert clock.now_s <= QUESTION_BUDGET_S


RUN_NOW = datetime(2026, 1, 2, 3, 4, 5)
RUN_ID = "20260102-030405"


def run_traced(
    questions: Path, answers: Path, config: AppConfig, tmp_path: Path
) -> tuple[int, Path]:
    traced = replace(config, traces_dir=tmp_path / "traces")
    fake = FakeClock()
    code = run_service.run(
        questions, answers, traced, fake.clock, fake.sleep, lambda: RUN_NOW
    )
    return code, tmp_path / "traces" / RUN_ID


def read_traces(run_dir: Path) -> dict[str, dict[str, Any]]:
    paths = sorted(run_dir.glob("*.json"))
    traces = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    return {trace["question_id"]: trace for trace in traces}


def test_ok_question_trace_matches_the_answer_line(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    code, run_dir = run_traced(questions, answers, config, tmp_path)

    trace = read_traces(run_dir)["q1"]
    assert code == EXIT_OK
    assert trace["final"] == read_answers(answers)["q1"]
    assert trace["run_id"] == RUN_ID
    assert trace["question"] == query
    assert trace["error"] is None
    assert trace["plan"]["family"] == "direct"
    assert trace["retrieved"]
    assert trace["draft"]["answer"] == "42"
    assert trace["grounding"] is not None
    assert trace["dropped_citations"] == ["doc_unknown"]


def test_invalid_question_gets_a_trace(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
) -> None:
    config, _ = indexed
    questions = write_questions(tmp_path / "q.jsonl", ["not json"])
    answers = tmp_path / "a.jsonl"

    _, run_dir = run_traced(questions, answers, config, tmp_path)

    trace = read_traces(run_dir)["line-1"]
    assert trace["final"] == read_answers(answers)["line-1"]
    assert trace["error"]
    assert trace["draft"] is None
    assert fake_llm.call_count == 0


def test_llm_error_trace_records_the_error(
    indexed: tuple[AppConfig, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    llm = FakeLlm(LlmUnavailableError("down"))
    monkeypatch.setattr(engine_service, "LlmGateway", lambda config: llm)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    _, run_dir = run_traced(questions, answers, config, tmp_path)

    trace = read_traces(run_dir)["q1"]
    assert trace["error"] == "down"
    assert trace["final"] == read_answers(answers)["q1"]
    assert trace["final"]["status"] == "not_found"


def test_unexpected_error_trace_names_the_exception(
    indexed: tuple[AppConfig, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    llm = FakeLlm(RuntimeError("boom"))
    monkeypatch.setattr(engine_service, "LlmGateway", lambda config: llm)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    _, run_dir = run_traced(questions, answers, config, tmp_path)

    trace = read_traces(run_dir)["q1"]
    assert trace["error"] == "RuntimeError: boom"
    assert trace["final"] == read_answers(answers)["q1"]


def test_unwritable_trace_dir_keeps_answers_and_exit_code(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config, query = indexed
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    config = replace(config, traces_dir=blocker)
    questions = write_questions(
        tmp_path / "q.jsonl",
        [{"id": "q1", "question": query}, {"id": "q2", "question": query}],
    )
    answers = tmp_path / "a.jsonl"

    code, _ = run_with_clock(questions, answers, config)

    assert code == EXIT_OK
    assert set(read_answers(answers)) == {"q1", "q2"}
    assert "trace not written" in caplog.text


def test_trace_building_failure_never_reaches_the_answer(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def explode(*_args: object) -> None:
        raise ValueError("bad trace")

    monkeypatch.setattr(run_service, "build_trace", explode)
    config, query = indexed
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )
    answers = tmp_path / "a.jsonl"

    code, run_dir = run_traced(questions, answers, config, tmp_path)

    assert code == EXIT_OK
    assert read_answers(answers)["q1"]["status"] == "answered"
    assert not run_dir.exists()


def test_expired_question_trace_is_not_found_with_an_error(
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

    _, run_dir = run_traced(questions, answers, config, tmp_path)
    fake_llm.release.set()
    assert fake_llm.finished.wait(JOIN_TIMEOUT_S)
    time.sleep(0.2)

    rows = read_answers(answers)
    traces = read_traces(run_dir)
    assert rows["slow"]["status"] == "not_found"
    assert traces["slow"]["final"] == rows["slow"]
    assert traces["slow"]["error"]
    assert traces["fast"]["final"] == rows["fast"]
    assert traces["fast"]["error"] is None


def test_deadline_cut_questions_still_get_a_trace(
    indexed: tuple[AppConfig, str], fake_llm: FakeLlm, tmp_path: Path
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

    _, run_dir = run_traced(questions, answers, config, tmp_path)
    fake_llm.release.set()
    time.sleep(0.2)

    rows = read_answers(answers)
    traces = read_traces(run_dir)
    assert set(traces) == set(rows)
    for question_id, trace in traces.items():
        assert trace["final"] == rows[question_id]
        assert trace["error"]


def test_run_writes_traces_but_no_viewer(
    indexed: tuple[AppConfig, str],
    fake_llm: FakeLlm,
    tmp_path: Path,
) -> None:
    config, query = indexed
    config = replace(config, viewer_dir=tmp_path / "viewer")
    questions = write_questions(
        tmp_path / "q.jsonl", [{"id": "q1", "question": query}]
    )

    code, run_dir = run_traced(
        questions, tmp_path / "a.jsonl", config, tmp_path
    )

    assert code == EXIT_OK
    assert read_traces(run_dir)
    assert not (tmp_path / "viewer").exists()

"""Build the static HTML viewer from the traces of a run."""

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ValidationError

from archive.common.constants import PDF_SUFFIX
from archive.pipeline.pipeline_constants import TRACE_SUFFIX
from archive.pipeline.trace_gateway import trace_filename
from archive.pipeline.trace_model import QuestionTrace, RetrievedChunk
from archive.validation.answer_model import Evidence
from archive.validation.answer_validator import normalize_doc_id
from archive.viewer.viewer_constants import (
    ACCURACY_DECIMALS,
    CONFIDENCE_LABELS,
    CONFIDENCE_UNKNOWN,
    DATA_PLACEHOLDER,
    IGNORED_ISSUE_CODES,
    INDEX_FILENAME,
    INLINE_ASSETS,
    ISSUE_SEPARATOR,
    LOG_BUDGET_EXHAUSTED,
    LOG_DOC_OUTSIDE_CORPUS,
    LOG_RENDER_FAILED,
    LOG_SCORES_UNUSABLE,
    LOG_TRACE_SKIPPED,
    LOG_VIEWER_WRITTEN,
    MSG_ASSET_MISSING,
    MSG_PLACEHOLDER_MISSING,
    MSG_TEMPLATE_MISSING,
    PAGES_DIRNAME,
    REASON_BY_ISSUE_CODE,
    REASON_EVIDENCE_INSUFFICIENT,
    RETRIEVED_LIMIT,
    SCORE_EXPECTED_KEY,
    SCORE_ID_KEY,
    SCORE_OK_KEY,
    SCORE_ROWS_KEY,
    SCRIPT_ESCAPES,
    TEMPLATE_PATH,
    TRACE_GLOB,
    VIEWER_ENCODING,
)
from archive.viewer.viewer_model import (
    ConfidenceAccuracy,
    EvidenceState,
    EvidenceView,
    QuestionView,
    RetrievedView,
    RunSummary,
    ViewerData,
)

logger = logging.getLogger(__name__)

Answer = str | list[str]
Verdict = Literal["verified", "unverified", "unchecked"]


@dataclass(frozen=True)
class ViewerBudget:
    """Wall-clock allowance for rendering; ``until_s`` None = unlimited."""

    until_s: float | None
    clock: Callable[[], float]

    def has_time(self) -> bool:
        """Whether the deadline has not passed yet."""
        return self.until_s is None or self.clock() < self.until_s


class RenderedLike(Protocol):
    """What the viewer needs from a rendered evidence."""

    @property
    def page(self) -> int | None:
        """1-based page of the quote, if located."""

    @property
    def crop_path(self) -> Path | None:
        """Image of the quote region, if any."""

    @property
    def full_path(self) -> Path | None:
        """Image of the whole page, if any."""

    @property
    def is_located(self) -> bool:
        """Whether the quote was found in the PDF."""


# (pdf_path, evidence, is_verified, out_stem) -> rendered evidence
EvidenceRenderer = Callable[[Path, Evidence, bool, Path], RenderedLike]


@dataclass(frozen=True)
class ViewerRequest:
    """Inputs of one viewer build."""

    trace_dir: Path
    corpus_dir: Path
    out_dir: Path
    budget: ViewerBudget
    render: EvidenceRenderer
    scores_path: Path | None = None
    template_path: Path = TEMPLATE_PATH
    now: Callable[[], datetime] = datetime.now


@dataclass(frozen=True)
class _Score:
    is_correct: bool
    expected_answer: Answer | None


def build_viewer(request: ViewerRequest) -> Path:
    """Write ``index.html`` (and evidence images) under ``out_dir``.

    Traces that cannot be parsed are skipped with a warning. Evidence is
    rendered while the budget has time; afterwards quotes are shown as
    text only. When the scores file is readable, each question gets its
    correctness and the summary an accuracy per confidence label.

    A quote is "verified" unless the grounding report lists it as
    unverified; when a draft has no grounding report (the check
    crashed), its quotes are "unchecked" rather than verified.

    Returns:
        Path of the written ``index.html``.

    Raises:
        FileNotFoundError: the template does not exist.
        ValueError: the template lacks the data placeholder.
        OSError: the page cannot be written.
    """
    template = _read_template(request.template_path)
    scores = _load_scores(request.scores_path)
    request.out_dir.mkdir(parents=True, exist_ok=True)
    traces = _load_traces(request.trace_dir)
    data = _make_viewer_data(traces, scores, request)
    page = _embed(template, data, request.template_path)
    target = request.out_dir / INDEX_FILENAME
    target.write_text(page, encoding=VIEWER_ENCODING)
    logger.info(LOG_VIEWER_WRITTEN, target)
    return target


def _make_viewer_data(
    traces: list[QuestionTrace],
    scores: dict[str, _Score] | None,
    request: ViewerRequest,
) -> ViewerData:
    questions = [_question_view(t, request, scores) for t in traces]
    return ViewerData(
        run_id=traces[0].run_id if traces else "",
        generated_at=request.now().astimezone().isoformat(timespec="seconds"),
        is_scored=scores is not None,
        summary=_summary(questions, scores is not None),
        questions=questions,
    )


def _read_template(path: Path) -> str:
    try:
        template = path.read_text(encoding=VIEWER_ENCODING)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            MSG_TEMPLATE_MISSING.format(path=path)
        ) from error
    for token, filename in INLINE_ASSETS:
        if token in template:
            asset = _read_asset(path.parent / filename, token)
            template = template.replace(token, asset, 1)
    return template


def _read_asset(path: Path, token: str) -> str:
    try:
        return path.read_text(encoding=VIEWER_ENCODING)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            MSG_ASSET_MISSING.format(path=path, token=token)
        ) from error


def _embed(template: str, data: ViewerData, path: Path) -> str:
    if DATA_PLACEHOLDER not in template:
        raise ValueError(
            MSG_PLACEHOLDER_MISSING.format(
                path=path, placeholder=DATA_PLACEHOLDER
            )
        )
    payload = data.model_dump_json()
    for char, escape in SCRIPT_ESCAPES.items():
        payload = payload.replace(char, escape)
    return template.replace(DATA_PLACEHOLDER, payload, 1)


def _load_traces(trace_dir: Path) -> list[QuestionTrace]:
    traces: list[QuestionTrace] = []
    for path in sorted(trace_dir.glob(TRACE_GLOB)):
        try:
            text = path.read_text(encoding=VIEWER_ENCODING)
            traces.append(QuestionTrace.model_validate_json(text))
        except (OSError, ValueError, ValidationError):
            logger.warning(LOG_TRACE_SKIPPED, path, exc_info=True)
    return sorted(traces, key=lambda trace: trace.question_id)


def _load_scores(path: Path | None) -> dict[str, _Score] | None:
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding=VIEWER_ENCODING))
        return {
            str(row[SCORE_ID_KEY]): _Score(
                bool(row[SCORE_OK_KEY]), row.get(SCORE_EXPECTED_KEY)
            )
            for row in raw[SCORE_ROWS_KEY]
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        logger.warning(LOG_SCORES_UNUSABLE, path, exc_info=True)
        return None


def _question_view(
    trace: QuestionTrace,
    request: ViewerRequest,
    scores: dict[str, _Score] | None,
) -> QuestionView:
    grounding = trace.grounding
    score = scores.get(trace.question_id) if scores else None
    family = trace.plan.get("family") if trace.plan else None
    return QuestionView(
        id=trace.question_id,
        question=trace.question,
        family=str(family) if family is not None else None,
        status=trace.final.status.value,
        answer=trace.final.answer,
        citations=trace.final.citations,
        confidence=grounding.confidence.value if grounding else None,
        confidence_reasons=_confidence_reasons(trace),
        ungrounded_values=grounding.ungrounded_values if grounding else [],
        dropped_citations=trace.dropped_citations,
        note=trace.note,
        error=trace.error,
        elapsed_s=trace.elapsed_s,
        is_correct=score.is_correct if score else None,
        expected_answer=score.expected_answer if score else None,
        retrieved=_retrieved_views(trace.retrieved),
        evidence=_evidence_views(trace, request),
    )


def _retrieved_views(chunks: Iterable[RetrievedChunk]) -> list[RetrievedView]:
    best: dict[str, RetrievedChunk] = {}
    for chunk in chunks:
        known = best.get(chunk.doc_id)
        if known is None or chunk.score > known.score:
            best[chunk.doc_id] = chunk
    ranked = sorted(best.values(), key=lambda chunk: -chunk.score)
    return [
        RetrievedView(
            doc_id=chunk.doc_id,
            score=chunk.score,
            doc_type=chunk.doc_type,
            doc_date=chunk.doc_date,
        )
        for chunk in ranked[:RETRIEVED_LIMIT]
    ]


def _issue_codes(trace: QuestionTrace) -> list[str]:
    codes = [
        issue.split(ISSUE_SEPARATOR, 1)[0].strip()
        for issue in trace.validation_issues
    ]
    if trace.grounding is not None:
        codes += [issue.code.value for issue in trace.grounding.issues]
    return codes


def _confidence_reasons(trace: QuestionTrace) -> list[str]:
    reasons: list[str] = []
    for code in _issue_codes(trace):
        reason = REASON_BY_ISSUE_CODE.get(code)
        if code in IGNORED_ISSUE_CODES or reason is None:
            continue
        if reason not in reasons:
            reasons.append(reason)
    if trace.draft is not None and not trace.draft.evidence_sufficient:
        reasons.append(REASON_EVIDENCE_INSUFFICIENT)
    return reasons


def _evidence_views(
    trace: QuestionTrace, request: ViewerRequest
) -> list[EvidenceView]:
    if trace.draft is None:
        return []
    unverified = set(
        trace.grounding.unverified_quotes if trace.grounding else []
    )
    stem_base = trace_filename(trace.question_id).removesuffix(TRACE_SUFFIX)
    pages_dir = request.out_dir / PAGES_DIRNAME
    return [
        _evidence_view(
            evidence,
            _verdict(trace, evidence, unverified),
            pages_dir / f"{stem_base}_{index}",
            request,
        )
        for index, evidence in enumerate(trace.draft.evidence)
    ]


def _verdict(
    trace: QuestionTrace, evidence: Evidence, unverified: set[str]
) -> Verdict:
    if trace.grounding is None:
        return "unchecked"
    return "unverified" if evidence.quote in unverified else "verified"


def _evidence_view(
    evidence: Evidence,
    verdict: Verdict,
    out_stem: Path,
    request: ViewerRequest,
) -> EvidenceView:
    is_verified = verdict != "unverified"
    rendered = _try_render(evidence, is_verified, out_stem, request)
    state: EvidenceState
    if verdict != "verified":
        state = verdict
    elif rendered is None:
        state = "not_rendered"
    else:
        state = "verified" if rendered.is_located else "not_located"
    return EvidenceView(
        doc_id=evidence.doc_id,
        quote=evidence.quote,
        value=evidence.value,
        state=state,
        page=rendered.page if rendered else None,
        crop_image=_relative(
            rendered.crop_path if rendered else None, request
        ),
        full_image=_relative(
            rendered.full_path if rendered else None, request
        ),
    )


def _try_render(
    evidence: Evidence,
    is_verified: bool,
    out_stem: Path,
    request: ViewerRequest,
) -> RenderedLike | None:
    if not request.budget.has_time():
        logger.info(LOG_BUDGET_EXHAUSTED)
        return None
    pdf_path = _corpus_pdf(request.corpus_dir, evidence.doc_id)
    if pdf_path is None:
        logger.warning(LOG_DOC_OUTSIDE_CORPUS, evidence.doc_id)
        return None
    try:
        return request.render(pdf_path, evidence, is_verified, out_stem)
    # The renderer is a boundary: one bad PDF must not stop the page.
    except Exception:  # noqa: BLE001
        logger.warning(
            LOG_RENDER_FAILED, evidence.doc_id, out_stem.name, exc_info=True
        )
        return None


def _corpus_pdf(corpus_dir: Path, doc_id: str) -> Path | None:
    """PDF of a cited doc id, or None when it escapes the corpus."""
    name = f"{normalize_doc_id(doc_id)}{PDF_SUFFIX}"
    root = corpus_dir.resolve()
    pdf_path = (root / name).resolve()
    return pdf_path if pdf_path.is_relative_to(root) else None


def _relative(path: Path | None, request: ViewerRequest) -> str | None:
    if path is None:
        return None
    return path.relative_to(request.out_dir).as_posix()


def _label(question: QuestionView) -> str:
    return question.confidence or CONFIDENCE_UNKNOWN


def _summary(questions: list[QuestionView], is_scored: bool) -> RunSummary:
    by_status: dict[str, int] = {}
    by_confidence = dict.fromkeys(CONFIDENCE_LABELS, 0)
    for question in questions:
        by_status[question.status] = by_status.get(question.status, 0) + 1
        by_confidence[_label(question)] += 1
    return RunSummary(
        total=len(questions),
        by_status=by_status,
        by_confidence=by_confidence,
        accuracy_by_confidence=(
            _accuracy_by_confidence(questions) if is_scored else None
        ),
    )


def _accuracy_by_confidence(
    questions: list[QuestionView],
) -> dict[str, ConfidenceAccuracy]:
    result: dict[str, ConfidenceAccuracy] = {}
    for label in CONFIDENCE_LABELS:
        scored = [
            question
            for question in questions
            if _label(question) == label and question.is_correct is not None
        ]
        if not scored:
            continue
        correct = sum(1 for question in scored if question.is_correct)
        result[label] = ConfidenceAccuracy(
            n=len(scored),
            correct=correct,
            accuracy=round(correct / len(scored), ACCURACY_DECIMALS),
        )
    return result

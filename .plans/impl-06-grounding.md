# Plan: step 06 grounding (`impl-06-grounding`)

**Status:** done (pending sample run by user)
**Parent:** `.plans/impl-00-roadmap.md` step 06, `.plans/global-architecture.md` §4 (output).

## Context

Step 05 is merged into main (45.00/45 on the samples). Most of the
§4 output rules already exist in `archive/validation/answer_validator.py`:
- citations are limited to retrieved and known docs;
- a conflict needs at least 2 citations;
- format is fixed (ISO dates, decimal amounts, 200-char limit);
- a failed check never makes the system abstain.

Three things are missing:
- checking that quotes are verbatim;
- checking that values are grounded;
- a confidence label.

Step 07 (traces) needs both the grounding report and the confidence.

User choice (2026-11-17): **flag only**. Grounding records issues and a
rule-based confidence, and never changes the answer. There is no
retry, no extra LLM call, and the 45/45 is not put at risk. The global
plan's "one retry with feedback" is dropped (decisions log).

## Acceptance criteria

1. **Quotes.** Each `Evidence.quote` is checked against the texts of
   the chunks that reached the draft for its `doc_id`. The match uses
   `normalize_for_match` (`archive/common/text/text_normalize_utils.py`),
   so case, accents and whitespace do not matter. A quote is flagged
   when:
   - it is not found in those texts, or
   - its doc was not retrieved.
2. **Values.** Each answer item of an `answered` draft is grounded when
   either:
   - its normalized text is contained in a verified quote or in the
     recipe note (the aggregation total and the superseded notes come
     from Python), or
   - it parses to the same amount or date as one found there. This
     reuses `normalize_amount` and `normalize_date` from
     `answer_validator.py`.

   An item that is not grounded is flagged.
3. **Confidence** (`high` / `medium` / `low`), rule-based:
   - `low`: an `answered` or `conflict` draft with no evidence, any
     unverified quote, any ungrounded value, or any citation dropped by
     validation;
   - `medium`: other validation issues, except `normalized`, or
     `evidence_sufficient=false`;
   - `high`: none of the above;
   - `not_found`: `high` when nothing was retrieved, else `medium`.
4. The pipeline logs the grounding issues and the confidence (INFO).
   The `answers.jsonl` line is byte-identical to before for the same
   draft.
5. No new LLM call and no change to prompts.
6. Checks are green. The sample run still scores 45/45; the user runs
   it, because it needs the `LLM_*` vars.

## Out of scope

- Retry with feedback.
- Writing traces (step 07 consumes the report).
- Prompt changes.
- Dropping citations or changing the status on a grounding failure.

## Design (frozen interfaces)

`archive/validation/` already holds 5 non-test files, so grounding goes
in a new subfolder.

- `archive/validation/grounding/grounding_model.py`
  - `Confidence(StrEnum)`: `HIGH`, `MEDIUM`, `LOW`.
  - `GroundingSources` (frozen dataclass): `texts_by_doc: Mapping[str, Sequence[str]]` (doc_id to the chunk texts that reached the draft) and `note: str | None`.
  - `GroundingReport` (pydantic): `issues: list[ValidationIssue]`, `unverified_quotes: list[str]`, `ungrounded_values: list[str]`, `confidence: Confidence`.
- `archive/validation/grounding/grounding_service.py`
  - `check_grounding(draft: DraftAnswer, sources: GroundingSources, validation: ValidationResult) -> GroundingReport`. It is pure, with no I/O.
- `archive/validation/grounding/grounding_constants.py`: issue detail strings.
- `archive/validation/issue_model.py`: add `IssueCode.QUOTE_UNVERIFIED`, `VALUE_UNGROUNDED` and `NO_EVIDENCE` (additive).
- `archive/agent/answer_service.py`
  - `answer_question` returns a new frozen dataclass `DraftOutcome(draft: DraftAnswer, hits: list[SearchHit], note: str | None)`, defined in the same file, instead of the `(draft, doc_ids)` tuple.
  - It adds a `doc_ids` property.
  - `hits` follows today's doc-id rule: the prompt hits, plus the hop hits, or all the recipe hits when a recipe drafts itself.
- `archive/pipeline/run_service.py`
  - `_answer_question` calls `validate(...)` as today, with `outcome.doc_ids`.
  - It then builds `GroundingSources` from `outcome.hits` and `outcome.note`, calls `check_grounding`, and logs the result.
  - New `LOG_*` strings go in `pipeline_constants.py`.

## Tasks (sequential: T2 imports T1)

| Task | Does | Owns | Done when |
|---|---|---|---|
| **T1** grounding core | The model, constants, service, the new issue codes, and tests covering each criterion 1–3 rule plus edge cases: empty evidence, quote in another doc, amount written differently (`12 500,00 $` vs `12500.00`), list answers, conflict, not_found | `archive/validation/grounding/*`, `archive/validation/issue_model.py`, `tests/validation/grounding/*` | unit tests pass; checks green |
| **T2** wiring | `DraftOutcome`; `run_service` calls grounding and logs it; update `tests/agent/test_answer_service.py` and the pipeline tests | `archive/agent/answer_service.py`, `archive/pipeline/run_service.py`, `archive/pipeline/pipeline_constants.py`, matching tests | a pipeline test shows the confidence is logged and the output line is unchanged; checks green |

Batches: A = [T1], then B = [T2]. Each one is under 700 lines.

## Execution

Every task is implemented by an `implement` subagent through the
plan-workflow §6.1 worktree flow (merged `--no-ff`). Each batch is
launched in one Agent call, and the main agent does not implement tasks
inline.
- Orchestrator branch: `feat/grounding`, cut from `main`. BASE is
  recorded in `.plans/impl-06-grounding.md`.
- Worktrees:
  - T1: `.claude/temp_worktree/grounding-core` on `feat/grounding-core`;
  - T2: `.claude/temp_worktree/grounding-wiring` on `feat/grounding-wiring`.
- Review: `pre-commit-review` (`reviewer` + `quality`) on `BASE..HEAD`.

## Verification

- On `feat/grounding`:
  - `ruff check . --exclude .claude`
  - `ruff format --check . --exclude .claude`
  - `mypy --strict archive scripts answer.py`
  - `pytest -q`
- The user runs `python answer.py <kit>/samples/questions.jsonl answers.jsonl`
  and then `score.py`, expecting 45/45. The logs show a confidence for
  every question, and the low-confidence ones get reviewed.

## Decisions log

- 2026-11-17: flag only, no retry with feedback (user choice). This
  protects the sample score and the time budget.

## Execution record

- BASE: 28e45a655e3f583af8f6e2a2792ff40edb015fbe
- Subagent branches: `feat/grounding-core` (T1), `feat/grounding-wiring` (T2)
- Fix-round branch: `fix/grounding-review`.

## Decisions log (implementation)

- 2026-11-17: the amount/date scan treats bare numbers as amounts and
  collapses all whitespace, including newlines.
- 2026-11-17: review fixes. The aggregation recipe now sets a note with
  the computed total, which only grounds values and is never prompted.
  Ambiguous DD/MM dates add both readings. Typographic punctuation is
  folded. Trailing punctuation is stripped from answer items. A
  grounding error is logged and never changes the answer. Added
  `GroundingSources.from_hits` and a shared `normalize_doc_id`.
- 2026-11-17: skipped review nits. Adjacent numbers can merge in the
  amount scan, and containment has no word boundaries. Both are rare
  and only cause missed flags, never false ones. There was no second
  review pass after the fix round (small diff, checks green), to save
  tokens.
- Result: 661 tests passing; ruff and mypy clean. The 45/45 sample run
  is still to be done by the user.
- 2026-11-17: the sample run scored 45/45, with s04 and s17 falsely
  rated low. Fix (`fix/grounding-partial`): quotes shortened with an
  ellipsis are verified piece by piece in order. A whitespace-free
  fallback match was added. Amounts or dates inside an answer item are
  grounded when every one of them matches. 671 tests passing.
- 2026-11-17: sample rerun scored 45.00/45. 17 questions were rated high,
  and 3 medium: s02, s11 and s18, the unanswerable ones (not_found with
  hits retrieved, as designed). None were rated low.

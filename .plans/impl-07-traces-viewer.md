# Plan: step 07 traces + click-to-verify viewer (`impl-07-traces-viewer`)

**Status:** done (pending sample run + demo viewer by user)
**BASE:** `4ca11879694d8ee3b12f5ce9360894c514243909` (feat/traces-viewer)
**Subagent branches:** feat/traces-core, feat/viewer-render, feat/viewer-build, feat/viewer-template, feat/viewer-wiring
**Parent:** `.plans/impl-00-roadmap.md` step 07; `.plans/global-architecture.md` §6.

## Context

The free angle is worth 30 jury points and only counts if the score is at
least 22.5/45; the current score is 45/45. Traces on their own read as
debugging tooling. The chosen angle is **"click to verify"**, aimed at a
Brumeval employee who has to decide whether to trust an answer:

- each answer shows the cited PDF page with the quote boxed in a color:
  - green: the quote was verified;
  - red: the quote is not in the document;
  - grey: verified, but the quote could not be located on the page.
- values in the answer that no source supports are listed in amber;
- the confidence badge explains itself ("pourquoi cette confiance");
- a conflict shows the disagreeing documents side by side;
- a not_found shows the documents that were searched.

Step 06 already provides the hard part: `GroundingReport` (verified quotes,
ungrounded values, confidence). This step only records it and makes it
visible. It makes no LLM calls.

Recon facts:
- `pdfplumber.Page.to_image()` takes about 0.27 s per page; each PNG is
  10–25 KB.
- Pillow and pypdfium2 are already dependencies of pdfplumber, so nothing
  new is installed.
- `score.py --json --details` gives `rows[].ok` and `expected_answer` for
  each question.
- `Chunk` has no page number, so the locator searches every page of the
  cited document.

User decisions (2026-11-17):
- the viewer is built **automatically at the end of `answer.py`** (option B),
  with a time guard;
- the demo viewer is committed under `demo/viewer/`;
- the UI is in French;
- trace detail is "medium".

## Acceptance criteria

1. **Traces.** Every question, including invalid ones, failures and those
   with an LLM error, writes `traces/<run_id>/<qid>.json`, where `run_id` is
   a local timestamp `YYYYMMDD-HHMMSS`. A write failure is logged and never
   changes the answer. `answers.jsonl` is byte-identical to before.
2. **Automatic viewer.**
   - After `answers.jsonl` is closed, `run()` builds
     `viewer/<run_id>/index.html` and logs its path.
   - Page images are rendered only until `deadline_s + VIEWER_GRACE_S`
     (90 s), so the whole run stays under 20 min. Past that, cards are
     text only.
   - Any error is logged and ignored; the exit code is unchanged.
   - The browser is never opened automatically.
3. **Rebuild.** `python scripts/build_viewer.py traces/<run_id> [--scores scores.json] [--out DIR]` rebuilds the viewer with no time limit. `--scores` takes the output of `score.py --json --details`, which adds correct/wrong marks and an accuracy-per-confidence table.
4. **Locating quotes.**
   - The quote is matched with the same normalization as step 06
     (`normalize_for_match`, the whitespace-free fallback, the
     `ELLIPSIS_RE` split).
   - Matching works on `page.extract_words()`, with one box per line of
     matched words.
   - The answer value inside a quote gets a stronger box when it is found.
   - If the quote cannot be located, the card shows page 1 and is marked
     "non localisée".
5. **Viewer contents.** One self-contained `index.html` (JSON data inlined,
   vanilla JS and CSS, no CDN), with page images under `pages/`. It shows:
   - a question list with status and confidence chips;
   - a detail view: answer, citations, evidence cards (crop, and the full
     page on click), confidence reasons, amber ungrounded values, dropped
     citations, the recipe note;
   - a side-by-side layout for conflicts;
   - the retrieved documents for not_found;
   - a run summary: counts per status and per confidence, plus accuracy per
     confidence when scores are provided.
6. `viewer/` and `traces/` are gitignored. `demo/viewer/` is committed after
   the user's 20-sample run.
7. Checks are green. The user's sample run still scores 45/45, and every
   sample has a trace and a card.

## Out of scope

- LLM call counting and a timeline of each step.
- A "tamper" mode (done by hand in the demo video).
- Any server, and opening the browser automatically.
- Changing prompts or answers.

## Design (frozen interfaces)

**Agent** (`archive/agent/answer_service.py`): `DraftOutcome` gains
`plan: QuestionPlan | None = None` (additive). `answer_question` fills it in.

**Config** (`archive/common/config.py`): `AppConfig` gains
`traces_dir: Path` (default `<repo>/traces`) and `viewer_dir: Path` (default
`<repo>/viewer`), resolved like `corpus_dir`. Additive.

**Trace** (`archive/pipeline/trace_model.py`, pydantic):
- `RetrievedChunk`: `doc_id`, `chunk_id`, `score`, `doc_type`, `doc_date`.
- `QuestionTrace`, with `trace_version: int = 1`:
  - `run_id`, `question_id`, `question`, `elapsed_s`;
  - `plan: dict | None`, from `QuestionPlan.model_dump` (`family`, filters);
  - `retrieved: list[RetrievedChunk]`, `note: str | None`;
  - `draft: DraftAnswer | None`;
  - `validation_issues: list[str]`, `dropped_citations: list[str]`;
  - `grounding: GroundingReport | None`;
  - `final: FinalAnswer`, `error: str | None`.

**Trace writer** (`archive/pipeline/trace_gateway.py`):
- `TraceWriter(run_dir: Path)` with `write(trace) -> None`.
- It is thread-safe, writes atomically (temp file, then replace), and never
  raises: it logs `LOG_TRACE_WRITE_FAILED` instead.
- `new_run_id(now: datetime) -> str`.

**Pipeline** (`archive/pipeline/run_service.py`):
- `_answer_question` returns the answer together with its trace (built by a
  helper in `archive/pipeline/trace_service.py`, so `run_service` stays
  under 500 lines).
- `_work` writes the trace on every path, error paths included.
- After the answers file is closed, `run()` calls
  `build_viewer(trace_dir, config.corpus_dir, out_dir, ViewerBudget(until_s, clock))` inside a broad try/except that logs `LOG_VIEWER_FAILED`, then logs `LOG_VIEWER_READY` with the path.
- `run()` gains an optional `now: Callable[[], datetime]` so tests are
  deterministic.

**Viewer** (new package `archive/viewer/`, 5 non-test files plus a
`template/` folder):
- `quote_locate_utils.py`: `locate_quote(words: Sequence[Word], quote: str, value: str | None) -> QuoteMatch | None`. `Word` is a frozen dataclass (`text`, `x0`, `top`, `x1`, `bottom`). `QuoteMatch` holds `boxes: list[Box]` and `value_boxes: list[Box]`. Pure, with no pdfplumber import. It reuses `archive/common/text/text_normalize_utils.py::normalize_for_match` and `archive/validation/grounding/grounding_constants.py` (`ELLIPSIS_RE`, `MIN_QUOTE_PIECE_LENGTH`).
- `page_render_gateway.py`: `render_evidence(pdf_path, quote, value, out_dir, stem) -> RenderedEvidence`, which contains `page: int | None`, `crop_path`, `full_path` and `is_located: bool`. It opens the PDF with pdfplumber, tries each page with `locate_quote`, and renders at `VIEWER_DPI` (110). Quote boxes are green or red, value boxes are a strong outline. It saves a crop (box union plus a margin) and the full page.
- `viewer_model.py`: the inlined `ViewerData` (pydantic) that the template reads as `window.VIEWER_DATA`:
  - `run_id`, `generated_at`, `is_scored`;
  - `summary`: `by_status`, `by_confidence`, `accuracy_by_confidence: dict | None`;
  - `questions: list[QuestionView]`. Each has `id`, `question`, `family`, `status`, `answer`, `citations`, `confidence`, `confidence_reasons: list[str]` (French), `ungrounded_values`, `dropped_citations`, `note`, `error`, `elapsed_s`, `is_correct: bool | None`, `expected_answer: str | None`, `retrieved` (doc_id, score, doc_type, doc_date; top 10), and `evidence: list[EvidenceView]`.
  - `EvidenceView`: `doc_id`, `quote`, `value`, `state` (`verified` / `unverified` / `not_located` / `not_rendered`), `page`, `crop_image`, `full_image` (relative paths or null).
- `viewer_build_service.py`:
  - `build_viewer(trace_dir, corpus_dir, out_dir, budget, scores_path=None) -> Path` loads the traces, maps `IssueCode` to French reasons, picks each evidence state, renders images while the budget allows, inlines the JSON into the template, and writes `index.html`.
  - The JSON is escaped for `</script>`.
  - A bad trace file is skipped with a warning.
  - `ViewerBudget(until_s: float | None, clock)`; `None` means no limit.
- `viewer_constants.py`: DPI, colors, crop margin, `VIEWER_GRACE_S`, French labels and issue reasons, the template path, the data placeholder token.
- `template/viewer_template.html`: the HTML, CSS and vanilla JS UI. It contains one placeholder that is replaced by the JSON. Light and dark themes, readable on mobile.
- `scripts/build_viewer.py` (+ `build_viewer_constants.py`): the CLI from criterion 3.

## Tasks

| Task | Does | Owns | Depends on | Done when |
|---|---|---|---|---|
| **T1** traces | `DraftOutcome.plan`, the `AppConfig` dirs, `trace_model`, `trace_gateway`, `trace_service`, trace writing in `run_service`, new `LOG_*` constants, `viewer/` in `.gitignore`, tests | `archive/agent/answer_service.py`, `archive/common/config.py`, `archive/pipeline/*`, `.gitignore`, `tests/pipeline/*`, `tests/agent/test_answer_service.py`, `tests/common/test_config.py` | none | tests show one trace per question on every path (ok, invalid, LLM error, exception), a failed write is non-fatal, the answers line is unchanged; checks green |
| **T2** locate + render | `quote_locate_utils`, `page_render_gateway`, tests (fake words; render test skipped when `corpus/` is absent) | `archive/viewer/quote_locate_utils.py`, `archive/viewer/page_render_gateway.py`, `tests/viewer/test_quote_locate_utils.py`, `tests/viewer/test_page_render_gateway.py` | T1 merged (base) | locates a multi-line quote, an elided quote, a quote with spacing glued together, a value inside a quote; returns None on no match; checks green |
| **T3** build service + CLI | `viewer_model`, `viewer_constants`, `viewer_build_service`, `scripts/build_viewer.py(+constants)`, `archive/viewer/__init__.py`, tests (render faked through an injected function) | those files, `tests/viewer/test_viewer_build_service.py`, `tests/scripts/test_build_viewer.py` | T1; uses the T2 signatures as frozen | builds from fixture traces; budget exhausted gives text-only cards; scores give accuracy per confidence; a bad trace is skipped; checks green |
| **T4** template | `template/viewer_template.html`, which renders the `ViewerData` shape above | `archive/viewer/template/viewer_template.html` | the frozen `ViewerData` shape | opening it with a hand-written sample `ViewerData` shows the list, detail view, conflict and not_found layouts with no console errors |
| **T5** wiring + docs | `run()` calls `build_viewer` after answers close (budget, try/except, ready log); pipeline tests; README "Visualiseur" paragraph | `archive/pipeline/run_service.py`, `archive/pipeline/pipeline_constants.py`, `tests/pipeline/*`, `README.md` | T1–T4 | the pipeline test writes `index.html`; a viewer exception still exits 0; checks green |

Batches:
- A = [T1];
- B = [T2, T3, T4] in parallel (disjoint files; T3 codes against the frozen T2 signatures and does not import a stub);
- C = [T5].

Each task is under 700 lines.

## Execution

Every task is implemented by an `implement` subagent through the
plan-workflow §6.1 worktree flow (merged `--no-ff`). Each batch is launched
in one Agent call, and the main agent does not implement tasks inline.
- Orchestrator branch: `feat/traces-viewer`, cut from `main` (`4ca1187`).
  BASE is recorded in `.plans/impl-07-traces-viewer.md`.
- Worktrees: `.claude/temp_worktree/<slug>`, on branches `feat/traces-core`, `feat/viewer-render`, `feat/viewer-build`, `feat/viewer-template` and `feat/viewer-wiring`.
- Review: `pre-commit-review` (`reviewer` + `quality`) on `BASE..HEAD`. One review pass, to keep usage low.

## Verification

- On `feat/traces-viewer`:
  - `ruff check . --exclude .claude`
  - `ruff format --check . --exclude .claude`
  - `mypy --strict archive scripts answer.py`
  - `pytest -q`
- Orchestrator smoke test with no LLM: a fixture trace dir plus real
  `corpus/` docs through `scripts/build_viewer.py`, then check the rendered
  crops by viewing one PNG.
- The user runs `python answer.py <kit>/samples/questions.jsonl answers.jsonl`:
  45/45 expected, the log prints the viewer path, and there are 20 traces.
  Then `score.py answers.jsonl --json --details > scores.json` and
  `scripts/build_viewer.py traces/<run> --scores scores.json --out demo/viewer`,
  committed.
- Visual check of the demo viewer, using Playwright to screenshot it: the
  green quote on s01, the conflict side by side on s03, the not_found
  documents on s02.

## Decisions log

- 2026-11-17: free angle = "click to verify" viewer, built on the step 06
  grounding (user choice). It replaces plain observability.
- 2026-11-17: the viewer is built automatically at the end of the run with
  a 90 s grace after the global deadline, and is text-only when no time is
  left (user choice B).
- 2026-11-17: correct/wrong marks come from a saved `score.py --json --details` output (`--scores`), so the code does not depend on the kit.
- 2026-11-17: render interface is `render_evidence(pdf_path, evidence, is_verified,
  out_stem)`; the build service consumes it through a Protocol so T2 and T3 ran in
  parallel. `scripts/build_viewer.py` moved from T3 to T5 (needs both).
- 2026-11-17: `.gitignore` `viewer/`/`traces/` anchored to the repo root (the
  unanchored pattern ignored `archive/viewer/`).
- 2026-11-17: review fixes: traces always match the answers line (late, expired
  and never-started questions); trace file names get a short hash on collision
  risk; quote matching shared in `archive/common/text/quote_match_utils.py`;
  evidence doc ids normalized and kept inside `corpus/`; new `unchecked` state
  when grounding crashed; full-width crops; URL hash encoded.
- 2026-11-17: accepted/skipped: `archive/common/text/` holds 6 non-test files
  (one over the limit; split into a subfolder later if touched); unverified
  quotes matched by text, not (doc, text) pairs (needs a step-06 report change,
  rare); render budget checked between evidences only (corpus PDFs ≤ 6.6 KB);
  T3 merge 810 lines (over the 700 soft budget, one cohesive service).

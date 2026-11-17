# Plan: live "ask the archive" server for the viewer (`impl-07b-live-server`)

**Status:** done (pending real-LLM smoke test by user)
**BASE:** `fd950bf7db07cf674848120f3bc5e407b83ff90c` (feat/traces-viewer)
**Subagent branches:** feat/live-engine, feat/live-viewer-api, feat/live-ui, feat/live-server
**Parent:** `.plans/impl-07-traces-viewer.md` (step 07). The work continues on
branch `feat/traces-viewer`, which is not merged into `main` yet.

## Context

The viewer is currently a static file. The user wants it to run on localhost
so that the top bar of their Figma design sends **new questions** to the
system. Each question is answered live, and its verified evidence is shown in
the same UI. This becomes the centre of the free-angle demo.

User decisions (2026-11-17):
- a new command `python scripts/serve.py` serves `http://127.0.0.1:8000`;
- `answer.py` is unchanged and still writes the static viewer, and
  `demo/viewer/` stays committed as an offline fallback for the jury;
- the UI streams the live pipeline steps while a question is being answered;
- questions asked live are saved as traces and appear in the sidebar under
  "Questions posées".

Time: the deadline is 2026-11-18 at 12:00, and REPORT.pdf and the demo video
are still to do. Keep the scope tight: no auth, no multi-user, one question at
a time.

## Acceptance criteria

1. **Startup.** `python scripts/serve.py [--run traces/<id>] [--port 8000]`:
   - checks the `LLM_*` variables with the same error messages as `answer.py`;
   - loads the models and opens the index once;
   - builds the page from the given run (if any) plus the saved live
     questions;
   - prints the URL;
   - binds `127.0.0.1` only.
2. **Ask.** The top bar sends `POST /api/ask` and receives a server-sent
   event stream:
   - `step` events, shown live in a progress panel in French: route, retrieve,
     draft/hop, validate, ground, render;
   - then a `result` event carrying a `QuestionView`, which is added to the
     list under "Questions posées" and selected;
   - an `error` event shows a French message, and the UI stays usable.
3. **One at a time.** A second ask while one is running gets `409` with a
   French message.
4. **Input checks.** An empty question, or one over 500 characters, gets
   `400`. Static paths are restricted to the viewer folder, so `../` is
   refused.
5. **Persistence.** Live questions are saved in `traces/live/live-NNN.json`,
   and their images are rendered into the server's viewer folder. They are
   reloaded on restart.
6. **Static mode unchanged.** Opened from `file://` (or with `live=false`),
   the top bar is still a search box, and `answer.py` output is
   byte-identical.
7. Checks are green; a server smoke test is done with the real LLM by the
   user; the sample run still scores 45/45.

## Out of scope

Auth, CORS, several users, cancelling a running question, deployment.

## Design (frozen interfaces)

**Steps** (`archive/common/step_model.py`, new):
- `PipelineStep(StrEnum)`: `ROUTE`, `RETRIEVE`, `DRAFT`, `HOP`, `VALIDATE`,
  `GROUND`, `RENDER`.
- `StepEvent` (frozen dataclass): `step`, `detail: str | None`.
- `StepCallback = Callable[[StepEvent], None]`.
- `archive/agent/answer_service.py::answer_question` gains
  `on_step: StepCallback | None = None` (additive). It emits:
  - ROUTE with the family;
  - RETRIEVE with the hit count and recipe;
  - DRAFT with the draft number;
  - HOP with the `missing` text.

**Engine** (`archive/pipeline/engine/engine_service.py`, new subfolder,
because `archive/pipeline/` already holds 5 files):
- `Engine` (frozen dataclass): `search`, `llm`, `valid_doc_ids`, `config`.
- `open_engine(config) -> ContextManager[Engine]` holds today's startup from
  `run_service.run`: `_load_models`, `_sync_index_or_continue`,
  `SearchService.open` and `_valid_doc_ids`, with the same errors.
- `answer_one(question, engine, on_step=None) -> AnswerParts` holds today's
  `_answer_question` plus grounding. It emits VALIDATE and GROUND.
- `run_service` uses both, with no behavior change.

**Viewer** (`archive/viewer/*`):
- `ViewerData.live: bool = False`; `QuestionView.is_live: bool = False`.
- `ViewerRequest.extra_trace_dirs: tuple[Path, ...] = ()`. Traces loaded from
  those directories get `is_live=True`.
- `build_viewer(...)` sets `live` from a new `ViewerRequest.live: bool = False`.
- New public `question_view_from_trace(trace, request) -> QuestionView`, which
  renders the images of a single trace (it reuses `_question_view`).
- A new inline asset token `/*__VIEWER_LIVE__*/` maps to
  `template/viewer_live.js`.

**Server** (`archive/server/`, new):
- `server_model.py`: the request and event shapes:
  - `AskRequest{question}`;
  - SSE `step` `{step, label, detail, elapsed_s}`;
  - `result` `{question: QuestionView}`;
  - `error` `{message}`.
- `ask_service.py`: `AskService(engine, viewer_request, traces_dir)`:
  - `ask(text, emit) -> QuestionView` under a lock (`BusyError` when one is
    already running);
  - it gives the next `live-NNN` id, calls `answer_one(on_step)`, writes the
    trace with `TraceWriter`, and renders the images through
    `question_view_from_trace` (emitting RENDER).
- `server_gateway.py`: a stdlib `ThreadingHTTPServer` with these routes:
  - `GET /` serves index.html;
  - `GET /pages/<file>` serves images, path-safe;
  - `GET /api/health` returns `{ready, busy}`;
  - `POST /api/ask` streams `text/event-stream`, with the body capped.
- `server_constants.py`: host, port, limits, French step labels, messages.
- `scripts/serve.py` + `serve_constants.py`: the CLI.

**Navigation** (user request, 2026-11-17, owned by the UI task):
- **Home view:** right below the top bar, the main column lists all the cases
  (questions):
  - each row shows the id, the question, the status, the confidence, and ✓/✗
    when scored;
  - the run summary (counters, accuracy per confidence) sits above the list.
- **Filters:** the existing sidebar filter area keeps its current look
  exactly: same nav items, chips and text filter. Today the filters seem to
  do nothing, because they only filter the small list in the right rail. They
  must now visibly filter the home list, with live counts and an empty state
  ("Aucun cas ne correspond" plus "Réinitialiser les filtres"). If the
  selected case is filtered out, the view returns to the list. Check every
  filter combination.
- **Detail view:** shown only when a case is selected. It has the current
  content (answer, notices, evidence, tabs) and a "← Tous les cas" back
  button, with previous/next and arrow keys kept.
- **URL hash:** an empty hash shows the list, and `#<id>` shows that case, so
  the browser back button works.
- **Live questions:** a live question opens in the detail view once it is
  answered, and appears in the list under "Questions posées".

**Template** (owned by the UI task):
- `viewer_live.js`: when `VIEWER_DATA.live` is set, the top bar submits to
  `/api/ask`. It reads the SSE stream with `fetch` and a `ReadableStream`.
- The progress panel shows a checklist of steps with timings.
- On `result`, the question is pushed into the questions array, the list is
  re-rendered and the question is selected. It is grouped under "Questions
  posées".
- It handles 409, 400 and errors with toasts.
- Small hooks in `viewer_app.js`, `viewer_template.html` and
  `viewer_styles.css` expose `render`/`select`, and add the panel and the
  group.

## Tasks

| Task | Does | Owns | Done when |
|---|---|---|---|
| **T1** engine + steps | the step model; `answer_question(on_step)`; `pipeline/engine/engine_service.py`; `run_service` refactored onto it | `archive/common/step_model.py`, `archive/agent/answer_service.py`, `archive/pipeline/engine/*`, `archive/pipeline/run_service.py`, `tests/agent/test_answer_service.py`, `tests/pipeline/**` | existing pipeline tests unchanged and green; the engine and steps are tested with fakes |
| **T2** viewer API | the `live`/`is_live` fields, `extra_trace_dirs`, `question_view_from_trace`, the live asset token | `archive/viewer/*.py`, `tests/viewer/test_viewer_build_service.py` | tests cover the live flags, extra dirs and the single-trace view |
| **T3** live UI + navigation | the list-first home view and the detail-on-select view with its filters (see Navigation); `viewer_live.js` plus the hooks, against the frozen SSE contract; checked with a tiny fake SSE server script in temp and Playwright | `archive/viewer/template/*` | screenshots show the home list being filtered by each sidebar filter (sidebar look unchanged), the detail after a click with back working (button and browser), the steps streaming, the result added and opened, 409 and error toasts, static mode working, 390 px mobile, no console errors |
| **T4** server + CLI + docs | `archive/server/*`, `scripts/serve.py(+constants)`, tests with a fake engine (SSE format, 409, 400, path traversal, persistence reload); README "Mode interactif" section | those files, `tests/server/**`, `tests/scripts/test_serve.py`, `README.md` | the tests pass; a local run with a fake engine streams steps |

Batches:
- A = [T1, T2, T3] in parallel (disjoint files);
- B = [T4], which depends on the T1 and T2 interfaces.

## Execution

Every task is implemented by an `implement` subagent through the
plan-workflow §6.1 worktree flow (merged `--no-ff`). Each batch is launched
in one Agent call, and the main agent does not implement tasks inline.
- Orchestrator branch: `feat/traces-viewer`. BASE is `fd950bf`, recorded in
  `.plans/impl-07b-live-server.md`.
- Branches: `feat/live-engine`, `feat/live-viewer-api`, `feat/live-ui`,
  `feat/live-server`.
- Review: `pre-commit-review` (`reviewer` + `quality`) on `BASE..HEAD`. One
  pass.

## Verification

- Full checks on the branch:
  - `ruff check . --exclude .claude`
  - `ruff format --check . --exclude .claude`
  - `mypy --strict archive scripts answer.py`
  - `pytest -q`
- The user runs `python scripts/serve.py` with the `LLM_*` variables set and
  asks 2 or 3 questions, including one conflict and one with no answer. Steps
  stream, the cards show the green crops, and the questions are still listed
  after a restart.
- The user's sample run with `answer.py` still scores 45/45.

## Decisions log

- 2026-11-17: live server via stdlib `http.server` + SSE (no new dependency);
  the static viewer is kept as the offline fallback (user choices).
- 2026-11-17: navigation changed to list-first (home lists all cases, detail on
  select); sidebar filters keep their look but now filter the home list (user).
- 2026-11-17: review fixes: localhost-only requests (Host/Origin checks, JSON
  content type, 30 s socket timeout); result sent before a background,
  coalesced page rebuild; atomic index.html; live ids never reused; engine
  startup I/O errors reported as index errors; shared `has_pdfs`/startup
  helpers and `LOG_FORMAT`; `viewer_app.js` split (`viewer_list.js`).
- 2026-11-17: accepted: rebuild re-renders every image (fine for a demo-sized
  run); rebuild thread is a daemon; several commits over the 200-line budget
  (new files with their tests).
- 2026-11-17: (user request) record the pipeline steps in every trace and show
  them as a "Déroulement" timeline under the answer. Frozen: `StepRecord{step,
  detail, elapsed_s}` in `QuestionTrace.steps` (default empty);
  `QuestionView.steps: list[StepView{step, label, detail, elapsed_s}]`; French
  labels shared from `archive/common/step_constants.py`. Branches
  `feat/trace-steps` (Python) and `feat/steps-timeline` (template).

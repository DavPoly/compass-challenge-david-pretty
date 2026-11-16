# Step 01: walking skeleton

**Status:** in-progress
**Parent:** [impl-00-roadmap.md](impl-00-roadmap.md), [global-architecture.md](global-architecture.md)
**Orchestrator branch `B`:** `feat/skeleton` (cut from `main`)
**BASE:** `bb65fa4c4855a1b2328605f3b6ceec1510f1b457`
**Subagent branches:** `chore/tracer` (T0, merged), `feat/ingest-text` (T1, merged), `feat/llm-gateway` (T2, merged), `feat/validation` (T3, merged), `feat/retrieval-index` (T4, merged), `feat/agent-runner` (T5, merged); review fix round 1: `fix/run-exit`, `fix/llm-repair`, `fix/validation-formats`, `fix/index-integrity`

## Goal

A thin end-to-end path through every module that scores above zero:
parse, chunk, BM25-only index, one `draft` LLM call, schema + format
validation, `answers.jsonl`. Later steps upgrade each layer behind the
interfaces frozen here.

## Acceptance criteria

- `python answer.py <kit>/samples/questions.jsonl answers.jsonl` runs end
  to end on the committed index. Each line has exactly `id`, `answer`,
  `citations`, `status`, and every cited id exists in `corpus/`.
- A missing `LLM_*` variable, questions file or `corpus/` makes the program
  exit 1 with a message that names the problem and the fix.
- The run on the 20 samples, scaled to 60 questions, takes under 10 min.
- `ruff check`, `ruff format --check`, `mypy --strict archive scripts` and
  `pytest` pass.
- `score.py --details` baseline is recorded in the decisions log.

## Out of scope (later steps)

Tables and number/date normalization (02), dense vectors and reranking (03),
router and recipes (04), ReAct (05), grounding and the conflict rule (06),
traces (07), report (08).

## Design

### Frozen interfaces

See the table in [impl-00-roadmap.md](impl-00-roadmap.md). Step-01 details:

- `AppConfig` (`archive/common/config.py`): `llm_base_url`, `llm_api_key`,
  `llm_model`, `corpus_dir`, `index_dir`; `from_env()` raises `ConfigError`.
- `Chunk` (`archive/common/chunk_model.py`): pydantic model, fields per the
  roadmap. Version fields stay `None` in step 01.
- `parse_pdf(path) -> ParsedDoc` (`archive/ingest/pdf_parse_gateway.py`):
  `doc_id`, `pages: list[str]` (pdfplumber text only).
- `normalize_text(text) -> str` (`text_normalize_utils.py`): NFKC,
  NBSP/thin spaces to spaces, whitespace collapse. Accent folding happens
  only in `normalize_for_match(text) -> str`, used for tokens.
- `chunk_document(doc, metadata) -> list[Chunk]` (`chunking_service.py`):
  one chunk below ~800 tokens; above that ~400-token chunks with 50 overlap.
- `extract_metadata(doc) -> DocMetadata` (`metadata_service.py`): regex
  identifiers (`F-YYYY-NNNN`, `C-YYYY-NN`, `BRV-YYYY-NN`, emails, tolerant
  of OCR-like typos), first date found as `doc_date`, `lang` by stopword
  count, `doc_type="unknown"` until step 02.
- `sparse_vector(text) -> SparseVector` (`archive/retrieval/qdrant_gateway.py`):
  in-house tokenizer (`normalize_for_match`, split, FR+EN stopwords from
  constants), stable hash to indices, term-frequency values; Qdrant applies
  `Modifier.IDF`.
- `QdrantGateway`: `open(index_dir)`, `ensure_collection()`,
  `upsert(chunks)`, `query_sparse(vector, filter, k)`,
  `scroll(filter, cap)`; one shared client with a write lock.
- `search_service`: `hybrid_search` (sparse only here; identifiers found in
  the question become a payload filter, with a retry without the filter if
  it returns nothing) and `list_by_filter`.
- `index_builder_service.build(corpus_dir, index_dir)`: parse, chunk,
  upsert, write `index/manifest.json` (`doc_id → size, sha1`).
- `LlmGateway(config).complete_json(messages, schema)`: `openai` SDK,
  `response_format` json_schema, JSON-in-text fallback, one repair
  re-prompt; retries timeouts/429/5xx with exponential backoff and jitter,
  honoring `Retry-After`.
- `input_model.load_questions(path) -> list[Question]`: a bad line becomes
  a `Question` flagged invalid, with a warning, and later a `not_found`
  answer.
- `answer_validator.validate(draft, retrieved_doc_ids, known_doc_ids) ->
  ValidationResult`: schema, citations ⊆ retrieved ∩ known (others dropped),
  ISO dates, decimal amounts, answer < 200 chars, list for multi-item.
  It never turns an answer into an abstention.
- `draft_service.draft(question, hits, llm) -> DraftAnswer`: top ~8 chunks
  wrapped in untrusted-data delimiters, prompt from `prompt_constants.py`.
- `run_service.run(...)`: loads questions, thread pool, 60 s per question,
  17 min global deadline. Writes each answer line as soon as it is ready.
  On timeout or `LlmUnavailableError` it writes `not_found` with no
  citations.

### Data flow

`answer.py` → `AppConfig.from_env()` → `run_service.run` → per question:
`hybrid_search` → `draft` → `validate` → `FinalAnswer` → `answers.jsonl`.
Offline: `scripts/build_index.py` → `index_builder_service.build` →
`index/qdrant/` + `index/manifest.json` (committed).

### Files

```
pyproject.toml, requirements.txt, requirements-dev.txt, .gitignore, answer.py
archive/common/      config.py, constants.py, chunk_model.py
archive/ingest/      pdf_parse_gateway.py, text_normalize_utils.py,
                     chunking_service.py, metadata_service.py,
                     index_builder_service.py
archive/retrieval/   qdrant_gateway.py, search_service.py
archive/llm/         llm_gateway.py
archive/validation/  input_model.py, answer_model.py, answer_validator.py
archive/agent/       draft_service.py, prompt_constants.py
archive/pipeline/    run_service.py
scripts/             build_index.py
tests/               mirrored tree (tests/<pkg>/test_<module>.py)
index/               qdrant/, manifest.json
```

Each package keeps its constants in its own `*_constants.py` when it needs
any (code-quality §4). Shared constants go in `archive/common/constants.py`.

## Tasks

| Task | What | Owns | Parallel | Depends on | Done when |
|---|---|---|---|---|---|
| T0 tracer | Tooling (ruff, mypy strict, pytest in `pyproject.toml`), pinned `requirements*.txt`, `.gitignore` (`.lock`, `traces/`, `corpus/`), `archive/common/*`, minimal `pdf_parse_gateway`, `qdrant_gateway` (sparse only). Spike: index 30 docs, query one known code. | `pyproject.toml`, `requirements*.txt`, `.gitignore`, `archive/common/*`, `archive/ingest/pdf_parse_gateway.py`, `archive/retrieval/qdrant_gateway.py`, their tests | no | none | a test queries a code and gets the right doc; all checks pass |
| T1 ingest | normalize, chunking, metadata | `archive/ingest/{text_normalize_utils,chunking_service,metadata_service}.py` + tests | yes (A) | T0 | unit tests cover edge cases: empty doc, typo'd codes, FR/EN text, chunk boundaries |
| T2 llm | `LlmGateway` | `archive/llm/*` + tests | yes (A) | T0 | mocked tests cover 429 + `Retry-After`, timeout, 5xx, bad JSON then repair, repair failure |
| T3 validation | input + answer models, validator | `archive/validation/*` + tests | yes (A) | T0 | tests cover bad question line, unknown or unretrieved citation, format rules, no forced abstention |
| T4 retrieval + index | `search_service`, `index_builder_service`, `scripts/build_index.py`, full build committed in `index/` | those files, `index/**`, tests | no (B) | A | full corpus indexed; `storage.sqlite` < 100 MB; codes from 5 sample questions hit their gold doc in the top 8 |
| T5 agent + runner | `draft_service`, `prompt_constants`, `run_service`, `answer.py` | those files + tests | no (C) | B | mocked-LLM end-to-end test writes valid lines; exit-1 paths tested |
| V verify | Run on `B` (no edits): sample command with real LLM, `score.py --details`, wall time | none | — | C | baseline score and time recorded below |

Batches: **T0** → **A = {T1, T2, T3}** (one Agent call) → **B = {T4}** →
**C = {T5}** → **V**. Each task stays under 700 merged lines; T4 excludes
the binary index from that count.

## Execution

Every task is implemented by an `implement` subagent via the plan-workflow
§6.1 worktree flow (`.claude/temp_worktree/<slug>` on `<type>/<slug>`, cut
from `B`, merged back `--no-ff`). Each batch is launched in one Agent call.
The main agent does not implement tasks inline; it only orchestrates,
merges and updates this file. After V, the `pre-commit-review` skill runs
the `reviewer` and `quality` subagents on `BASE..HEAD`. Fix rounds go
through `implement` subagents with new slugs, capped at about two cycles.

Environment: the orchestrator creates the main-checkout venv once, before
T0, with Python 3.11 (`py -3.11 -m venv .venv`). Subagent check commands use
the absolute path to that venv's python. The fresh worktree has no `corpus/`,
so tests needing PDFs read from the kit's
`c:/Users/david/Dev/compass-challenge-kit/corpus`, passed in as a path.

## Verification

- Per task: the "done when" tests, plus `ruff check`,
  `ruff format --check`, `mypy --strict archive scripts` and `pytest` in the
  worktree.
- Whole step: V on `B` with the real LLM (OpenRouter, env vars set by the
  user). Then the four robustness checks: a missing env var, a missing
  questions file, a missing `corpus/`, and a malformed questions line.

## Decisions log

- 2026-11-16: the sparse vectors come from an in-house tokenizer with
  Qdrant `Modifier.IDF`, not fastembed BM25. Reason: no model download, no
  onnxruntime in step 01, and the stopword config stays committed (the global
  plan's intent). Step 03 adds fastembed for dense vectors only.
- 2026-11-16: Python 3.11 dev venv (eval minimum; avoids missing 3.14 wheels).
- 2026-11-16 (T0): sparse values use BM25-style TF saturation
  (`tf*(k1+1)/(tf+k1)`, k1=1.2); raw TF ranked a doc repeating "2023"
  above the doc holding `BRV-2023-11`. Hyphenated codes are indexed whole
  and as parts.
- 2026-11-16: `archive/ingest/` will already hold 5 modules after T4, so
  T1's constants go in `archive/common/constants.py` (T1 is its only
  owner in batch A) rather than a sixth `ingest_constants.py`.
- 2026-11-16 (T1): no identifier typos found in ~760 scanned PDFs; typos
  sit in prose (month names matched with difflib, cutoff 0.8). The parser
  stays tolerant anyway. The first 200 docs are all single-chunk.
- 2026-11-16 (T2): `LlmResponseError` subclasses `LlmUnavailableError`.
  Worst-case retries (5 × 45 s) exceed the 60 s question budget; T5 must
  bound each call by the remaining question time.
- 2026-11-16 (T3): merge was 798 lines (≈400 tests), over the soft 700
  budget, merged anyway. `validate` takes `question_id` as a first
  argument. score.py facts: false abstention costs 0.17 extra; any invalid
  cited id zeroes that question's citation score; over-citing is
  penalised by `(len(gold)+1)/len(cited)`; money tolerance 0.5%; gold
  `not_found` answer is `""`.
- 2026-11-16 (T4): full build 83 s on 22 cores, 3,048 docs, 3,048 chunks
  (all single-chunk), 0 failures, `storage.sqlite` 14.2 MB. Date filters
  use Qdrant `DatetimeRange` on the ISO string. Reads are serialised by a
  lock. Retrieval baseline on the 17 samples with gold citations: mean
  gold-doc recall@8 = 0.67, ≥1 gold doc in top 8 for 15/17; s01 and s12
  (policy/superseded, no code) miss entirely; s20 = 0.06 (aggregation).
- 2026-11-16 (T5): merge was 940 lines (≈480 tests), over the soft 700
  budget, merged anyway. LLM budget retuned: 12 s request timeout, 3
  attempts, backoff cap 4 s, Retry-After cap 8 s → one request chain
  ≤ 52 s; a repair chain can still overrun, and the runner's 60 s budget
  then writes `not_found`. Lines are written in completion order;
  duplicate question ids keep the first occurrence.
- 2026-11-16: V is blocked on the user's `LLM_*` variables, so the
  pre-commit review runs before V instead of after.
- 2026-11-16 (fix round 1): every regression test mutation-verified —
  fails with its fix reverted. run-exit finished two broken edits:
  DOCUMENT_TAG_ESCAPE needs a double backslash (r"<\\document") and
  the tag regex needs re.IGNORECASE; tests/agent/test_draft_service.py
  joined run-exit's owned set as the only home for the tag tests.
- 2026-11-16 (fix round 1): amounts round half up (0.125 $ → 0.13) via
  AMOUNT_ROUNDING/_format_amount, inferred from required behaviour;
  drop AMOUNT_ROUNDING if the scorer proves half-even.
- 2026-11-16 (fix round 1): index-integrity renamed
  test_tracer_spike.py → test_sparse_code_ranking.py (30-PDF ranking
  probe) and took tests/retrieval/test_search_service.py into its
  owned set for the open/close-on-failure tests.
- 2026-11-16 (fix round 1): slices committed as 309/261/325/382 lines,
  all over the 200-line soft commit budget with no clean split; merged
  --no-ff as 595ac80/92eb544/6975a53/44a89b7, all checks green
  (223 tests) on feat/skeleton.

## Resume point (2026-11-16, fix round 1 complete)

T0–T5 and fix round 1 merged on `feat/skeleton` (tip 44a89b7; 223
tests, ruff + format + mypy --strict green). Fix round 1 slices:
run-exit (e238715), llm-repair (3d08ba2), validation-formats (edfea51),
index-integrity (2b4aee1); worktrees and branches removed, nothing
pushed. Next:
- Round 2: unify month tables/date parsing and accent stripping,
  move text normalize utils to `common/`, split `common/constants.py`.
- Pre-commit review on BASE bb65fa4..HEAD (fix rounds capped at ~2).
- V still pending: needs the user's `LLM_*` variables.

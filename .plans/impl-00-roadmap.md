# Implementation roadmap: "Ask the Archive"

**Status:** approved
**Parent:** [global-architecture.md](global-architecture.md) (architecture,
constraints, decisions). This file only splits that plan into steps.
**Deadline:** Wed 2026-11-18, 12:00 (last commit counts).

## Approach

Skeleton first: step 01 builds a thin end-to-end path that scores above zero.
Every later step upgrades one layer behind interfaces frozen in step 01. Each
step gets its own detailed plan (`impl-<nn>-<step>.md`) written when the step
starts, using what earlier steps measured. Only `impl-01-skeleton.md` is
detailed up front.

Every step follows plan-workflow: `implement` subagents in the §6.1 worktree
flow (merged `--no-ff`), one Agent call per parallel batch, no inline
implementation by the main agent, then `pre-commit-review` (`reviewer` +
`quality`).

## Cross-step interfaces (frozen in step 01, only extended later)

Later steps may add optional fields or new functions. They never rename or
remove what is listed here without a decisions-log entry in this file.

| Interface | File | Contract |
|---|---|---|
| `Chunk` | `archive/common/chunk_model.py` | `doc_id`, `chunk_id`, `chunk_kind` (`text`/`table`), `doc_type`, `doc_date` (ISO or None), `identifiers`, `lang`, `text`; optional `version`, `effective_from`, `effective_to` |
| `SearchFilters`, `SearchHit` | `archive/retrieval/search_service.py` | `SearchHit(chunk: Chunk, score: float)`; filters on identifiers, doc types, date range |
| `hybrid_search(query, filters, k)` | `archive/retrieval/search_service.py` | ranked `list[SearchHit]` (BM25-only in 01, hybrid + rerank from 03) |
| `list_by_filter(filters, cap)` | `archive/retrieval/search_service.py` | exhaustive, unranked `list[SearchHit]` |
| `LlmGateway.complete_json(messages, schema)` | `archive/llm/llm_gateway.py` | returns a validated pydantic instance; retries, backoff, one repair re-prompt; raises `LlmUnavailableError` |
| `DraftAnswer`, `FinalAnswer` | `archive/validation/answer_model.py` | draft = global plan §3 shape; final = exactly `id`, `answer`, `citations`, `status` |
| `run(questions_path, answers_path, config)` | `archive/pipeline/run_service.py` | returns the process exit code |
| `AppConfig.from_env()` | `archive/common/config.py` | raises `ConfigError` naming every missing variable |

## Steps

| # | Plan file | Scope (global plan §) | Depends on | Done when |
|---|---|---|---|---|
| 01 | `impl-01-skeleton.md` | Tooling, pinned deps, config, pdfplumber text, simple chunking, regex identifiers, Qdrant embedded sparse-only index with identifier filters, one `draft` call, schema + format validation, thread-pool runner with deadlines, committed index (§1–6, thin) | none | standard command runs on the 20 samples; baseline score recorded |
| 02 | `impl-02-ingest-quality.md` | Tables via `find_tables` as own chunks with context header; FR/EN number and date normalization; `doc_type` detection; version metadata (`version`, `effective_from/to`); startup manifest diff with incremental upsert; table-detection check on 30 docs (§1) | 01 | 30-doc table check measured; a new PDF in `corpus/` is indexed at startup; no score regression |
| 03 | `impl-03-dense-rerank.md` | e5-large dense vector via fastembed, download timeout + BM25 fallback; RRF fusion; reranker latency measured then chosen (jina vs bge, licence checked); `storage.sqlite` size check; startup index check (§2) | 01; parallel with 02 (disjoint files, single re-index after both) | hybrid + rerank ≥ BM25-only score; 60 questions fit the time budget |
| 04 | `impl-04-router-recipes.md` | Regex route; `scripts/generate_router_set.py` + committed training set; e5 classifier with LLM fallback; recipes direct, aggregation (`list_by_filter` + exact-decimal `calculate`), superseded (§3 route, retrieve) | 03 | aggregation and superseded samples improve |
| 05 | `impl-05-react-safety-net.md` | ReAct loop (≤ 3 calls), pydantic tool args with errors fed back; `evidence_sufficient=false` re-route; per-question and global budgets (§3 safety net, budgets; §4 tool input) | 04 | multi_hop samples improve; budgets hold under a mocked slow LLM |
| 06 | `impl-06-grounding.md` | Verbatim quotes, value grounding, citations limited to retrieved docs, conflict rule, one retry with feedback, rule-based confidence, never abstain on validation failure (§4 output) | 01; parallel with 02–05 while it only touches `archive/validation/` | conflict and unanswerable samples get correct statuses |
| 07 | `impl-07-traces-viewer.md` | `trace_gateway` writing `traces/<run>/<qid>.json`; small demo viewer (free angle) (§6) | 05, 06 | every sample has a trace; viewer renders them |
| 08 | `impl-08-hardening-report.md` | Clean-venv install; robustness runs (env, corpus, 429, new PDF, blocked model download); `scripts/evaluate.py`; README; REPORT.pdf with error analysis and demo link (global Verification) | all | README checklist met; REPORT.pdf ≤ 2 pages; final score recorded |

## Suggested order

```
01 ─► 02 ┐
   ├► 03 ┴► 04 ─► 05 ┐
   └► 06 ────────────┴► 07 ─► 08
```

## Priority cut line

- **Must-have:** 01, 02, 03, 06, 08. The 22.5/45 threshold gates the free
  angle, and REPORT.pdf decides whether the system is run at all.
- **Score gains:** 04, 05.
- **Free angle:** 07.
- Start 08 by the evening of 2026-11-17 at the latest, whatever is
  unfinished. Unfinished steps go in the report as accepted risks.

## Risks

- Local default Python is 3.14; onnxruntime/fastembed wheels may be missing.
  Development uses a Python 3.11 venv (installed), which is also the eval
  minimum.
- Every index rebuild must be re-committed, and the index must match the
  pinned qdrant-client/pydantic versions.
- Re-indexing is serial work: steps 02 and 03 share a single rebuild.

## Decisions log

- 2026-11-16: skeleton-first ordering; only step 01 is detailed up front.
- 2026-11-16: `Chunk` lives in `archive/common/chunk_model.py` (third file in
  `common/`), because both ingest and retrieval depend on it.
- 2026-11-17: step 04 routes with regex plus one LLM plan call; the
  local classifier and its generated training set were dropped to save
  time before the deadline. Score 35.64/45 after step 04.
- 2026-11-17: step 05 replaces the LLM tool-calling ReAct loop with
  identifier expansion plus a draft loop driven by `missing` (at most 3
  drafts, 30 s hop budget) and a one-hop safety net for direct
  questions. Score 45.00/45 on the samples after step 05.

# Global architecture plan: "Ask the Archive" (Compass challenge)

**Status:** approved (architecture only; no implementation in this plan)
**Next step:** break this into implementation steps, each with its own
implementation plan (`.plans/impl-<nn>-<step>.md`) that references this one.
**Repo:** `../compass-challenge-david-pretty` (sibling of the kit, built from `starter/`)

## Context

The Compass kit (`c:/Users/david/Dev/compass-challenge-kit`) holds 3,048
synthetic PDFs (~2M tokens, 2× the eval model's context) for the fictional
firm Brumeval: invoices FR/EN (`F-YYYY-NNNN`), contracts (`C-YYYY-NN`), project
sheets (`BRV-YYYY-NN`), monthly reports, minutes, versioned policies, a staff
directory, emails and newsletters. The documents contain typos, even in headers,
and mixed number and date formats. The system answers questions, cites doc ids,
and returns `not_found` or `conflict` when it should.

Scoring: `score.py` gives 45 pts on 60 secret questions from the same families
as `samples/` (direct, multi_hop, aggregation, superseded, conflict,
unanswerable). The jury gives 25 pts for architecture and report and 30 pts for
the free angle.

Hard constraints:
- The run must finish in 20 min (install excluded).
- The hosted LLM is reachable **only** through `LLM_BASE_URL`, `LLM_API_KEY`
  and `LLM_MODEL` (OpenAI-compatible, Haiku-class).
- The eval machine is a standard CPU with no GPU. Install is `pip install`
  only, so no Docker.
- `corpus/` is replaced before the run, and `answers.jsonl` has exactly
  `id`, `answer`, `citations` and `status`.

Recon facts:
- pypdf takes ~0.17 s/doc, so the index must be prebuilt and committed.
- SQLite 3.50 is available.
- 11/20 sample questions contain an exact code and 6 more name an entity, so
  lexical matching is essential.

## Architecture overview

```
answer.py (CLI) ─► pipeline.run_service ─► per question (thread pool):
  route ─► retrieve(recipe) ─► rerank ─► draft (1 LLM call) ─► validate
                 ▲                                      │
                 └──── ReAct fallback (≤3 calls) ◄──────┘ if evidence_sufficient=false
                                                         (max 1 re-route, 1 retry)
```

### 1. Ingest (offline build + incremental at startup)
- **Parser:** pdfplumber (MIT). It finds tables with `find_tables` (lines,
  then text strategies) and separates them from prose by bounding box. A
  validation step on ~30 docs (invoices, project sheets, directory) measures
  table detection. Fallback: parse the "Label  Value" key/value lines.
- **Chunking:** a doc's prose under ~800 tokens is one text chunk. Above
  that, it is split on numbered section headings, then by size (~400 tokens,
  50 overlap). Tables are always their own chunk, and each table chunk carries
  a context header (doc title, doc_id, main identifier, date).
- **Payload metadata per chunk:** `doc_id`, `chunk_id`, `chunk_kind`
  (`text|table`), `doc_type`, `doc_date` (ISO), `identifiers` (F-/C-/BRV-
  codes, emails), `lang`. Versioned docs also get `version`,
  `effective_from`, and `effective_to` (computed from the next version).
- **Normalization:** accents, NBSP and thin spaces, case, and FR/EN
  number and date formats.
- **Extensibility:** a manifest `doc_id → size + sha1`. At startup the code
  diffs it against `corpus/` and parses, embeds and upserts only new or
  changed docs.

### 2. Index and retrieval: Qdrant embedded mode
- `qdrant-client` in local path mode (`index/qdrant/`, committed), the same
  in dev and eval. One collection holds a named dense vector plus a sparse BM25
  vector (`Modifier.IDF`).
- **Dense:** `intfloat/multilingual-e5-large` (1024-d) through fastembed (ONNX,
  CPU), downloaded at startup with a timeout and not committed. If the
  download fails, search falls back to BM25 only and logs a clear warning.
- **Sparse:** fastembed BM25 with no stemming and a combined FR+EN stopword
  list. Its config is committed, so it needs no download.
- **Hybrid search:** dense and sparse prefetch, fused with RRF. Identifiers
  detected in the question also become payload filters.
- **`list_by_filter`:** an exhaustive, unranked scroll on `doc_type`,
  `identifiers` and date range (cap ~60) for aggregation.
- **Reranker:** a CPU cross-encoder on the top 30–50 hybrid hits.
  Preferred: `jinaai/jina-reranker-v2-base-multilingual`, if its CC-BY-NC
  licence is acceptable. Otherwise `BAAI/bge-reranker-v2-m3`. The final pick
  depends on measured latency.
- **Mitigations:**
  - exact version pins for qdrant-client and pydantic (the storage is pickled);
  - a startup check that the index opens, with an explicit error and no silent
    rebuild;
  - a size check that keeps `storage.sqlite` under 100 MB;
  - one shared client with a write lock;
  - `.lock` in `.gitignore`.

### 3. Agent: lean bounded graph (plain Python state machine, no framework)
- **route (0 LLM calls):**
  - regex for codes, dates and "as of" constraints;
  - a local classifier on the e5 embeddings for question family and answer
    type, trained on ~50 synthetic questions per family generated offline with
    Haiku and committed (the 20 samples are kept for testing only);
  - when confidence is low, one structured LLM call instead.
- **retrieve (0 LLM calls), fixed recipe per family:**
  - direct: hybrid search + filters → rerank;
  - aggregation: `list_by_filter` → amounts → `calculate` (exact decimal);
  - superseded: every version of the policy → the one in force on the asked
    date or currently;
  - multi-hop: a short ReAct loop (≤ 3 calls) with tools `hybrid_search`,
    `list_by_filter` and `calculate`.
- **draft (1 LLM call, the only guaranteed one):** returns a structured
  `DraftAnswer`:
  - `answer` (str|list), `status`, `citations`;
  - `evidence[{doc_id, quote, value}]`;
  - `evidence_sufficient`, `missing`.

  The call uses provider structured output, falls back to JSON-in-text, and
  makes one repair re-prompt if parsing fails. This step decides
  conflict vs. superseded itself.
- **Safety net:** `evidence_sufficient=false` sends the question once to the
  ReAct loop, with `missing` as the hint.
- **Conflict rule:** values differ + explicit version/replacement language
  → `answered` with the version in force. Values differ without it →
  `conflict`, citing every disagreeing doc, whatever their dates. "Latest
  date wins" is never a rule.
- **Budgets:**
  - 1–2 LLM calls normally, ~5 at most per question;
  - 60 s timeout per question and a 17 min global deadline;
  - when a budget runs out, answer from the best evidence, or `not_found`
    only if nothing was retrieved.

### 4. Validation
- **Input:**
  - `questions.jsonl` checked with pydantic (a bad line becomes `not_found`
    plus a warning);
  - tool arguments checked with pydantic (errors go back to the LLM);
  - corpus chunks wrapped in delimiters as untrusted data;
  - an explicit exit 1 when an env var, the questions file or `corpus/` is
    missing.
- **Output, Python only:**
  1. schema;
  2. grounding:
     - each quote appears verbatim in its chunk;
     - each value appears in a quote or comes from `calculate`;
     - each citation was retrieved during this question's run;
  3. conflict rule: `conflict` needs ≥ 2 citations with differing values;
  4. format: ISO dates, decimal amounts, answer under 200 chars, a list for
     multi-item answers.

  On failure: one retry with feedback, then **keep the answer** with
  `confidence=low` and drop only the citations that were never retrieved.
  Never abstain because validation failed (an abstention costs the full
  0.67 pts plus the 0.17 penalty).

### 5. LLM gateway
`openai` SDK (pinned) on `LLM_BASE_URL`. It retries timeouts, 429 and 5xx
with exponential backoff and jitter, honoring `Retry-After`. No model name is
in code. Dev uses OpenRouter with `anthropic/claude-haiku-5.5`.

### 6. Runner and evidence trail (free angle, may change)
- A thread pool writes `answers.jsonl` lines incrementally, with exactly the
  4 fields.
- One trace per question, in `traces/<run>/<qid>.json`, records:
  - the route decision and its confidence;
  - the recipe and tool calls;
  - the retrieved and reranked chunks;
  - verified quotes;
  - validation results, re-routes and retries;
  - a rule-based confidence label.

  A small viewer for the demo is built on these traces.

### Module layout (≤ 5 non-test files per folder, ≤ 500 lines per file)
```
answer.py
archive/common/      config.py, constants.py
archive/ingest/      pdf_parse_gateway.py, chunking_service.py,
                     metadata_service.py, text_normalize_utils.py,
                     index_builder_service.py
archive/retrieval/   qdrant_gateway.py, embedding_gateway.py,
                     search_service.py, rerank_gateway.py
archive/agent/       router_service.py, recipe_service.py, react_service.py,
                     draft_service.py, prompt_constants.py
archive/llm/         llm_gateway.py, tool_model.py
archive/validation/  input_model.py, answer_model.py, answer_validator.py
archive/pipeline/    run_service.py, trace_gateway.py
index/               qdrant/ (committed), manifest.json, bm25 config, router training set
scripts/             build_index.py, generate_router_set.py, evaluate.py
tests/               mirrored tree
```

## Accepted risks (go in the report)
- A misrouted aggregation or superseded question whose draft is confident
  is not caught (only the safety net is implemented).
- Downloading the dense model at runtime depends on Hugging Face being
  reachable; BM25-only is the fallback.
- Qdrant's local mode is positioned for dev, and the pickle storage ties the
  index to library versions.
- The reranker licence (CC-BY-NC) needs checking.

## Parked
- Abstention threshold tuning (revisit if not_found accuracy is poor).
- Implementation priorities, task batches, process: next plan.

## Execution
Implementation is planned separately. Every implementation task will be done
by `implement` subagents via the plan-workflow §6.1 worktree flow (merged
`--no-ff`), each batch launched in one Agent call, with no inline
implementation by the main agent. The `pre-commit-review` skill (`reviewer` +
`quality`) runs before completion.

## Verification (of the architecture, once built)
- Run, in a clean venv:
  `pip install -r requirements.txt`, then
  `python answer.py <kit>/samples/questions.jsonl answers.jsonl`, then
  `python <kit>/score.py answers.jsonl --details`.
- Measure wall time (scaled to 60 questions), LLM calls per question, and
  accuracy per family and per route.
- Robustness runs:
  - a missing env var;
  - a missing corpus;
  - a mocked 429 or timeout;
  - a new PDF added to `corpus/`;
  - the dense model download blocked, so BM25 is the fallback.
- Measure table-detection quality on 30 docs, and reranker CPU latency.

## Decisions log
- Pure RAG (no facts DB); Qdrant embedded; hybrid dense + BM25 with RRF; e5-large.
- pdfplumber over markitdown (markitdown doesn't tag tables) and over
  PyMuPDF (AGPL) and docling (torch, slow).
- Jev rejected: hosted only and not chat-completions. A local encoder
  classifier beats it on trained intents. Strands Decider 2B is too heavy for
  the CPU eval.
- Lean graph: 1 guaranteed LLM call. Conflicts are decided in `draft` and
  enforced in Python.
- The evidence trail goes in `traces/`, not `answers.jsonl` (the README
  defines only 4 fields).

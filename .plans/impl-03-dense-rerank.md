# Plan: step 03, dense retrieval and reranking (`impl-03-dense-rerank`)

**Status:** done
**Parent:** `.plans/impl-00-roadmap.md` step 03, `.plans/global-architecture.md` §2
**BASE:** 9cd9bcd7a9e91e58ee90cc986054601d5de7bbb6
**Orchestrator branch B:** `feat/dense-rerank`, cut from `main` @ b298d6b. Its
first commit is a `docs:` commit adding the final step-02 main score (33.30/45,
no-op sync 1.6 s) to `.plans/impl-02-ingest-quality.md`.

## Context

Step 02 is merged at 33.30/45. Retrieval is BM25 only. Mean gold-doc
recall@16 on 17 sample questions is 0.79. The remaining misses (s01, s20,
s05/s08/s15) come from missing logic (steps 04 and 05), not from search.

Dense retrieval is for the 60 hidden questions. BM25 misses paraphrases and
FR question ↔ EN doc pairs, and the samples barely test either. The roadmap's
"done when" is: hybrid + rerank ≥ BM25-only score, and 60 questions fit the
time budget.

Measured facts:
- The questions phase takes about 16 s per 20 questions, so the runtime has a
  lot of headroom.
- The real risks are at startup:
  - the model download (e5-large ONNX is about 2.2 GB);
  - CPU embedding of new PDFs during sync. A fully replaced corpus would
    need 3,048 docs embedded.
- `fastembed` 0.9.1 and `onnxruntime` 1.32.0 are on PyPI. Wheels for
  Python 3.11 / Windows are not yet verified.
- `GLOBAL_DEADLINE_S` is 17 min, and the startup sync already counts against
  it.

User decisions:
- **Dense model:** measure, then pick. Candidates are multilingual-e5-large,
  multilingual-e5-small (fastembed custom model) and
  paraphrase-multilingual-MiniLM-L12-v2. Keep the smallest one within 0.02
  recall of the best.
- **Reranker:** measure, keep only if it pays. It is enabled by a constant
  only if recall@16 improves and 60 questions still fit the budget.
- **Licence:** CC-BY-NC is fine, so jina-reranker-v2-base-multilingual is
  allowed.

## Acceptance criteria

1. The spike numbers are logged in the decisions log for each candidate:
   - download size and time;
   - docs/s at 4 threads;
   - query latency;
   - recall@16, BM25 vs hybrid, on the sample gold set and on a
     paraphrase/cross-lingual gold set;
   - reranker latency per question and recall delta.

   The dense model and the reranker on/off choice are logged with their
   reasons.
2. `hybrid_search` fuses dense and sparse prefetches with RRF when the
   embedder is available. With the reranker enabled, it re-scores the top
   `RERANK_CANDIDATES` fused hits. Identifier filters and the empty-filter
   retry behave as today.
3. **Fallback.** If the model download or load fails or exceeds its
   timeout:
   - the run logs one clear warning;
   - it uses BM25-only search;
   - it still answers every question;
   - exit 0.
4. **Sync.** New or changed docs get a dense vector until
   `SYNC_DENSE_BUDGET_S` runs out. After that, docs are upserted sparse-only
   (logged) and remain searchable.
5. The index is rebuilt with dense vectors and committed:
   - `storage.sqlite` stays under 100 MB, checked and printed by
     `scripts/build_index.py`;
   - the startup index check still raises an explicit error on a missing or
     unusable index.
6. Recall@16 (hybrid) on the sample gold set is ≥ 0.79 (the BM25 baseline).
   The sample `score.py --details` is ≥ 33.30. The 60-question extrapolation,
   including model load and sync, stays under 10 min.
7. ruff, `ruff format --check`, `mypy --strict archive scripts answer.py` and
   pytest are green. Tests use fake embedder and reranker ports and never
   download a model.

## Out of scope

- Router and recipes (step 04), and ReAct (step 05).
- Changing chunking: every doc stays one chunk. Docs are ≤ 644 words, and
  e5 truncates at 512 tokens, which is accepted and logged.
- Committing model weights. Models are downloaded at startup into a
  gitignored cache dir.

## Design

### Layout (`archive/retrieval/` would exceed 5 files, so it is split by T0)

```
archive/retrieval/          search_service.py, search_constants.py
archive/retrieval/qdrant/   qdrant_gateway.py, qdrant_constants.py, sparse_encoding_utils.py
archive/retrieval/models/   embedding_gateway.py, rerank_gateway.py, model_constants.py
tests/retrieval/{qdrant,models}/   mirrored
```

### Interfaces (frozen by T0; later tasks fill in the bodies)

- **`retrieval/models/embedding_gateway.py`**
  - `EmbeddingPort` (Protocol): `dim: int`,
    `embed_passages(texts: Sequence[str]) -> list[list[float]]`,
    `embed_query(text: str) -> list[float]`.
  - Implementations add the e5 `passage: ` / `query: ` prefixes when the
    model needs them.
  - `load_embedder(timeout_s: float) -> EmbeddingPort | None`:
    - downloads or loads the model in a daemon thread, joined with the
      timeout;
    - returns None and logs a warning on any failure or timeout;
    - uses cache dir `MODEL_CACHE_DIR` (repo-local `.cache/models/`,
      gitignored) and `MODEL_THREADS`.
- **`retrieval/models/rerank_gateway.py`**
  - `RerankPort` (Protocol): `score(query: str, texts: Sequence[str]) ->
    list[float]`.
  - `load_reranker(timeout_s) -> RerankPort | None`. It returns None when
    `RERANK_ENABLED` is False.
- **`retrieval/models/model_constants.py`**: `DENSE_MODEL_NAME`,
  `DENSE_DIM`, `RERANK_MODEL_NAME`, `RERANK_ENABLED`, `RERANK_CANDIDATES`,
  `MODEL_LOAD_TIMEOUT_S`, `MODEL_CACHE_DIR`, `MODEL_THREADS`.
- **`retrieval/qdrant/qdrant_gateway.py`**
  - `ensure_collection(dense_dim: int | None)` adds the named dense vector
    `DENSE_VECTOR_NAME` (cosine) when `dense_dim` is set.
  - `has_dense() -> bool`.
  - `upsert(chunks, dense: Sequence[list[float] | None] | None = None)`. A
    None entry means a sparse-only point, since named vectors are optional
    per point.
  - `query_hybrid(sparse, dense: list[float] | None, query_filter, k,
    prefetch_k) -> list[tuple[Chunk, float]]`: two `Prefetch` +
    `FusionQuery(RRF)`. With `dense=None` it behaves like `query_sparse`.
- **`retrieval/search_service.py`**
  - `SearchService.open(index_dir, embedder: EmbeddingPort | None = None,
    reranker: RerankPort | None = None)`.
  - `hybrid_search`:
    - same signature and identifier logic as today;
    - fuses with `PREFETCH_K`;
    - then reranks the top `RERANK_CANDIDATES` when a reranker is set and
      returns the top k.
  - The dense side is skipped when the embedder is None or the index has no
    dense vector.
- **Ingest:**
  - `build(corpus_dir, index_dir, workers=None, embedder=None)`;
  - `sync_index(corpus_dir, index_dir, workers=None, embedder=None)`.
  - Dense vectors are embedded in batches of `DENSE_BATCH_SIZE`, after
    parsing, under `SYNC_DENSE_BUDGET_S` for sync. A full build has no
    budget.
  - `SyncReport` gains `sparse_only: int = 0`.
  - `scripts/build_index.py` loads the embedder (it fails loudly if the load
    fails) and prints the `storage.sqlite` size. It warns when the size is
    ≥ `STORAGE_SIZE_LIMIT_MB` (100).
- **`pipeline/run_service.py`**, `run()`:
  1. `load_embedder` and `load_reranker` load in parallel, each with
     `MODEL_LOAD_TIMEOUT_S`;
  2. then `sync_index(..., embedder=...)`;
  3. then `SearchService.open(..., embedder, reranker)`.

  The timeouts count against the global deadline. A missing embedder means
  BM25-only, never exit 1.
- **`scripts/measure_recall.py`**: `--dense/--no-dense` and
  `--rerank/--no-rerank` flags. It loads models through the same loaders.

## Tasks

| Task | What | Owns | Depends | Batch |
|---|---|---|---|---|
| T0 restructure | Pure moves (`git mv`) into `retrieval/qdrant/`. Create `retrieval/models/` with the Protocols, the loader stubs (return None) and the constants. Update every import and the test paths. Add `.cache/` to `.gitignore`. No behavior change. | `archive/retrieval/**`, every importer of the moved modules (import lines only), `tests/retrieval/**`, `.gitignore` | none | 0 |
| S spike | Measurement only, no repo commits (scratch scripts in `%TEMP%`). Install fastembed 0.9.1 in a throwaway venv copy and verify the py3.11/Windows wheels. For each dense candidate, measure: download size and time, docs/s at 4 threads, query latency, and recall@16 of RRF(BM25 top-50, dense) with the step-02 typed-share `retrieve` logic. Measure on the sample gold set and on ~15 paraphrased / FR↔EN-swapped / code-free sample questions (which the spike writes and returns). Rerank jina-v2 and bge-reranker-base on the top 30/50: latency per question and recall delta. Report the exact pins (fastembed, onnxruntime and their transitive deps). | none (report only) | none | 0 |
| T1 models | Real `load_embedder` / `load_reranker` with fastembed. e5 prefixes. Custom-model registration if e5-small is chosen. Thread timeout. Pins in `requirements.txt`. Tests with a monkeypatched fastembed (timeout → None, exception → None, prefixes). | `archive/retrieval/models/**`, `requirements.txt`, `tests/retrieval/models/**` | T0, S | A |
| T2 search | Dense vector config, `upsert` with optional dense, `has_dense`, `query_hybrid` (RRF prefetch), `SearchService` wiring and rerank step. Tests with fake ports on a temp local index: fusion order, sparse-only points still found, reranker reorders, identifier retry. | `archive/retrieval/qdrant/**`, `archive/retrieval/search_service.py`, `archive/retrieval/search_constants.py`, `tests/retrieval/qdrant/**`, `tests/retrieval/test_search_service.py` | T0 | A |
| T3 ingest+startup | `build`/`sync_index` embedding pass with batches and the sync budget, `SyncReport.sparse_only`, the `build_index.py` loader and size check, `run()` parallel model load then sync then open, constants. Tests with a fake embedder: budget exhausted → sparse-only, embedder None → sparse-only, run continues when load fails. | `archive/ingest/build/**`, `archive/pipeline/run_service.py`, `archive/pipeline/pipeline_constants.py`, `scripts/build_index.py`, `scripts/build_index_constants.py` (if needed), `tests/ingest/build/**`, `tests/pipeline/**`, `tests/scripts/test_build_index.py` | T0 | A |
| T4 integrate | Set `DENSE_MODEL_NAME`, `DENSE_DIM`, the rerank constants and `SYNC_DENSE_BUDGET_S` from the spike. Add the flags to `measure_recall`. Commit the paraphrase gold set as `scripts/data/paraphrase_gold.jsonl`. Rebuild the index from the main checkout's `corpus/` and commit `index/` (`chore:`). Measure recall dense on/off and rerank on/off on both gold sets. Decide `RERANK_ENABLED`, then time startup (cold and warm cache) and the questions phase. | `archive/retrieval/models/model_constants.py`, `archive/ingest/build/build_constants.py`, `scripts/measure_recall*.py`, `scripts/data/**`, `tests/scripts/**`, `index/**` | A | B (alone) |

Batches:
- **Batch 0:** T0 and S in parallel. S writes nothing to the repo.
- **Batch A:** T1, T2 and T3 in parallel, with disjoint files. They depend
  only on the T0 interfaces. T1 also needs the S pins and the model shortlist.
- **Batch B:** T4 alone.
- **V** comes last.

Each task merge stays under 700 lines. T0's moves count only their edits.

## Execution

Every task is implemented by an `implement` subagent via the plan-workflow
§6.1 worktree flow:
- The worktree is `.claude/temp_worktree/<slug>`, on branch `<type>/<slug>`
  cut from B.
- Each branch is merged back with `git merge --no-ff`.
- Each batch is launched in one Agent call.

The main agent does not implement tasks inline. The spike S is a
measurement-only implement run: no worktree and no commits; it reports
numbers. Subagents get:
- the absolute path of the main checkout's venv python;
- the main checkout's `corpus/`, `index/` and the kit's `samples/` gold
  path.

After the final merge, `pre-commit-review` (`reviewer` + `quality`) runs on
`BASE..HEAD`. Fix rounds use new slugs, up to about 2 cycles.

## Verification

- Per task:
  - ruff, `ruff format --check`, `mypy --strict` and pytest in its worktree;
  - every behavior change ships with tests;
  - no test downloads a model.
- On B after each batch: the full checks.
- **V** (a verification-only implement run on B, no commits):
  1. **Fallback:** set `MODEL_CACHE_DIR` to an empty dir with the network
     blocked (`HF_HUB_OFFLINE=1`). The run must log the BM25-only warning,
     answer every question and exit 0.
  2. **Sync budget:** on a `%TEMP%` copy, add 20 PDFs and set
     `SYNC_DENSE_BUDGET_S` tiny. Expect the `sparse_only` count in the
     report, and the new docs still found by code.
  3. **Timing:** cold-cache and warm-cache startup times are logged.
  4. **Score:** the user runs `python answer.py samples/questions.jsonl
     answers.jsonl` and then `python score.py answers.jsonl --details`
     (it needs `LLM_*`). Compare against 33.30.

## Decisions log

- 2026-11-16: dense model measured then chosen (smallest within 0.02 recall
  of the best). Reranker kept only if it measurably pays. CC-BY-NC is
  accepted for the jina reranker (user choices).
- 2026-11-16: a paraphrase / cross-lingual gold set is added, because the
  sample questions carry exact codes and BM25 already finds them. Without it
  dense would show no gain.
- 2026-11-16: the sync embeds under a time budget, and overflow docs stay
  sparse-only. A replaced corpus must not blow the 17-min deadline.

## Subagent branches

- Batch 0: `refactor/retrieval-layout` (T0); spike S has no branch.
- Batch A: `feat/hybrid-search` (T2), `feat/dense-ingest` (T3),
  `feat/model-loaders` (T1).
- Batch B: `feat/dense-integrate` (T4 code); the rebuild and the
  measurements run on B in the main checkout.

## Batch B measurements (2026-11-16)

Run on the rebuilt index (ae81e80), 17 samples gold questions and 15
paraphrase gold questions, k = 16 primary. Baseline before the
rebuild was BM25 recall@16 = 0.79 on samples, identical to step 02
(delta 0.00), so the rebuild changed no sparse ranking.

| config                | samples @16 | paraph. @16 | s/query |
|-----------------------|-------------|-------------|---------|
| R1 BM25 only          | 0.79        | 0.80        | 0.8     |
| R2 + dense            | 0.82        | 0.87        | 2.5     |
| R3 + dense + jina     | unmeasured  | unmeasured  | 20-35   |
| R3 + dense + bge-int8 | 1.00 (n=2)  | not run     | 105-140 |
| R5 bge-int8 only      | not run     | not run     | 105-140 |

The k sweep on samples rises with k: BM25 0.67/0.71/0.79/0.79/0.79
and dense 0.79/0.80/0.82/0.82/0.85 at k = 8/12/16/24/32. Dense
lifts samples recall@16 by 0.03 and paraphrase by 0.07, and every
samples question now has a gold doc in the top 16 (17/17 vs 16/17).
Per-query latency is the whole-process wall divided by the question
count, so it includes startup; the k-sweep paraphrase runs give the
same per-retrieve figures (0.82 s BM25, 2.27 s dense).

Reranker, jina (the committed RERANK_MODEL_NAME): disqualified on
evidence, never measured. Event 1: a startup wedge (0.3 s CPU,
19 MB working set, 46 min wall, killed externally). Event 2: a
compute explosion killed mid-row-1 (1451 CPU-seconds, 11.8 GB
working set, 53 threads, about 404 s), roughly 20-35 s compute per
question. Sixty questions would need 20-35 min of reranking alone,
over both the 10-min questions phase bound and GLOBAL_DEADLINE_S =
17 min, with 11.8 GB as an aggravator.

Reranker, bge-int8: the model loads in 2.3 s, but each query
re-scores RERANK_CANDIDATES = 30 candidates in 105-140 s, so a
17-question row cannot finish inside a 600 s guard and no full-gold
recall exists (the 2 probed samples questions both retrieve at
1.00). Sixty questions would need 105-140 min: 6-8x over the
budget, and a drop to 20 candidates would still need about 70-93
min. Only CPU providers are installed (Azure, CPU); the machine has
an Intel Arc GPU but no DirectML provider, so GPU offload is an
unverified lever, not a fix.

Decision: RERANK_ENABLED stays False and RERANK_MODEL_NAME stays
the committed jina id — no constant changed, so no `feat` commit.
Dense stays on: samples 0.82 @16 meets the 0.79 acceptance bar.
Both candidates are recorded as not enabled for budget reasons;
a reranker cannot be enabled without measurements.

Startup, final config (reranker off, so only the embedder loads):
warm 16.8 s (models 1.9, no-op sync 14.3 on the first SHA-1 pass,
open index 0.6); cold 19.8 s (models 16.8 including the 0.24 GB
embedder download, sync 2.5, open 0.6); a second warm pass took
4.5 s with the OS file cache hot (sync 2.1). The no-op sync cost
dominates and stays well inside the deadline.

Environment note, flagged unverified: the first two reranker runs
left a Store-python 3.11 child under the venv launcher; the wedge
root cause is unresolved.

## Step 03 verification (2026-11-17)

- V fallback: empty cache + HF_HUB_OFFLINE=1 → exit 0, one warning
  per layer (LOG_MODEL_FAILED then LOG_DENSE_UNAVAILABLE), BM25-only
  run, 20/20 lines, statuses 11 answered / 8 not_found / 1 conflict.
- V sync budget: 20 added docs on a %TEMP% index copy with
  SYNC_DENSE_BUDGET_S=0.001 → SyncReport sparse_only=20; scroll
  confirmed all new points sparse-only; the new doc retrievable by
  BM25 at the identical score of its indexed twin (32.8202).
- Timing: cold startup 19.8 s (includes the 0.24 GB MiniLM
  download), warm 16.8 s, second warm 4.5 s; no-op sync 2.1 s.
- Score (user run, dense on, rerank off): 33.30/45 — equal to the
  step-02 baseline, acceptance ≥ 33.30 met. Exactitude 20.62/30
  (11/16), fiabilité 9.15/10 (4/4 statuses, 5 unjustified
  abstentions), citations 3.53/5. direct 6/6, aggregation 2/3,
  superseded 3/3, conflict 1/1, unanswerable 3/3, multi_hop 0/4.
- Reading: retrieval measurably improved (recall@16 0.79 → 0.82
  samples, 0.80 → 0.87 paraphrase, any 16/17 → 17/17) but the score
  is capped by the five questions needing steps 04/05 logic:
  multi_hop s04/s05/s08/s15 and s20 (17-gold-doc aggregation,
  recall 0.06@16 even with dense — needs decomposition, not
  better vectors).

## Resume point

2026-11-17, step 03 done. All tasks merged on `feat/dense-rerank`:
hybrid BM25 + dense MiniLM RRF search (recall@16 0.82 samples /
0.87 paraphrase), rerank wired but disabled (RERANK_ENABLED=False;
both rerankers CPU-dead — jina ≈20–35 s/question + 11.8 GB,
bge-int8 105–140 s/query), index rebuilt with dense (storage.sqlite
24.4 MB), 463 tests, four checks green, V verified (fallback, sync
budget, timing), score 33.30/45. Nothing pushed. Next: merge to
`main` on approval, then step 04 (router/recipes) and 05 (ReAct)
for the multi_hop/aggregation gap; 06 and 08 stay must-haves before
the Wed 12:00 deadline.

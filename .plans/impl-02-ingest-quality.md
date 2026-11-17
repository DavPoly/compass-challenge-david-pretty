# Plan: step 02, ingest quality and retrieval depth (`impl-02-ingest-quality`)

**Status:** in-progress
**Parent:** `.plans/impl-00-roadmap.md` step 02, `.plans/global-architecture.md` §1
**BASE:** `59a79fc618692ee90f82cf2af424f1bbdfed5a05`
**Subagent branches:** refactor/ingest-layout (T0, merged aee336d), feat/table-render (T1), feat/doc-metadata (T2), feat/index-sync (T3), feat/retrieve-hints (T4), feat/integrate-retrieve (T5)
**Orchestrator branch B:** `feat/ingest-quality`, cut from `main` @ 59a79fc

## Context

Step 01 is merged on `main` and scored 26.60/45 (direct 6/6, multi_hop 0/4,
aggregation 1/3, superseded 1/3). The V run showed that retrieval depth is the
main gap: `SEARCH_TOP_K=8` is smaller than the gold-doc counts of s10 (12) and
s20 (17). Recon on the full corpus found:

- Every doc is ≤ 644 words, so each doc is already exactly one chunk.
  Section-based splitting is irrelevant.
- `extract_text` already includes table cells as plain lines. Tables exist in
  all 983 invoices, 656 monthly reports, 70 technical notes, 56 project sheets,
  69 contracts and the 9 staff-directory docs.
- All 656 monthly reports have `doc_date=None`, because their only date is a
  month-year period ("Période : août 2023"). 44 contracts also have no date.
- There are about 12 doc families. Their headers contain typos ("Monthy",
  "mcnsuel", "Tcchnical", "Reunion"), and `doc_type` is always "unknown" today.
- The 33 policy docs carry "Version N — En vigueur le <date>" or
  "Effective <date>" (typos such as "Efffective"). Versions of one policy share
  a title line, with accent and typo variants.

User decisions:
- **Tables inline.** Keep one chunk per doc, and render each detected table as
  `cell | cell` rows inside that chunk.
- **Add retrieval wins.** Tune top-k by measured recall, and add doc-type
  hints from the question.

## Acceptance criteria

1. The 30-doc table check is run, and its result is logged in the decisions
   log (detection rate per family, and how many invoices have table amounts
   that sum to the subtotal).
2. On the full corpus:
   - `doc_type` is "unknown" for ≤ 1 % of docs.
   - Every policy doc has `version`, `effective_from` and `series`.
   - `effective_to` equals the next version's `effective_from`, and is None
     on the latest version.
   - Monthly reports get a `doc_date`.
3. At startup, before the index is opened:
   - a new PDF in `corpus/` is indexed;
   - a changed PDF is re-indexed;
   - a removed PDF is deleted from the index;
   - an unchanged corpus costs only the hashing (< 2 s).
4. Recall@k is measured with `scripts/measure_recall.py` for k ∈
   {8, 12, 16, 24, 32}. K is chosen and logged. Mean gold-doc recall@K must
   be ≥ 0.67 (the baseline).
5. The rebuilt index is committed. The sample run's `score.py --details` is
   ≥ 26.60, and the 60-question extrapolation stays under 10 min.
6. ruff, `ruff format --check`, `mypy --strict archive scripts answer.py` and
   pytest are green.

## Out of scope

- Dense vectors and the reranker (step 03).
- Routing and recipes (04), and value grounding (06).
- Rewriting chunk text with normalized numbers. The text stays verbatim for
  step 06 quotes. Amount parsing stays in `archive/validation` until step 04's
  `calculate` needs it there too. Date tables were already unified in step 01.

## Design

### Layout: `archive/ingest/` gets subfolders (≤ 5 non-test files each)

```
archive/ingest/chunking_service.py, chunking_constants.py
archive/ingest/parse/     pdf_parse_gateway.py, table_render_utils.py, parse_constants.py
archive/ingest/metadata/  metadata_service.py, doc_type_utils.py, version_utils.py, metadata_constants.py
archive/ingest/build/     index_builder_service.py, index_sync_service.py, manifest_gateway.py,
                          version_series_utils.py, build_constants.py
tests/ingest/{parse,metadata,build}/   mirrored
```

### Interfaces (frozen by T0; later tasks fill in the bodies)

- `archive/common/chunk_model.py`:
  - add the `DocType` StrEnum: `invoice`, `contract`, `monthly_report`,
    `minutes`, `email`, `newsletter`, `memo`, `policy`, `directory`,
    `technical_note`, `project_sheet`, `unknown`;
  - add the optional `Chunk.series: str | None = None` (the normalized
    policy title key);
  - `doc_type` stays `str` and holds `DocType` values (the roadmap contract
    is unchanged).
- `ingest/parse/pdf_parse_gateway.py`: `ParsedDoc(doc_id, pages,
  table_count: int = 0)`. Each detected table's text is replaced, at its
  vertical position, by one `cell | cell` line per row. If table detection
  fails, the page falls back to plain `extract_text`.
- `ingest/metadata/metadata_service.py`: `DocMetadata` gains `version`,
  `effective_from` and `series` (all `str | None`).
  - `extract_metadata(doc)` sets `doc_type` through
    `doc_type_utils.detect_doc_type(text) -> DocType`.
  - `doc_date` order: labelled header date first ("Date :", "Report date",
    "En vigueur", "Mise à jour"), then the earliest full date, then the
    month-year period (`YYYY-MM-01`).
- `ingest/metadata/version_utils.py`: `parse_version(text) -> VersionInfo |
  None` returns version, effective_from and series. It is typo tolerant and
  covers FR and EN.
- `ingest/build/version_series_utils.py`: `with_effective_to(chunks) ->
  list[Chunk]`. Within each `series`, sorted by `effective_from`, it sets
  `effective_to` to the next version's `effective_from`.
- `ingest/build/manifest_gateway.py`: `load_manifest`, `write_manifest`
  (atomic: write a tmp file, then replace), `file_entry`, `ManifestEntry`
  and `ManifestError`. These are moved out of `index_builder_service`.
- `ingest/build/index_sync_service.py`: `sync_index(corpus_dir, index_dir,
  workers=None) -> SyncReport(added, changed, removed, failed, seconds)`.
  - It diffs the manifest against the corpus by size and sha1.
  - For changed or removed docs it calls `QdrantGateway.delete_docs(doc_ids)`.
  - It parses new or changed docs through the builder's shared worker, then
    upserts them.
  - It re-applies `with_effective_to` to every policy chunk, then writes the
    manifest.
  - With no manifest or no collection, it falls back to a full `build()` and
    logs a warning.
- `archive/retrieval/qdrant_gateway.py`: `delete_docs(doc_ids)`, a filter
  delete on `doc_id`.
- `archive/pipeline/run_service.py`: `run()` calls `sync_index` after the
  corpus check and before `SearchService.open`. If sync fails while an index
  exists, it logs a warning and continues on the stale index. Exit 1 stays
  reserved for "no usable index".
- `archive/agent/retrieve_service.py`: `retrieve(question, search, k) ->
  list[SearchHit]`.
  - `detect_doc_type_hints(question)` uses a FR/EN keyword table:
    facture/invoice/facturé/billed → invoice; politique/policy → policy;
    contrat → contract; réunion/meeting → minutes; and so on.
  - When it finds hints, `RETRIEVE_TYPED_SHARE` of the k slots go to a
    `doc_types`-filtered search first. Unfiltered hits fill the rest, deduped
    by `chunk_id`.
  - Typed slots are reserved because merging by score alone would just
    reproduce the unfiltered top-k.
  - `SEARCH_TOP_K` moves from `pipeline_constants` to `retrieve_constants`.
- `scripts/measure_recall.py`: `--gold <path> --k 8,12,16,24,32`. It prints
  per-question gold-doc recall@k and the mean, using `retrieve()` with no LLM.
- `scripts/check_tables.py`: picks 30 docs by stable stratified sampling
  (10 invoices, 10 monthly reports, 5 project sheets, 3 directory,
  2 technical notes).
  - It prints the table count and the rendered rows of each doc.
  - For each invoice it checks that the table amounts sum to "Subtotal".

## Tasks

| Task | What | Owns | Depends | Parallel |
|---|---|---|---|---|
| T0 restructure | Pure moves: the ingest subfolders, split `ingest_constants`, extract `manifest_gateway`. Add `DocType` and `Chunk.series` with stubs that keep behavior. Update imports in `retrieval/search_service.py`, `scripts/build_index.py` and the tests. Use `git mv` so renames are detected. | `archive/ingest/**`, `archive/common/chunk_model.py`, `archive/retrieval/search_service.py` (import only), `scripts/build_index.py`, `tests/ingest/**`, `tests/common/**` | none | no (tracer) |
| T1 tables | Inline table rendering, `table_count`, `scripts/check_tables.py`, run the 30-doc check and report the numbers | `ingest/parse/**`, `scripts/check_tables.py`, `tests/ingest/parse/**` | T0 | A |
| T2 metadata | `detect_doc_type`, `parse_version`, the `doc_date` order (period, "1er", contracts), copy the new fields in `chunking_service`. Measure on the full corpus (scratch script, not committed): unknown rate, policy coverage, missing dates | `ingest/metadata/**`, `ingest/chunking_service.py`, `ingest/chunking_constants.py`, `archive/common/text/date_parsing_*.py`, `tests/ingest/metadata/**`, `tests/ingest/test_chunking_service.py`, `tests/common/text/**` | T0 | A |
| T3 sync | `with_effective_to` applied in `build()` and `sync_index`, `delete_docs`, startup call in `run()`, atomic manifest write | `ingest/build/**`, `retrieval/qdrant_gateway.py`, `retrieval/qdrant_constants.py`, `pipeline/run_service.py`, `pipeline/pipeline_constants.py`, `tests/ingest/build/**`, `tests/retrieval/test_qdrant_gateway.py`, `tests/pipeline/**` | T0 | A |
| T4 retrieve | `retrieve_service` plus constants (K default stays 8), `scripts/measure_recall.py`, tests | `archive/agent/retrieve_service.py`, `archive/agent/retrieve_constants.py`, `scripts/measure_recall.py`, `tests/agent/test_retrieve_service.py` | T0 | A |
| T5 integrate | Wire `run()` to `retrieve()`. Rebuild the index from the main checkout's `corpus/` and commit `index/` in a `chore:` commit. Run `measure_recall` and set `SEARCH_TOP_K` and `MAX_PROMPT_CHUNKS` to the chosen K. | `pipeline/run_service.py`, `pipeline/pipeline_constants.py`, `agent/retrieve_constants.py`, `agent/prompt_constants.py`, `index/**`, `tests/pipeline/**` | A | B (alone) |

Batches:
- T0 runs first, alone.
- Batch A runs T1 to T4 in parallel, with disjoint files.
- Batch B is T5 alone.
- V comes last.

Every task stays under 700 merge lines. Whole-file moves in T0 count only
their edits.

## Execution

Every task is implemented by an `implement` subagent via the plan-workflow
§6.1 worktree flow:
- The worktree is `.claude/temp_worktree/<slug>`, on branch `<type>/<slug>`
  cut from B.
- Each branch is merged back with `git merge --no-ff`.
- Each batch is launched in one Agent call.

The main agent does not implement tasks inline. Subagents get:
- the absolute path to the main checkout's venv python
  (`.venv/Scripts/python.exe`);
- the absolute path to the main checkout's `corpus/`, which is untracked and
  absent from worktrees.

After the final merge, `pre-commit-review` (`reviewer` + `quality`) runs on
`BASE..HEAD`. Fix rounds use new slugs, up to about 2 cycles.

## Verification

- Per task:
  - its "done when" checks;
  - ruff, `ruff format --check`, `mypy --strict` and pytest in its worktree;
  - every behavior change ships with tests;
  - T1 and T2 report their measured numbers.
- On B after each batch: the full checks.
- **V** (a verification-only implement run on B, no commits):
  1. Run `python answer.py samples/questions.jsonl answers.jsonl`, then
     `python score.py answers.jsonl --details`. This needs the user's
     `LLM_*` env vars. Compare against 26.60 and record wall time.
  2. Run the sync robustness check in `%TEMP%`:
     - Copy `index/` and `corpus/`, then add one duplicated PDF as
       `doc_9999.pdf`, modify one doc and delete one.
     - Run `sync_index` and assert added=1, changed=1, removed=1.
     - Assert that `hybrid_search` finds `doc_9999`.
     - A second sync must be a no-op that takes < 2 s.
  3. Record the numbers in the decisions log.

## Decisions log

- 2026-11-16: tables inline (user choice). Every doc is a single chunk, so
  separate table chunks would duplicate content and use up top-k slots.
- 2026-11-16: retrieval wins added to step 02 (user choice): measured K and
  doc-type hints with reserved typed slots.
- 2026-11-16: number normalization is not applied to the chunk text (step 06
  needs verbatim quotes). The amount parser stays in validation.
- 2026-11-16: startup sync falls back to a full build when there is no index,
  and continues on the stale index when sync fails.
- 2026-11-16 (T0): merged aee336d, 315 lines. pytest skips dirs named
  `build` by default; `norecursedirs` in pyproject = pytest 9.2 default
  minus "build" so `tests/ingest/build/` runs.
- 2026-11-16 (T1): table check (`scripts/check_tables.py`): invoice
  10/10, monthly_report 10/10, project_sheet 5/5, staff directory 1/1
  (the corpus holds only one), technical_note 2/2 docs with tables;
  invoice amounts sum to Subtotal 10/10 (FR and EN formats). 28 docs,
  not 30, for lack of directories. Non-table lines verbatim vs
  extract_text on 50 docs: 0 mismatches. Parse 0.061 → 0.132 s/doc
  (accepted: ~20 s more on a 22-core full build; startup sync parses
  only new docs).
- 2026-11-16 (T2): doc_type unknown 0/3048 (invoice 983,
  monthly_report 712, minutes 451, email 447, contract 93,
  technical_note 90, project_sheet 90, memo 77, newsletter 68, policy
  35, directory 2). The supplier list doc_2534 maps to `directory`
  (closest frozen value). All 35 policies have version, effective_from
  and series: 12 series, contiguous versions, no title-letter typos, so
  no fuzzy series rule. doc_date None: 0 for every type. The recon
  figure "44 undated contracts" came from a coarse regex and was wrong.
- 2026-11-16 (T3): merge 708 lines (≈340 tests), just over the soft 700
  budget, merged anyway. Missing index → startup sync builds it (exit 1
  only if sync fails and no usable index remains); the run_service test
  for "index open failure exits 1" was replaced by three tests. No-op
  sync: 1.5–1.7 s on a quiet machine, 2.5–3.8 s under load, mostly
  hashing 3,048 files; accepted (an mtime shortcut would change the
  frozen ManifestEntry). Gateway gained `scroll_series`.
- 2026-11-16 (T4): typed share 0.5; courriel/email, poste, salaire and
  bare "rapport" are deliberately not hints. Recall on the old index
  (all "unknown" types, so typed slots inert): mean @8 0.67, @12 0.71,
  @16–32 0.73; s01/s12 stay 0 at every k, s20 0.12 at k=32.
- 2026-11-16 (batch A): merged 3149ef5, c40f626, af8900a, 14afc88;
  ruff, format, mypy --strict green, 374 tests.
- 2026-11-16 (T5): retrieval wired through `retrieve()`. Rebuild: 3,048
  docs, 3,050 chunks, 0 failures, 100.9 s, storage.sqlite 14.3 MB.
  Recall on the new index (17 gold questions), mean:
  share 0.5 → @8 0.67, @12 0.71, @16 0.72, @20 0.73, @24 0.79;
  share 0.75 → @8 0.67, @12 0.71, @16–32 0.79. Chosen K=16, share
  0.75 (s12 0 → 1.0, s10 → 1.0 at k=16); s20 stays ≤ 0.12 (needs the
  step 04 aggregation recipe). `MAX_PROMPT_CHUNKS = SEARCH_TOP_K`.
  Prompt at K=16: avg 18.1 k chars, max 32.5 k. Merge 23 code lines.
- 2026-11-16: LLM_* unset in this session, so the pre-commit review and
  the V sync check run before the scored V run (as in step 01).

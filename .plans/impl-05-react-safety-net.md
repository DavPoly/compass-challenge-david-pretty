# Plan: step 05, multi-hop loop and safety net (`impl-05-react-safety-net`)

**Status:** done
**Parent:** `.plans/impl-00-roadmap.md` step 05, `.plans/global-architecture.md` §3
**Orchestrator branch B:** `feat/react-safety-net`, cut from `main` @ 88328c8 (step 04 merged).
**BASE:** 88328c852b5d118f347d92e8f0b3f370da41bec7
**Subagent branches:** feat/hops-tracer (T0), feat/hops-expand (T1), feat/hops-loop (T2), fix/expand-shared-codes, fix/hops-promote-linked, fix/hops-partial-chain, fix/hops-chain-cite-log, fix/hops-review (all merged and deleted)

Before cutting B:
1. Merge `feat/router-recipes` into `main` locally (`--no-ff`, no push). This is the user's choice.
2. Cut B from `main`.
3. Record BASE in `.plans/impl-05-react-safety-net.md`.

## Context

After step 04 the score is 35.64/45. Every family is at 100% except
multi_hop, which is 0/4. Each of the four misses is a chain of entity
links, and the current single retrieve → draft pass sees only the first
link:

| id | chain | gold docs |
|---|---|---|
| s04 | project name → charter (BRV-2023-14, subcontractor) → contract C-2023-15 → price | doc_2198, doc_1382 |
| s05 | contract C-2023-15 → signer Léa Fréchette → staff directory → email | doc_1382, doc_0459 |
| s08 | invoice F-2021-1413 → BRV-2019-22 → project sheet (Xavier Ricard) → directory → email | doc_2003, doc_1387, doc_0459 |
| s15 | invoice F-2026-1104 → BRV-2025-10 → project sheet → manager | doc_2005, doc_0549 |

Two kinds of link need following:
- **Code links.** An invoice, contract or charter carries a BRV code in
  `chunk.identifiers`. That code leads to the project sheet or contract
  that shares it. Python can follow these with `list_by_filter`, at no
  LLM cost.
- **Name links.** A person's name leads to the directory row with their
  email. The draft already reports these gaps through
  `evidence_sufficient=false` and `missing`
  (`archive/validation/answer_model.py:48`). The `missing` text becomes a
  follow-up search.

User decisions (2026-11-17):
- Method: identifier expansion first, then a loop of draft calls driven
  by `missing`.
- Branch base: merge step 04 into main first.

## Acceptance criteria

1. **Multi-hop loop.** For the `multi_hop` family, the code-linked docs
   (project sheet, contract) join the hits before the first draft. While
   the draft reports `evidence_sufficient=false` with a non-empty
   `missing`, a follow-up search on `missing` adds hits and the draft runs
   again. There are at most 3 draft calls, so at most 4 LLM calls per
   question with the plan call.
2. **Safety net.**
   - A `direct` draft with `evidence_sufficient=false` and a non-empty
     `missing` gets one follow-up hop: expansion plus the `missing`
     search, then a second draft.
   - A direct draft that is sufficient is unchanged: same prompt, a
     single call.
3. **Budget.**
   - No new draft starts once `HOP_TIME_BUDGET_S` has passed since the
     loop began (injected clock). The answer is then the last draft.
   - The per-question 60 s budget and the global deadline still hold
     under a mocked slow LLM. `tests/pipeline` covers this.
4. **Citations.** The retrieved ids are every doc that reached any draft
   prompt in the loop, so validation keeps citations from earlier hops.
5. **Offline check.** With the committed index and no LLM, expansion
   puts the code-linked gold docs into the prompt hits:
   - doc_0549 for s15;
   - doc_1387 for s08;
   - doc_1382 for s04.

   A `missing` string naming the person (e.g. "email of Xavier Ricard")
   brings doc_0459 into the hits.
6. **Scored run (user).**
   - The score is ≥ 35.64 and multi_hop is ≥ 2/4.
   - The unanswerable questions s02, s11 and s18 stay `not_found`.
   - Direct, aggregation, superseded and conflict stay at 100%.
   - Log the wall time. Questions should take ≤ 30 s for 20 questions.
7. **Checks.** ruff, `ruff format --check`, `mypy --strict archive scripts
   answer.py` and pytest are green. Every test uses fakes and none
   touches the network.

## Out of scope

- An LLM tool-calling ReAct loop. The roadmap wording is superseded, and
  the decisions log records why.
- The grounding checks (step 06) and traces (step 07).
- New scripts. `scripts/` is already over the folder limit, so V uses a
  scratchpad snippet.

## Design

### Layout

`archive/agent/` is at its 5-file limit, so it gains a new subfolder:

```
archive/agent/hops/   hop_model.py, expand_service.py, hop_service.py,
                      hop_constants.py
tests/agent/hops/     mirrored
```

### Interfaces (frozen by T0)

- **`hops/hop_model.py`**
  - `HopPolicy`, a frozen dataclass:
    - `max_drafts: int`;
    - `expand_upfront: bool`;
    - `time_budget_s: float`;
    - `clock: Callable[[], float]`, defaulting to `time.monotonic`.
  - Two constructors:
    - `HopPolicy.multi_hop()`: 3 drafts, expansion before the first draft.
    - `HopPolicy.safety_net()`: 2 drafts, expansion only on the
      follow-up.
- **`hops/expand_service.py`**:
  `expand_by_identifiers(question: Question, hits: list[SearchHit],
  search: RecipeSearchPort) -> list[SearchHit]`.
  - It takes the codes found in the question (`find_identifiers`) and in
    the `chunk.identifiers` of the top `EXPAND_SOURCE_HITS` hits. Emails
    are left out.
  - It calls `list_by_filter(SearchFilters(identifiers=codes,
    doc_types=EXPAND_DOC_TYPES), EXPAND_CAP)`, where `EXPAND_DOC_TYPES`
    is `project_sheet` and `contract`.
  - It returns only chunks that are new by `chunk_id`, in the order the
    codes were found, with question codes first.
- **`hops/hop_service.py`**:
  `run_hops(question: Question, hits: list[SearchHit], search:
  RecipeSearchPort, llm: LlmGateway, policy: HopPolicy) -> RecipeResult`.
  - `run_hops` returns `RecipeResult(hits=<every hit that reached a
    prompt>, draft=<last draft>)`.
  - The prompt hits are the targeted ones (expansion and follow-up,
    newest first), then the original hits, capped at
    `MAX_PROMPT_CHUNKS`.
  - The follow-up search is `hybrid_search(missing, None,
    FOLLOW_UP_K)` merged with `hybrid_search(missing,
    doc_types=FOLLOW_UP_DOC_TYPES, FOLLOW_UP_TYPED_K)`. The typed types
    are directory, project_sheet and contract.
  - The loop stops at the first of:
    - the draft is sufficient;
    - `missing` is empty;
    - the follow-up search adds no new chunk;
    - `max_drafts` is reached;
    - the time budget is spent.
- **`answer_service.answer_question`** (signature unchanged):
  - `multi_hop` → `retrieve` → `run_hops(..., HopPolicy.multi_hop())`.
  - `direct` (and any recipe fallback) → `retrieve` → `draft`. If that
    draft is insufficient and has `missing`, it goes to
    `run_hops(..., HopPolicy.safety_net())`, seeded with that first
    draft so the call is not repeated.
  - Recipes that draft themselves (aggregation) are unchanged.
- `run_hops` takes a seeded first draft. The exact shape is up to T0
  (a keyword-only `first_draft: DraftAnswer | None = None` is fine), but
  it is frozen once T0 merges.

### Data flow

```
plan (1 LLM) ─┬─ multi_hop: retrieve → expand → draft ⟲ (missing → follow-up search → draft) ≤3
              ├─ direct:    retrieve → draft ── insufficient+missing? → expand+follow-up → draft
              └─ aggregation / superseded: unchanged (step 04)
→ validate (retrieved ids = union of prompt hits)
```

## Tasks

| Task | What | Owns | Depends | Batch |
|---|---|---|---|---|
| T0 tracer | Create the `hops/` package with the frozen models and signatures. `expand_by_identifiers` is a stub returning `[]`. `run_hops` runs one draft, so the loop is a single pass. Wire `answer_service`: the multi_hop dispatch and the safety-net hook. `hop_constants.py` gets section headers. Adjust the pipeline `FakeLlm` if the hook changes call counts. Existing tests pass and new dispatch tests are added. | `archive/agent/answer_service.py`, `archive/agent/hops/**`, `tests/agent/test_answer_service.py`, `tests/agent/hops/**`, `tests/pipeline/**` | none | 0 |
| T1 expand | The real `expand_by_identifiers` and its constants under "# Expand". Tests: invoice → project sheet code pivot, question codes first, email identifiers ignored, already-present chunks dropped, cap respected, no codes → `[]`. | `archive/agent/hops/expand_service.py`, "# Expand" in `hop_constants.py`, `tests/agent/hops/test_expand_service.py` | T0 | A |
| T2 loop | The real `run_hops` loop: follow-up search, prompt assembly and the cumulative retrieved ids, the five stop conditions and the time budget (fake clock), plus its constants under "# Loop". Tests cover each stop condition, the seeded first draft (no repeated call), the hits union and the draft count limit. | `archive/agent/hops/hop_service.py`, `hop_model.py`, "# Loop" in `hop_constants.py`, `tests/agent/hops/test_hop_service.py` | T0 | A |

`hop_constants.py` is shared by T1 and T2. T0 creates it with the two
section headers, and each task appends only under its own. Any conflict
at merge is mechanical.

**Batches:**
- **0:** T0 alone (the tracer bullet).
- **A:** T1 and T2 in parallel.
- **V** last.

Each merge stays under 700 lines.

## Execution

Every task is implemented by an `implement` subagent via the plan-workflow
§6.1 worktree flow:
- the worktree is `.claude/temp_worktree/<slug>`, on branch
  `<type>/<slug>` cut from B;
- each branch is merged back with `git merge --no-ff`;
- each batch is launched in one Agent call.

The main agent does not implement tasks inline. Subagents get:
- the main checkout's venv python
  `c:/Users/david/Dev/compass-challenge-david-pretty/.venv/Scripts/python.exe`;
- the main checkout's `index/` and `corpus/`.

After the final merge, `pre-commit-review` (`reviewer` + `quality`) runs on
`BASE..HEAD`. Fix rounds use new slugs, up to about 2 cycles. The main
agent commits only `docs:` plan updates.

## Verification

- **Per task:** the four checks run in its worktree.
- **On B after each batch:** the full checks.
- **V** is a verification-only implement run on B, with no commits. It
  runs a scratchpad snippet against the committed index, with no LLM:
  - `retrieve` + `expand_by_identifiers` for s04, s08 and s15 shows the
    code-linked gold docs in the prompt hits (criterion 5);
  - a follow-up search for "email of Xavier Ricard" and one for "courriel
    de Léa Fréchette" both return doc_0459.
- **Score:** the user runs `python answer.py samples/questions.jsonl
  answers.jsonl` and then `python score.py answers.jsonl --details`.
  - The bar is criterion 6.
  - If s02, s11 or s18 regress, turn the safety net off in
    `answer_service` and re-run.
  - Log the wall time.

## Decisions log

- 2026-11-17: the hops use deterministic identifier expansion plus a
  draft loop driven by `missing` (at most 3 drafts), not an LLM
  tool-calling ReAct loop. It reuses the existing `DraftAnswer` fields
  and costs fewer LLM calls (user choice).
- 2026-11-17: step 04 is merged into main before step 05 is cut (user
  choice).
- 2026-11-17: expansion pivots on codes shared by ≥ 2 hits and lists
  per code. On s04 the "contrat" hint filled the top ranks with unrelated
  contracts, and the charter sat at rank 12.
- 2026-11-17: the prompt moves original hits linked to targeted ones
  forward, and reserves 4 slots for original hits. Each hop adds at
  most 6 new hits.
- 2026-11-17: the draft prompt has a "partial chain" rule (on a partial
  chain, set `evidence_sufficient=false` and name the next fact in
  `missing`) and a "chain citations" rule. The old
  `evidence_sufficient` description let the LLM stop with not_found, so
  no hop ever ran.
- 2026-11-17: a follow-up happens only when the evidence is
  insufficient and `missing` names a fact (not the empty-retrieval
  sentinel). A final not_found never replaces an earlier answered
  draft. The hop budget is 30 s from question start. These came from
  review round 1.
- 2026-11-17: a second review cycle was skipped. The round 1 fixes are
  covered by tests and by a 45/45 rerun.

## Measurements

| Run | Score | multi_hop | Notes |
|---|---|---|---|
| step 04 baseline | 35.64 | 0/4 | |
| expansion + loop | 37.98 | 1/4 | the loop never fired (sufficient=true on not_found) |
| partial-chain prompt | 42.51 | 3/4 | s04 citations 0.5, s08 not_found |
| chain citations + draft log | 45.00 | 4/4 | |
| after review round 1 | 45.00 | 4/4 | questions phase ~17 s; 625 tests green |

## Resume point

Step 05 is done on `feat/react-safety-net`, which is not merged to main
and not pushed. Next is step 06 (grounding) or step 08 (hardening and
report). Step 08 starts this evening at the latest, per the roadmap.

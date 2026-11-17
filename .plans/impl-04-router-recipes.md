# Plan: step 04, router and recipes (`impl-04-router-recipes`)

**Status:** in-progress
**BASE:** 161204412e88aaf6c782860d2b9b1a976f92945d
**Parent:** `.plans/impl-00-roadmap.md` step 04, `.plans/global-architecture.md` §3
**Orchestrator branch B:** `feat/router-recipes`, cut from `main` @ 1612044
(step 03 merged). BASE is recorded in `.plans/impl-04-router-recipes.md`
before the first worktree.

## Context

Step 03 left the score at 33.30/45:
- direct 6/6, superseded 3/3, conflict 1/1 and unanswerable 3/3;
- aggregation 2/3, with s20 failing;
- multi_hop 0/4, which is step 05.

Every question takes the same path today: `retrieve` (top 16) → `draft`
(one LLM call) → `validate`, in `archive/pipeline/run_service.py:122`.

Why the current path breaks:
- **Aggregation needs every matching doc, not the top 16.** s20 has 17
  gold invoices and its recall@16 is 0.06. The hidden set will hold more
  of this kind, and a sum the LLM does in its head is fragile.
- **Superseded works today, but only by luck.** Nothing picks the version
  in force on the asked date. The `version`, `effective_from`,
  `effective_to` and `series` payloads exist (step 02) and go unused.

User decisions (2026-11-17):
- **Router.** Regex plus one structured LLM "plan" call per question.
  This replaces the local classifier and the training set the
  architecture planned, to save time before the deadline.
- **Amounts.** Python parses the invoice lines with exact `Decimal`. When
  the regex fails, the docs go to an LLM extraction call. Python always
  does the sum.

Facts from the committed index:
- 983 invoices and 90 project sheets, all templated.
  - Invoice lines: `Facturé à :` / `Bill to:`, `Projet :` / `Project:`,
    `Sous-total :` / `Subtotal:`, `TOTAL :`.
  - 21 of the 983 invoices have no subtotal line that the regex can read
    (typos).
  - Every project sheet has a `Chargé de projet` / project manager row.
  - Invoice `identifiers` carry their BRV code, and `doc_date` is the
    issue date. There are 132 invoices in 2023 and 162 in 2025.
- `SearchService.list_by_filter` (`archive/retrieval/search_service.py:179`)
  scrolls by doc_type, identifier and date range.
- `normalize_amount` (`archive/validation/answer_validator.py:123`) and
  `normalize_for_match` (`archive/common/text/text_normalize_utils.py`)
  can be reused.

## Acceptance criteria

1. Every valid question gets a `QuestionPlan`: regex codes and dates, plus
   one LLM plan call. If the plan call fails, it falls back to the
   `direct` family and the run continues. On the 20 samples, the family
   matches the gold `type` on at least 15/16 of the answerable ones.
   Measured by `scripts/measure_route.py`.
2. **Aggregation recipe.**
   - It sums invoices filtered by client name, BRV code(s) or project
     manager (manager → their project sheets → BRV codes), within the date
     range.
   - The measure is the subtotal (pre-tax) or the TOTAL (taxes included).
   - The arithmetic is exact `Decimal`. All summed invoices are cited, and
     each carries one evidence quote (its amount line).
   - Offline, with a fixed plan and the committed index, it reproduces the
     gold answer of s07, s10 and s20 exactly.
   - With no narrowing entity (for example s18 "revenue in 2024") or no
     matching invoice, it falls back to `direct`.
3. **Superseded recipe.**
   - It finds the policy series and picks the version in force on
     `as_of_date`, or the latest one when the question asks what is in
     force now.
   - That version goes first in the hits.
   - A one-line note naming it goes into the draft prompt.
   - s01, s12 and s17 still pass.
4. Unanswerable questions s02, s11 and s18 stay `not_found`.
5. **Scored run.** The user's run reaches ≥ 33.30, with aggregation 3/3.
6. **Budget.** At most 3 LLM calls per question on a recipe path. The
   extrapolated 60-question run, startup included, stays under 10 min.
7. **Checks.** ruff, `ruff format --check`, `mypy --strict archive scripts
   answer.py` and pytest are green. Tests use fake LLM and search ports,
   and none needs the network.

## Out of scope

- The multi_hop ReAct loop (step 05). The `multi_hop` family uses the
  direct path for now.
- The grounding checks (step 06).
- The classifier and its generated training set. They are dropped, and
  the roadmap decisions log records why.
- Aggregations over anything but invoices: hours, counts and revenue
  figures. These go to `direct`.

## Design

### Layout

`archive/agent/` holds at most 5 files, so it gains two subfolders:

```
archive/agent/            answer_service.py (new), draft_service.py,
                          prompt_constants.py, retrieve_service.py,
                          retrieve_constants.py
archive/agent/route/      route_model.py, route_service.py,
                          route_constants.py
archive/agent/recipes/    recipe_model.py, aggregation_service.py,
                          invoice_parsing_utils.py, superseded_service.py,
                          recipe_constants.py
tests/agent/{route,recipes}/   mirrored
```

### Interfaces (frozen by T0)

- **`route/route_model.py`**
  - `QuestionFamily` (StrEnum): `direct`, `aggregation`, `superseded`,
    `multi_hop`.
  - `AmountMeasure` (StrEnum): `pre_tax`, `tax_included`.
  - `QuestionPlan` (pydantic), with LLM field descriptions:
    - `family`;
    - `client: str | None`;
    - `project_manager: str | None`;
    - `project_codes: list[str]`;
    - `date_from`, `date_to`, `as_of_date` (ISO `str | None`);
    - `measure: AmountMeasure | None`;
    - `policy_topic: str | None`.
- **`route/route_service.py`**: `plan_question(question: Question, llm:
  LlmGateway) -> QuestionPlan`.
  - It makes one `complete_json` call.
  - Codes come from `find_identifiers` and override the LLM's. Dates are
    checked with `date_parsing_utils` (a bad date becomes None).
  - On `LlmUnavailableError` or `LlmResponseError` it returns
    `QuestionPlan(family=direct)` plus the regex codes, and logs a warning.
- **`recipes/recipe_model.py`**
  - `RecipeResult(hits: list[SearchHit], draft: DraftAnswer | None = None,
    note: str | None = None)` as a frozen dataclass. With `draft` set, the
    draft LLM call is skipped.
  - `RecipeSearchPort` (Protocol): `hybrid_search` and `list_by_filter`.
- **`recipes/aggregation_service.py`**: `run_aggregation(question, plan,
  search, llm) -> RecipeResult | None`. None means "use direct".
- **`recipes/invoice_parsing_utils.py`**:
  - `parse_invoice(text) -> InvoiceFields` with `client`, `project_code`,
    `subtotal`, `total` as `Decimal | None`, plus each amount's source
    line;
  - `client_matches(candidate, wanted) -> bool`: normalised text, then
    containment or `difflib` ratio ≥ `CLIENT_MATCH_RATIO`.
- **`recipes/superseded_service.py`**: `run_superseded(question, plan,
  search) -> RecipeResult | None`.
- **`answer_service.py`**: `answer_question(question, search, llm) ->
  tuple[DraftAnswer, set[str]]`, returning the draft and the retrieved doc
  ids.
  - Flow: plan → dispatch on family → recipe or `retrieve` → `draft(...,
    note=result.note)` unless the recipe already drafted.
  - The retrieved ids are every doc a recipe listed or searched, so
    validation keeps their citations.
- **`draft_service.draft`** gains `note: str | None = None`, which renders
  into `USER_PROMPT`.
- **`run_service._answer_question`** calls `answer_question`, then
  `validate` as today.

### Data flow

```
question → plan_question (1 LLM) → aggregation | superseded | direct/multi_hop
  aggregation: list_by_filter(invoice, codes/date) [+ project sheets for manager]
               → Python filter (client) → parse amounts (regex)
               → LLM extract for regex misses (≤ 1 call) → Decimal sum → DraftAnswer
  superseded:  hybrid_search(policy) → series → list_by_filter(policy) → in-force pick
               → ordered hits + note → draft (1 LLM)
  direct:      retrieve (unchanged) → draft (1 LLM)
→ validate (unchanged)
```

## Tasks

| Task | What | Owns | Depends | Batch |
|---|---|---|---|---|
| T0 tracer | Create the `route/` and `recipes/` packages with the frozen models and Protocols. `plan_question` stub returns direct plus regex codes; recipe stubs return None. `answer_service.answer_question` dispatch. The `note` param in `draft` and the prompt. Wire `run_service`. No behavior change; existing tests pass and new dispatch tests are added. | `archive/agent/**`, `archive/pipeline/run_service.py`, `tests/agent/**`, `tests/pipeline/**` | none | 0 |
| T1 route | Real `plan_question`: prompt constants, the LLM call, regex merge, date check, fallback. `scripts/measure_route.py` prints family per sample vs gold. Tests with a fake LLM: merge, bad date, fallback. | `archive/agent/route/**`, `tests/agent/route/**`, `scripts/measure_route*.py`, `tests/scripts/test_measure_route.py` | T0 | A |
| T2 aggregation | `invoice_parsing_utils` (FR/EN lines, Decimal, client match) and `run_aggregation`: invoice selection, the manager → codes hop, the regex-miss LLM extraction (`ExtractedAmounts` schema), sum, DraftAnswer with evidence and citations, and fall back to direct. Tests on real-shaped invoice texts, typo'd lines, the fallback, and an empty match. | `archive/agent/recipes/{aggregation_service,invoice_parsing_utils}.py`, aggregation keys in `recipe_constants.py`, `tests/agent/recipes/test_{aggregation,invoice_parsing}*.py` | T0 | A |
| T3 superseded | `run_superseded`: find the series via a policy-filtered hybrid search and `plan.policy_topic`, list its versions, pick the version in force on `as_of_date` (`effective_from ≤ d < effective_to`, else the latest), order the hits, write the note. Tests: date inside, on the boundary and before v1; no series → None. | `archive/agent/recipes/superseded_service.py`, superseded keys in `recipe_constants.py`, `tests/agent/recipes/test_superseded*.py` | T0 | A |
| T4 integrate | Offline check script (fixed plans on the committed index → s07, s10 and s20 amounts). Run `measure_route`. Time a full sample run. Record the numbers. | `scripts/check_recipes*.py`, `tests/scripts/test_check_recipes.py` | A | B |

`recipe_constants.py` is shared by T2 and T3. T0 creates it with section
headers, and each task appends only under its own header. Any conflict at
merge is mechanical.

**Batches:**
- **0:** T0 alone (the tracer bullet).
- **A:** T1, T2 and T3 in parallel.
- **B:** T4.
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
- the main checkout's `index/` and `corpus/`;
- the kit's `samples/` path.

After the final merge, `pre-commit-review` (`reviewer` + `quality`) runs on
`BASE..HEAD`. Fix rounds use new slugs, up to about 2 cycles. The main
agent commits only `docs:` plan updates (this plan copied to `.plans/`, the
decisions log, and the roadmap's decision to drop the classifier).

## Verification

- **Per task:** the four checks run in its worktree. Every behavior change
  ships with tests. No test touches the network or a real model.
- **On B after each batch:** the full checks.
- **V** is a verification-only implement run on B, with no commits:
  1. `scripts/check_recipes.py` gives the exact gold amounts for s07, s10
     and s20.
  2. `scripts/measure_route.py` gets at least 15/16 answerable families
     right. This needs `LLM_*` in the environment, so the user runs it,
     or V runs it if the variables are set.
  3. A plan-call failure (fake gateway that raises) → direct path, exit 0.
- **Score:** the user runs `python answer.py samples/questions.jsonl
  answers.jsonl` and then `python score.py answers.jsonl --details`. The
  bar is ≥ 33.30 with aggregation 3/3, and s02, s11 and s18 must stay
  `not_found`. Log the wall time.

## Decisions log

- 2026-11-17: the router is regex plus one LLM plan call. The classifier
  and its generated training set are dropped to save time before the
  deadline (user choice).
- 2026-11-17: aggregation amounts are parsed by regex with exact Decimal,
  with an LLM extraction fallback for regex misses. Python always does the
  sum (user choice).
- 2026-11-17: aggregation covers invoices only. With no narrowing entity it
  falls back to direct, so "total revenue"-style unanswerables stay
  `not_found`.

## Subagent branches

- Batch 0: `feat/agent-dispatch` (T0).
- Batch A: `feat/route-plan` (T1), `feat/agg-recipe` (T2),
  `feat/superseded-recipe` (T3).
- Batch B: `feat/check-recipes` (T4).
- Fix round: `fix/superseded-pick` (LLM picks the policy series).

## Decisions log (implementation)

- 2026-11-17: superseded series vote (T3) is safe but inert on the
  samples. FR questions do not reach EN-only series (s01), and "Expense
  Claims Policy" ranks the wrong series (s12). Fix: one LLM call picks
  the series from the index's ~12 policy titles, or none. "Currently in
  force" uses today's date, so versions effective in 2027 are not
  current (user choice). `run_superseded` gains an `llm` parameter.
- 2026-11-17: T2 merge was 817 lines (≈420 tests), over the 700 soft
  budget; T4 399 lines. Both flagged and merged.

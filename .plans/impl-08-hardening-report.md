# Plan: step 08 first pass — README (`impl-08-hardening-report`, pass 1)

**Status:** in-progress (pass 1)
**BASE:** 17471bace84606151c142d9e392ce1fcdc6433f2 (`feat/hardening-report`)
**Subagent branches:** `docs/readme-first-pass`
**Parent:** `.plans/impl-00-roadmap.md` step 08, `CHALLENGE.md` "Livrable".

## Context

Step 05 is merged into `main` (`17471ba`, 45.00/45 on the samples).
Step 08 is the deliverable step. This first pass covers only the
README, which has to work for the jury now. Steps 06 and 07 come next,
and step 08 gets a second pass after them: the REPORT draft and PDF,
the robustness runs, the free angle and the demo link.

User choices (2026-11-17):
- Scope is the README only.
- Written in French.
- The REPORT will be Markdown first and become a PDF later (deferred).

## Acceptance criteria

`README.md` is in French and follows the template's sections, filled
with real content:
1. **Installation**: 2 steps at most, Python ≥ 3.11, with a Windows
   variant of the venv activation.
2. **Exécution**:
   - the env vars and the exact command;
   - the sample output line;
   - a note that the index is prebuilt and committed in `index/`;
   - a note that new PDFs in `corpus/` are indexed incrementally at
     startup;
   - a note that the dense model is downloaded at first launch, with
     BM25-only search as the fallback.
3. **Messages d'erreur**: the table quotes the **real** messages and
   exit codes, captured by running the command. The cases are:
   - a missing `LLM_*` variable;
   - a missing questions file;
   - an empty or missing `corpus/`;
   - an unreadable index;
   - wrong usage.
4. **Bibliothèques utilisées**: every pin in `requirements.txt`, with
   its exact version and one line on why it was chosen.
5. **Architecture en 3 lignes**:
   - ingest: pdfplumber, tables, metadata, a committed Qdrant index and
     an incremental sync;
   - agent: regex and an LLM plan router, the recipes (direct,
     aggregation, superseded) and multi-hop through identifier
     expansion and the draft loop;
   - validation: pydantic schemas, citations limited to retrieved docs,
     and the status rules.

   Plus the per-question and global budgets (60 s and 17 min).
6. **Angle libre** and **Démo**: clearly marked placeholders, to fill
   after step 07.
7. Every fact is checked against the code and `.plans/`: no invented
   features. There is no secret, and no model name is hard-coded as a
   requirement.

## Out of scope (pass 2, after 06/07)

- REPORT.md and REPORT.pdf.
- The robustness runs and the clean-venv timing.
- `scripts/evaluate.py`.
- The free angle and the demo.

## Execution

This is the light path: a single docs file with no interface.
1. Cut the orchestrator branch `B = feat/hardening-report` from `main`
   and record its BASE in `.plans/impl-08-hardening-report.md`.
2. One `implement` subagent writes the file, using the plan-workflow
   §6.1 worktree flow:
   - worktree `.claude/temp_worktree/readme-first-pass`;
   - branch `docs/readme-first-pass`;
   - owned file: `README.md` only.
3. The subagent captures the error messages by running `answer.py` with
   the main checkout's venv python. The questions are:
   - no `LLM_*` vars;
   - dummy vars with a nonexistent questions file;
   - dummy vars in the worktree, which has no `corpus/` because it is
     gitignored;
   - wrong argument count.

   No real LLM call is made.
4. The branch is merged `--no-ff` into B, and the worktree and branch
   are removed.

The main agent does not write the README inline. The pre-commit-review
skill applies only to code, so a single `reviewer` pass checks the
README against the code for factual accuracy. It is lean, given the
token limits.

## Verification

- The quoted error messages match the captured output.
- The library versions match `requirements.txt`.
- The checks stay green on B: `ruff check . --exclude .claude`,
  `ruff format --check . --exclude .claude`, `mypy --strict archive
  scripts answer.py`, `pytest -q`. Nothing in the code changes.

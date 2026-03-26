# Codex Audit Notes

Date: March 25, 2026
Agent: Codex
Mode: Read-only audit of repository contents and implementation behavior

## Purpose

This file records Codex audit findings and handoff notes for follow-up work by other agents. It is not a runtime instruction file; Codex runtime instructions live in `AGENTS.md`.

## Audit Findings

1. High: `analysis/R/meta_analysis.R`
   `build_summary_table()` exponentiates all pooled effects. That is correct for binary log-scale effects like RR, but incorrect for continuous mean differences such as LOS, weight, sodium, creatinine, and related outcomes. The generated summary table will therefore misreport continuous outcomes.

2. High: `pipeline/fulltext_screening.py`
   The script accepts `--screening-log` and defines `load_included_citations()`, but the main execution path never uses that screening log to constrain which PDFs are screened. In practice it screens every PDF in the directory, so the documented workflow is not enforced.

3. Medium: `extraction/scripts/llm_auditor.py`
   `final_extractions.json` is assembled from Model A as the base extraction and only patched with auditor-reviewed fields. Auto-accepted Level 1 and Level 2 disagreements are not incorporated into the final output, so resolved-but-not-audited disagreements can silently retain arbitrary Model A values.

4. Medium: `analysis/R/prepare_data.R`
   Denominator fallback is applied only when an outcome-N column is entirely missing or entirely `NA`. If only some rows are missing denominators, those rows remain `NA` instead of falling back row-by-row, which can exclude studies downstream.

5. Medium: `analysis/R/meta_analysis.R`
   Subgroup analyses derive subgroup vectors from a newly filtered `df` and apply them to an existing meta object with `update()`. Because the meta object may have been built from a different filtered subset and ordering, subgroup assignments may not align reliably with the studies actually analyzed.

## Additional Notes

- `AGENTS.md` is the authoritative Codex instruction file for this repository.
- `CLAUDE.md` appears to serve the parallel role for Claude Code.
- Existing user-owned worktree changes were present during the audit and were not modified:
  - `CLAUDE.md`
  - `agents_record.md`
  - `architecture.md`
  - `desal_trial.md`
- A non-writing Python syntax sanity check passed for the main pipeline scripts.

## Suggested Next Step

Claude Code should address the five findings above and then re-run a focused validation of:
- extraction finalization logic
- row-level denominator fallback
- subgroup alignment
- summary-table effect formatting
- full-text screening input constraints

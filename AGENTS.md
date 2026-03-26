# DESAL Project Context

## Agents Record (MANDATORY)
When you make ANY edit to files in this project, you MUST add a line to `agents_record.md` in the project root documenting what you did. Format: `**Agent Name** — Date: Brief description`. This is non-negotiable — the audit trail is part of the methodology.

## What This Is
A systematic review and meta-analysis of hypertonic saline co-administered with loop diuretics for acute decompensated heart failure, with trial sequential analysis. Registered on PROSPERO (CRD420261351795). The SR/MA is designed to inform a planned pragmatic RCT (DESAL) — see `desal_trial.md` for trial context and `trial/` for trial design files.

## People
- **Fernando G. Zampieri** — PI, leads trial design and SR/MA methodology
- **Justin A. Ezekowitz** — Co-PI, leads clinical operations and site selection (University of Alberta)

## SR/MA Overview
- **PICO:** HSS + loop diuretics vs loop diuretics ± isotonic/placebo in hospitalized ADHF adults (RCTs only)
- **Registration:** PROSPERO CRD420261351795
- **Databases:** PubMed, Embase, ClinicalTrials.gov
- **Analysis:** Random-effects (REML), RoB 2.0, GRADE, custom trial sequential analysis
- **Key sensitivity analysis:** Excluding Paterna/Tuttolomondo group (Palermo) — they dominate the literature with likely inflated effect sizes
- **Estimated yield:** ~494 PubMed hits (March 2026), ~600-700 total after Embase de-duplication
- **Existing evidence:** ~12-15 RCTs, dominated by single group (Paterna/Palermo)
- **Protocol:** `srma/DESAL_SRMA_Protocol.md`
- **Literature review:** `srma/HTS_AHF_Literature_Review.md`

## LLM-Assisted Pipeline
- Dual-model approach: Claude + GPT-5.4 (via Codex)
- API keys required: `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` as environment variables
- Screening: both models screen independently → auto-resolve agreements (confidence ≥0.70) → human reviews disagreements → 10% audit of auto-excludes with escalation protocol
- Extraction: Pydantic schema → both models extract → verify with clinical-data-extractor skill (Layers 1-4) → disagreement classifier (L0-5) → LLM auditor → human reviews remaining conflicts
- The clinical-data-extractor skill is at `clinical-data-extractor/` (and also at `~/.claude/skills/clinical-data-extractor/`)
- Full specification: `pipeline/DESAL_LLM_SRMA_Pipeline.md`
- Architecture and data flow: `architecture.md`

## Current Status (2026-03-25)

**All pipeline components: BUILT** (pre-specified before data exposure)

- Group 1 — Screening: screening orchestrator, full-text screening, prompt template, resolution logic
- Group 2 — Extraction: Pydantic schema (77+ fields), extraction orchestrator, disagreement classifier (L0-5), LLM auditor
- Group 3 — Analysis: prepare_data.R, meta_analysis.R (12 outcomes, 7 subgroups, 8 sensitivities), tsa.R (O'Brien-Fleming, RIS, D²)
- Reporting: PRISMA flow diagram, GRADE Summary of Findings

**Next steps:**
1. Set up Anthropic + OpenAI API keys
2. Run PubMed + Embase searches, export results
3. Run screening_orchestrator.py
4. Human review of disagreements + 10% audit
5. Full-text screening of included citations
6. Run extraction pipeline (orchestrate_extraction.py → compare_extractions.py → llm_auditor.py)
7. Human review of remaining extraction conflicts
8. Run prepare_data.R → meta_analysis.R → tsa.R
9. Write manuscript

## Key Documents
| Document | Purpose |
|---|---|
| `architecture.md` | Pipeline data flow, directory map, execution DAG, human decision points |
| `desal_trial.md` | Trial design context — why the SR/MA exists, how results inform the trial |
| `srma/DESAL_SRMA_Protocol.md` | PRISMA-P protocol with all pre-specified decision rules |
| `pipeline/DESAL_LLM_SRMA_Pipeline.md` | Full LLM pipeline specification |
| `agents_record.md` | Chronological audit trail of all agent edits |

## Key Statistics from Existing Literature
- Control median LOS: ~7 days
- Meta-analytic LOS reduction: 3.3-3.6 days (likely inflated by Palermo group)
- Meta-analytic mortality RR: ~0.55 (implausibly large for a diuretic adjunct)
- DESAL trial powers for: 1.0-day LOS reduction (WR ~1.27), ~one-third of published estimate

## Important Notes
- Fernando prefers Markdown (uses Typora) alongside PDF/Word deliverables
- Do NOT fabricate statistics or data — use [INSERT DATA] placeholders where needed
- The Paterna/Tuttolomondo sensitivity analysis is the most important methodological contribution of the SR/MA
- TSA uses custom R code, NOT the Copenhagen Trial Sequential Analysis software

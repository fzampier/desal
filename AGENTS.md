# DESAL Project Context

## What This Is
DESAL (Decongestion with Saline Loading) — a pragmatic, open-label, multicentre RCT of hypertonic saline vs standard of care in adults hospitalized with acute heart failure. This folder contains all project documents, analysis scripts, and the SR/MA pipeline specification.

## People
- **Fernando G. Zampieri** — PI, leads trial design and SR/MA methodology
- **Justin A. Ezekowitz** — Co-PI, leads clinical operations and site selection (likely University of Alberta)
- This trial is part of a broader HF platform trial infrastructure (two states: AHF and outpatient)

## Trial Design (DESAL)
- **Intervention:** 250 mL 3% NaCl IV over 30-60 min, up to 3 doses q6h within first 24h, + SOC
- **Control:** SOC alone (open-label, no placebo)
- **Population:** Adults ≥18, hospitalized or in ED with AHF, elevated BNP (threshold TBD)
- **Primary endpoint:** Day 14 hierarchical win ratio — Tier 1: all-cause death, Tier 2: days alive out of hospital (any readmission counts)
- **Stratification:** Baseline sodium (≤135 vs >135 mEq/L)
- **Sample size:** ~900 (450/arm), 80% power for WR 1.27 (~1-day LOS reduction)
- **Analysis:** Frequentist, stratified Mann-Whitney
- **Pre-specified subgroups:** HFpEF vs HFrEF, baseline sodium, baseline eGFR, SGLT2i use
- **No Health Canada submission** — minimal-risk pragmatic trial

## Systematic Review / Meta-Analysis
- SR/MA protocol written for PROSPERO registration
- Pairwise MA: HSS + loop diuretics vs loop diuretics ± isotonic/placebo in hospitalized ADHF (RCTs only)
- Databases: PubMed, Embase, ClinicalTrials.gov
- Random-effects (REML), RoB 2.0, GRADE, trial sequential analysis (custom R, not Copenhagen software)
- KEY sensitivity analysis: excluding Paterna/Tuttolomondo group (Palermo) — they dominate the literature with likely inflated effect sizes
- Search strategy: no RCT filter applied (design eligibility assessed during LLM screening); ~494 PubMed hits (March 2026), ~600-700 total estimated after Embase de-duplication
- Dual-LLM screening and extraction pipeline planned (see pipeline doc)

## LLM-Assisted Pipeline
- Dual-model approach: Codex + GPT-5.4 (Codex)
- API keys required: ANTHROPIC_API_KEY and OPENAI_API_KEY as environment variables
- Screening: both models screen independently → auto-resolve agreements (confidence ≥0.70 required) → human reviews disagreements → 10% audit of auto-excludes with escalation protocol
- Extraction: Pydantic schema → both models extract → verify with clinical-data-extractor skill (Layers 1-4) → disagreement classifier (L0-5) → LLM auditor → human reviews remaining conflicts
- The clinical-data-extractor skill is at `clinical-data-extractor/` in this folder (and also at ~/.Codex/skills/clinical-data-extractor/)
- Full pipeline specification in DESAL_LLM_SRMA_Pipeline.md

## Current Status (2026-03-24)

**Group 1 — Screening: COMPLETE** (pre-specified before data exposure)
- Screening prompt template (v1.0, locked)
- Screening resolution logic (confidence threshold 0.70, 10% audit of auto-excludes with escalation)
- Screening orchestration script (handles PubMed CSV, NBIB, Embase RIS; calls Codex + GPT-5.4 APIs; outputs screening log, summary, human review queue, audit sample, metrics)

**Group 2 — Extraction: COMPLETE** (pre-specified before data exposure)
- Pydantic extraction schema (77 top-level fields, nested arm characteristics + outcomes)
- Cross-model extraction orchestration (dual-API, skill verification layers 1-3)
- Disagreement classifier (Levels 0-5, deterministic thresholds)
- LLM auditor layer (alternating model to avoid self-bias, confidence threshold 0.80)

**Group 3 — Analysis: COMPLETE** (pre-specified before data exposure)
- Data preparation script (JSON → analysis-ready CSV, Wan et al. median/IQR conversion)
- Meta-analysis R scripts (meta/metafor, random-effects REML, forest/funnel plots, all subgroups + sensitivities)
- TSA R implementation (custom O'Brien-Fleming alpha spending, RIS calculation, D² adjustment, TSA plots)

**Next steps:**
1. Register on PROSPERO
2. Set up Anthropic + OpenAI API keys
3. Run PubMed + Embase searches, export results
4. Run screening_orchestrator.py
5. Human review of disagreements + 10% audit
6. Full-text screening of included citations
7. Run extraction pipeline (orchestrate_extraction.py → compare_extractions.py → llm_auditor.py)
8. Human review of remaining extraction conflicts
9. Run prepare_data.R → meta_analysis.R → tsa.R
10. Write manuscript

## Files in This Folder

### Root
- `AGENTS.md` — This file (project context and instructions)

### `trial/` — Trial design, power analysis, sample size
- `DESAL_Trial_Synopsis.md` / `.pdf` — Trial synopsis with power curves figure
- `desal_power_curves.png` — Simulation-based power curves
- `desal_power_results.csv` — Full simulation results
- `desal_power_analysis.py` — Power simulation script (Python)
- `win_ratio_sample_size.R` — Formula-based sample size calculator (R)
- `win_ratio_sample_size.py` — Same in Python
- `win_ratio_sample_sizes.csv` — Formula-based results across WR/tie scenarios

### `srma/` — Systematic review / meta-analysis protocol and literature
- `DESAL_SRMA_Protocol.md` / `.pdf` — SR/MA protocol for PROSPERO
- `HTS_AHF_Literature_Review.md` — Literature search summary

### `pipeline/` — LLM-assisted screening and extraction pipeline
- `DESAL_LLM_SRMA_Pipeline.md` — Full LLM pipeline specification
- `screening_prompt_template.md` — Pre-specified screening prompt for both LLMs (v1.0, locked before data exposure)
- `screening_resolution_logic.md` — Decision matrix and resolution rules for dual-LLM screening
- `screening_orchestrator.py` — Title/abstract screening (both APIs, resolution, audit sampling, fuzzy dedup)
- `fulltext_screening.py` — Full-text PDF screening with expanded exclusion criteria
- `screening_README.md` — Usage instructions for the orchestrator

### `extraction/` — Data extraction pipeline (Group 2)
- `schema/study_extraction.py` — Pydantic schema (StudyExtraction model, 77 fields)
- `scripts/orchestrate_extraction.py` — Dual-LLM extraction orchestrator
- `scripts/compare_extractions.py` — Disagreement classifier (Levels 0-5)
- `scripts/llm_auditor.py` — LLM auditor layer
- `pdfs/`, `extracted_text/`, `extracted_tables/`, `data/` — Runtime directories

### `analysis/` — Meta-analysis and TSA (Group 3)
- `R/prepare_data.R` — Convert final_extractions.json → analysis_ready.csv
- `R/meta_analysis.R` — Random-effects MA, forest/funnel plots, subgroups + 8 sensitivity analyses
- `R/tsa.R` — Custom trial sequential analysis (O'Brien-Fleming, RIS, D² adjustment)
- `data/`, `output/` — Runtime directories

### `reporting/` — PRISMA and GRADE
- `prisma_flow.R` — PRISMA 2020 flow diagram (LLM-annotated)
- `grade_sof.R` — GRADE Summary of Findings table

### `clinical-data-extractor/` — Skill for verifying extracted data
- `SKILL.md` — Skill definition
- `scripts/` — Supporting scripts

## Key Statistics
- Control median LOS: ~7 days
- D14 mortality: ~4.5%
- Readmission rate: ~10%
- Meta-analytic LOS reduction (existing lit): 3.3-3.6 days (likely inflated)
- DESAL powers for: 1.0-day LOS reduction (WR ~1.27)
- Existing evidence: ~12-15 RCTs, dominated by single group (Paterna/Palermo)

## Important Notes
- Fernando prefers Markdown (uses Typora) alongside PDF/Word deliverables
- Do NOT fabricate statistics or data — use [INSERT DATA] placeholders where needed
- The Paterna/Tuttolomondo sensitivity analysis is the most important methodological contribution of the SR/MA
- Win ratio methodology: Fernando is familiar with R packages (WWR/WRestimate) and the Dong et al. 2020 variance formula
- TSA should use custom R code, not the Copenhagen Trial Sequential Analysis software

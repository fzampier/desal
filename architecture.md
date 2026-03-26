# DESAL Project Architecture

## Overview

This project implements a systematic review and meta-analysis of hypertonic saline for acute decompensated heart failure, using a dual-LLM pipeline (Claude + GPT-5.4) for screening and data extraction. The pipeline replaces the traditional dual-human reviewer approach with dual-AI reviewers, retaining human adjudication for disagreements and a 10% audit of auto-excludes.

The approach builds on emerging work in LLM-assisted systematic reviews (Delgado-Chaves et al. 2025, PNAS; Galli et al. 2025, Information; Khan et al. 2025, JAMIA; Chen et al. 2026, Nat Med), extending these with dual-model adjudication, confidence-gated auto-resolution, a four-layer numerical verification system, and pre-specified disagreement taxonomy. See `pipeline/DESAL_LLM_SRMA_Pipeline.md` (Methodological Precedent section) for detailed positioning.

The methodology is pre-specified, version-controlled, and registered on PROSPERO (CRD420261351795). All analysis code was committed before data exposure.

## Data Flow

```
                        PubMed (.nbib)
                        Embase (.ris)          ─── Search Phase
                        ClinicalTrials.gov         (manual)
                              │
                              ▼
                    ┌─────────────────────┐
                    │   De-duplication     │    ─── DOI, PMID, fuzzy title
                    │  (Levenshtein ≤ 3)  │        (screening_orchestrator.py)
                    └─────────┬───────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │   Title/Abstract Screening    │ ─── screening_orchestrator.py
              │                               │
              │  Claude ──┐    ┌── GPT-5.4    │     Dual-LLM, independent
              │           ▼    ▼              │
              │      Resolution Logic         │     Confidence ≥ 0.70
              │           │                   │
              │     ┌─────┼──────┐            │
              │     ▼     ▼      ▼            │
              │   Auto   Auto   Human         │
              │  Include Exclude Review        │
              │           │                   │
              │      10% Audit                │     Escalation protocol
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   Full-Text Screening         │ ─── fulltext_screening.py
              │   (PDF → pdftotext → LLMs)    │     Same resolution logic
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   Data Extraction             │ ─── orchestrate_extraction.py
              │                               │
              │  PDF → text + tables           │     pdftotext + extract_tables.py
              │         │                     │
              │    Claude extracts             │     → Pydantic schema
              │    Verify (Layers 1-3)         │     → clinical-data-extractor
              │         │                     │
              │    GPT-5.4 extracts            │     → same schema
              │    Verify (Layers 1-3)         │     → same verification
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   Disagreement Classification │ ─── compare_extractions.py
              │                               │
              │   Level 0: Perfect agreement   │     Auto-accept
              │   Level 1: Trivial (rounding)  │     Auto-accept
              │   Level 2: Minor difference    │     Auto if both verified
              │   Level 3: Moderate            │     → LLM Auditor
              │   Level 4: Major               │     → LLM Auditor
              │   Level 5: Structural          │     → LLM Auditor
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   LLM Auditor                 │ ─── llm_auditor.py
              │                               │
              │   Alternating model            │     Avoids self-bias
              │   Source text + tables          │
              │   Confidence ≥ 0.80 → accept   │
              │   Confidence < 0.80 → human    │
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   Human Review                │ ─── Fernando (PI)
              │   Remaining conflicts only     │
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   final_extractions.json       │
              │         │                     │
              │   prepare_data.R               │ ─── JSON → analysis_ready.csv
              │   (Wan et al. median/IQR       │     Subgroup categories
              │    conversion)                 │     Per-outcome N fallback
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   Meta-Analysis               │ ─── meta_analysis.R
              │                               │
              │   Random-effects (REML)        │     12 outcomes
              │   Forest plots                 │     7 subgroups
              │   Funnel plots + Egger's       │     8 sensitivity analyses
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   Trial Sequential Analysis   │ ─── tsa.R
              │                               │
              │   O'Brien-Fleming boundaries   │     Mortality, LOS, readmission
              │   Required Information Size    │     D² heterogeneity adjustment
              │   Conclusive / Inconclusive    │     Informs DESAL sample size
              └───────────┬───────────────────┘
                          │
                          ▼
              ┌───────────────────────────────┐
              │   Reporting                   │
              │                               │
              │   prisma_flow.R                │     LLM-annotated PRISMA 2020
              │   grade_sof.R                  │     GRADE Summary of Findings
              └───────────────────────────────┘
```

## Directory Map

```
DESAL/
├── CLAUDE.md                     Agent instructions (Claude Code)
├── AGENTS.md                     Agent instructions (Codex/Dispatch)
├── README.md                     Public-facing project description
├── LICENSE                       CC BY 4.0
├── architecture.md               This file
├── desal_trial.md                Trial design context (references trial/)
├── agents_record.md              Audit trail of all agent edits
│
├── srma/                         SR/MA Protocol and Literature
│   ├── DESAL_SRMA_Protocol.md    PRISMA-P protocol (PROSPERO CRD420261351795)
│   └── HTS_AHF_Literature_Review.md  Annotated literature review
│
├── pipeline/                     Screening Pipeline
│   ├── DESAL_LLM_SRMA_Pipeline.md    Full pipeline specification
│   ├── screening_prompt_template.md   T/A screening prompt (v1.0, locked)
│   ├── screening_resolution_logic.md  Dual-LLM resolution rules
│   ├── screening_orchestrator.py      T/A screening (dual-API, fuzzy dedup)
│   ├── fulltext_screening.py          Full-text screening (dual-API)
│   └── screening_README.md            Usage instructions
│
├── extraction/                   Data Extraction Pipeline
│   ├── schema/
│   │   ├── __init__.py
│   │   └── study_extraction.py   Pydantic schema (77+ fields)
│   ├── scripts/
│   │   ├── orchestrate_extraction.py  Dual-LLM extraction + verification
│   │   ├── compare_extractions.py     Disagreement classifier (L0-5)
│   │   └── llm_auditor.py            Auditor triage layer
│   ├── pdfs/                     Included study PDFs (populated at runtime)
│   ├── extracted_text/           pdftotext outputs (generated)
│   ├── extracted_tables/         Table JSONs (generated)
│   └── data/                     Extraction outputs (generated)
│
├── analysis/                     Statistical Analysis
│   ├── R/
│   │   ├── prepare_data.R        JSON → analysis-ready CSV
│   │   ├── meta_analysis.R       RE meta-analysis + subgroups + sensitivities
│   │   └── tsa.R                 Custom trial sequential analysis
│   ├── data/                     analysis_ready.csv (generated)
│   └── output/                   Plots and summaries (generated)
│
├── clinical-data-extractor/      Verification Skill (4 Layers)
│   ├── SKILL.md                  Skill definition
│   └── scripts/
│       ├── anchor_extract.py     L1: Anchor-based extraction
│       ├── verify_numbers.py     L2: Text verification
│       ├── verify_with_tables.py L3: Table verification + context
│       ├── benford_check.py      L4: Benford's law check
│       ├── extract_tables.py     PDF table extraction
│       └── run_tests.py          Test suite
│
├── reporting/                    PRISMA and GRADE
│   ├── prisma_flow.R             PRISMA 2020 flow diagram
│   └── grade_sof.R               GRADE Summary of Findings
│
└── trial/                        Trial Design (local only, not in git)
    ├── DESAL_Trial_Synopsis.md/pdf
    ├── desal_power_analysis.py
    ├── desal_power_curves.png
    ├── desal_power_results.csv
    ├── win_ratio_sample_size.R/py
    └── win_ratio_sample_sizes.csv
```

## Pipeline Stages in Detail

### Stage 1: Search (Manual)
- **Input:** Search strategies from protocol Section 3c
- **Databases:** PubMed/MEDLINE, Embase, ClinicalTrials.gov
- **Output:** Exported citation files (.nbib, .ris, .csv)
- **No code** — manual database searches with pre-specified strategies

### Stage 2: Title/Abstract Screening (`screening_orchestrator.py`)
- **Input:** Citation export files
- **Process:** Ingest → deduplicate (DOI, PMID, fuzzy title) → dual-LLM screening → resolution → audit sampling
- **APIs:** Anthropic (Claude), OpenAI (GPT-5.4)
- **Output:** `screening_log.json`, `screening_summary.csv`, `human_review_queue.csv`, `audit_sample.csv`, `screening_metrics.json`
- **Human input required:** Review disagreements, review 10% audit sample

### Stage 3: Full-Text Screening (`fulltext_screening.py`)
- **Input:** PDFs of included/uncertain citations
- **Process:** pdftotext → dual-LLM screening with expanded exclusion criteria → same resolution logic
- **Output:** `fulltext_screening_log.json`, `fulltext_screening_summary.json`
- **Human input required:** Review disagreements, adjudicate borderline cases (e.g., overlapping cohorts)

### Stage 4: Data Extraction (`orchestrate_extraction.py`)
- **Input:** PDFs of final included studies
- **Process:** Per study: PDF → text + tables → Claude extracts → verify (Layers 1-3) → GPT extracts → verify (Layers 1-3)
- **Output:** `extraction_log.json`, `claude_extractions.json`, `gpt_extractions.json`

### Stage 5: Disagreement Classification (`compare_extractions.py`)
- **Input:** `extraction_log.json`
- **Process:** Cell-by-cell comparison, classify into Levels 0-5
- **Output:** `disagreements.json`, `auditor_queue.json`

### Stage 6: LLM Auditor (`llm_auditor.py`)
- **Input:** `auditor_queue.json`, `extraction_log.json`
- **Process:** Alternating LLM reviews disputed fields with source text context
- **Output:** `auditor_report.json`, `human_review_extraction.json`, `final_extractions.json`
- **Human input required:** Review fields where auditor confidence < 0.80

### Stage 7: Data Preparation (`prepare_data.R`)
- **Input:** `final_extractions.json`
- **Process:** Flatten JSON → CSV, Wan et al. median/IQR conversion, create subgroup categories, per-outcome N fallback chain
- **Output:** `analysis_ready.csv`

### Stage 8: Meta-Analysis (`meta_analysis.R`)
- **Input:** `analysis_ready.csv`
- **Process:** Random-effects MA (REML) for 12 outcomes, 7 subgroup analyses, 8 sensitivity analyses, forest plots, funnel plots
- **Output:** Forest plot PDFs, funnel plot PDFs, `meta_analysis_summary.csv`

### Stage 9: Trial Sequential Analysis (`tsa.R`)
- **Input:** `analysis_ready.csv`
- **Process:** Cumulative MA ordered by year, O'Brien-Fleming boundaries, RIS calculation with D² adjustment
- **Output:** TSA plot PDFs/PNGs, `tsa_summary.csv`
- **Key output:** Conclusive vs inconclusive determination; RIS deficit informs DESAL

### Stage 10: Reporting (`prisma_flow.R`, `grade_sof.R`)
- **Input:** Screening metrics, meta-analysis summary
- **Output:** PRISMA 2020 flow diagram (LLM-annotated), GRADE Summary of Findings table

## Human Decision Points

The pipeline pauses for human input at these stages:

| Stage | Decision | Who |
|-------|----------|-----|
| T/A Screening | Adjudicate disagreements between models | Fernando |
| T/A Screening | Review 10% audit of auto-excludes; trigger escalation if misses found | Fernando |
| Full-Text Screening | Adjudicate disagreements; decide overlapping Palermo cohorts | Fernando |
| Full-Text Screening | Confirm SALT-HF exclusion from primary (ambulatory population) | Fernando |
| Extraction | Review Level 3-5 disagreements where auditor confidence < 0.80 | Fernando |
| Analysis | Interpret subgroup interactions; GRADE domain judgments | Fernando + Justin |
| TSA | Interpret conclusive/inconclusive; decide DESAL implications | Fernando + Justin |

## Execution Order (DAG)

```
Search (manual)
    │
    ▼
screening_orchestrator.py ──→ Human review of disagreements + audit
    │
    ▼
fulltext_screening.py ──→ Human adjudication of borderline cases
    │
    ▼
orchestrate_extraction.py
    │
    ▼
compare_extractions.py
    │
    ▼
llm_auditor.py ──→ Human review of low-confidence fields
    │
    ▼
prepare_data.R
    │
    ├──→ meta_analysis.R ──→ forest/funnel plots
    │
    ├──→ tsa.R ──→ TSA plots, conclusive/inconclusive
    │
    └──→ prisma_flow.R + grade_sof.R ──→ PRISMA diagram, GRADE table
```

## Dependencies

### Python
`pydantic>=2.0`, `anthropic`, `openai`, `pandas`, `rispy`, `pyyaml`, `camelot-py[cv]`, `pdfplumber`

### R
`meta`, `metafor`, `dplyr`, `readr`, `ggplot2`, `jsonlite`

### System
`poppler-utils` (pdftotext), `ghostscript` (camelot table extraction)

### API Keys
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` as environment variables

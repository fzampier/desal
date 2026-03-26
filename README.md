# DESAL — Decongestion with Saline Loading

A systematic review of hypertonic saline for acute heart failure designed to inform a possible trial.

**Principal Investigators:** Fernando G. Zampieri, Justin A. Ezekowitz

## Repository Structure

```
srma/                  SR/MA protocol (PRISMA-P) and literature review
pipeline/              Dual-LLM screening pipeline (Claude + GPT-5.4)
extraction/            Data extraction pipeline (Pydantic schema, orchestrator, disagreement classifier, LLM auditor)
analysis/              Meta-analysis (R/meta, R/metafor) and custom trial sequential analysis
clinical-data-extractor/  Multi-layer verification skill for numerical data
reporting/             PRISMA flow diagram and GRADE Summary of Findings
```

## Systematic Review: Dual-LLM Pipeline

This project uses a novel dual-LLM approach for systematic review screening and data extraction. Two independent LLMs (Claude and GPT-5.4) screen and extract in parallel, with pre-specified resolution logic, human audit of auto-excludes, and a multi-layer verification system to catch LLM hallucinations.

The full methodology is documented in `pipeline/DESAL_LLM_SRMA_Pipeline.md`.

### Pipeline Components

| Component | Status | Location |
|-----------|--------|----------|
| SR/MA Protocol (PRISMA-P) | Pre-specified | `srma/DESAL_SRMA_Protocol.md` |
| Screening prompt + resolution logic | Pre-specified | `pipeline/` |
| Title/abstract screening orchestrator | Built | `pipeline/screening_orchestrator.py` |
| Full-text screening | Built | `pipeline/fulltext_screening.py` |
| Pydantic extraction schema | Pre-specified | `extraction/schema/study_extraction.py` |
| Extraction orchestrator | Built | `extraction/scripts/orchestrate_extraction.py` |
| Disagreement classifier (L0-5) | Built | `extraction/scripts/compare_extractions.py` |
| LLM auditor | Built | `extraction/scripts/llm_auditor.py` |
| Clinical data extractor (4 layers) | Built | `clinical-data-extractor/` |
| Meta-analysis R scripts | Built | `analysis/R/meta_analysis.R` |
| Trial sequential analysis | Built | `analysis/R/tsa.R` |
| Data preparation | Built | `analysis/R/prepare_data.R` |
| PRISMA flow diagram | Built | `reporting/prisma_flow.R` |
| GRADE Summary of Findings | Built | `reporting/grade_sof.R` |

All pipeline code was pre-specified and committed before data exposure. The git history serves as evidence of pre-specification.

## Outcomes

**Primary:** All-cause mortality

**Secondary:**
- Length of hospital stay
- Heart failure readmission
- Body weight change
- 24-hour urine output
- 24-hour natriuresis (urine sodium excretion)
- Serum sodium change
- Serum chloride change
- Serum creatinine change
- BNP/NT-proBNP change

**Safety:**
- Hypernatremia events (Na >145 mEq/L)
- Acute kidney injury
- Troponin elevation

## Pre-Specified Methodological Decisions

- **Overlapping cohorts:** Decision rules for mapping Palermo group publications to unique cohorts (largest sample / longest follow-up retained)
- **Zero-event handling:** Exclude zero-zero studies; 0.5 continuity correction for one-arm zeros; TACC sensitivity analysis
- **Crossover trials:** First-period data preferred; combined crossover data included in sensitivity analysis only
- **Ambulatory populations:** Excluded from primary analysis (PICO requires hospitalized ADHF); included in broadened-population sensitivity
- **Outcome timepoints:** Longest follow-up for mortality/readmission; 48-72h for physiological outcomes
- **8 pre-specified sensitivity analyses** including exclusion of Palermo group, high RoB studies, crossover trials, fixed-effect model, leave-one-out, broadened population, TACC, and alternative timepoints

## Requirements

### Python
```
pydantic>=2.0
anthropic
openai
pandas
rispy
pyyaml
camelot-py[cv]
pdfplumber
```

### R
```
meta
metafor
dplyr
readr
ggplot2
jsonlite
```

### System
```
poppler-utils (pdftotext)
ghostscript (for camelot table extraction)
```

### API Keys
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

## Running the Pipeline

```bash
# 1. Title/abstract screening
python pipeline/screening_orchestrator.py --input pubmed.nbib embase.ris --format auto

# 2. Full-text screening
python pipeline/fulltext_screening.py --pdfs path/to/pdfs/

# 3. Data extraction
python extraction/scripts/orchestrate_extraction.py --pdfs extraction/pdfs/

# 4. Compare extractions
python extraction/scripts/compare_extractions.py extraction/data/extraction_log.json

# 5. LLM auditor
python extraction/scripts/llm_auditor.py \
  --queue extraction/data/auditor_queue.json \
  --extraction-log extraction/data/extraction_log.json

# 6. Prepare data for analysis
Rscript analysis/R/prepare_data.R --input extraction/data/final_extractions.json

# 7. Run meta-analysis
Rscript analysis/R/meta_analysis.R --data analysis/data/analysis_ready.csv

# 8. Run trial sequential analysis
Rscript analysis/R/tsa.R --data analysis/data/analysis_ready.csv

# 9. Generate PRISMA diagram and GRADE table
Rscript reporting/prisma_flow.R
Rscript reporting/grade_sof.R
```

## License

This work is licensed under a [Creative Commons Attribution 4.0 International License](http://creativecommons.org/licenses/by/4.0/). See [LICENSE](LICENSE) for details.

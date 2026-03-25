# DESAL — Decongestion with Saline Loading

A pragmatic, open-label, multicentre, randomized controlled trial of hypertonic saline for acute heart failure, with an accompanying systematic review and meta-analysis.

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
| Meta-analysis R scripts | Pre-specified | `analysis/R/meta_analysis.R` |
| Trial sequential analysis | Pre-specified | `analysis/R/tsa.R` |
| PRISMA flow diagram | Built | `reporting/prisma_flow.R` |
| GRADE Summary of Findings | Built | `reporting/grade_sof.R` |

All pipeline code was pre-specified and committed before data exposure. The git history serves as evidence of pre-specification.

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

This protocol and analysis code are made available for transparency and reproducibility. Please cite appropriately if reusing.

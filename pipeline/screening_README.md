# DESAL Screening Orchestrator

Dual-LLM screening pipeline for the DESAL systematic review. Screens citations independently with Claude and GPT-5.4, applies pre-specified resolution logic, and produces structured output files.

## Setup

```bash
pip install anthropic openai pandas rispy pyyaml
```

Set API keys as environment variables:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

## Usage

Screen a PubMed CSV export:

```bash
python screening_orchestrator.py --input pubmed_results.csv --format csv
```

Screen multiple files with auto-detection:

```bash
python screening_orchestrator.py --input pubmed.nbib embase.ris --format auto
```

Specify output directory and models:

```bash
python screening_orchestrator.py \
  --input pubmed.nbib embase.ris \
  --format auto \
  --output-dir ./screening_output/ \
  --claude-model claude-opus-4-6 \
  --gpt-model gpt-5.4 \
  --confidence-threshold 0.70 \
  --audit-fraction 0.10 \
  --seed 42 \
  --delay 0.5
```

Resume after interruption (skips already-screened citations):

```bash
python screening_orchestrator.py \
  --input pubmed.nbib embase.ris \
  --format auto \
  --output-dir ./screening_output/ \
  --resume
```

## Output Files

All saved to `--output-dir` (default: `./screening_output/`):

- `screening_log.json` — Complete log with both models' full outputs and resolution for every citation. Saved incrementally after each citation (enables `--resume`).
- `screening_summary.csv` — One row per citation with decisions, confidences, resolution method, and flags.
- `human_review_queue.csv` — Citations routed to human review with both models' rationales and the abstract.
- `audit_sample.csv` — Random 10% of auto-excludes selected for human audit (fixed seed for reproducibility).
- `screening_metrics.json` — Cohen's kappa, percent agreement, confidence distributions, auto-resolution rate, and category counts.

## Resolution Logic

Follows `screening_resolution_logic.md` v1.0:

- Both INCLUDE with confidence ≥0.70 → auto-include
- Both EXCLUDE with confidence ≥0.70 → auto-exclude (10% audited)
- Any confidence <0.70 on an agreement → human review
- Any disagreement → human review
- Any UNCERTAIN → human review
- Model errors → human review

## Input Formats

- **PubMed CSV**: Expects columns PMID, Title, Abstract, Authors, Journal, Year, DOI (case-insensitive).
- **PubMed NBIB/MEDLINE**: Standard NBIB export from PubMed.
- **Embase RIS**: Standard RIS export. Parsed via the `rispy` library.

De-duplication is performed by DOI and PMID matching across all input files.

## Programmatic Use

```python
from screening_orchestrator import run

metrics = run(
    input_paths=["pubmed.nbib", "embase.ris"],
    fmt="auto",
    output_dir="./screening_output/",
    confidence_threshold=0.70,
)
print(metrics["cohens_kappa"])
```

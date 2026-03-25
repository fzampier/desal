---
name: clinical-data-extractor
description: Extract and verify numerical claims from clinical research papers against source text and tables
---

# Clinical Data Extractor

A multi-layered system for extracting and verifying numerical data from clinical research papers. Designed to catch LLM hallucinations and fabricated statistics.

## Overview

Four verification layers, each catching different failure modes:

| Layer | Script | Catches | Requirements |
|-------|--------|---------|--------------|
| 1. Anchor Extraction | `anchor_extract.py` | Numbers without semantic context | Source text |
| 2. Text Verification | `verify_numbers.py` | Completely invented numbers | Source text |
| 3. Table Verification | `verify_with_tables.py` | Context mismatches (human-aided) | PDF tables |
| 4. Benford Check | `benford_check.py` | Systematic fabrication patterns | 50+ numbers |

## Quick Start

```bash
# 1. Extract text from PDF
pdftotext paper.pdf paper.txt

# 2. Extract tables
python3 scripts/extract_tables.py paper.pdf paper_tables.json

# 3. Anchor-based extraction (constrained by semantic context)
python3 scripts/anchor_extract.py paper.txt

# 4. Verify LLM-generated claims against source
python3 scripts/verify_with_tables.py paper_tables.json claims.json paper.txt

# 5. Benford check for large extractions (optional)
python3 scripts/benford_check.py paper_tables.json
```

## Layer 1: Anchor-Based Extraction

**Purpose:** Extract numbers only when they appear near semantically relevant context.

```bash
python3 scripts/anchor_extract.py paper.txt [output.json]
```

**How it works:**
- Defines anchor patterns for each field type (e.g., mortality anchors: "mortality", "death", "died", "survival")
- Only extracts numbers within a window (typically 250-600 chars) of relevant anchors
- Prevents extracting "62" from "SAPS 39-62" when looking for mortality

**Key insight:** This is the inverse of verification — constrain extraction upfront rather than filtering afterward.

**Example anchors:**
```python
A_MORTALITY = ["mortality", "death(s)?", "died", "survival", "fatal"]
A_RANDOM = ["randomized", "allocated", "enrolled", "recruited"]
A_CI = ["95% CI", "confidence interval"]
```

## Layer 2: Text Verification

**Purpose:** Verify claimed numbers exist in source text.

```bash
python3 scripts/verify_numbers.py paper.txt claims.json
```

**What it catches:**
- Completely invented numbers
- Transposed digits (efficacy vs safety)
- Wrong units

**Output categories:**
- ✓ VERIFIED: Number found in text
- ✗ UNVERIFIED: Number not found (likely fabrication)
- ⚠️ CITATION_ONLY: Found only in references (suspicious)

## Layer 3: Table Verification

**Purpose:** Display exact context for human review, catch semantic mismatches.

```bash
# Extract tables first
python3 scripts/extract_tables.py paper.pdf tables.json

# Verify with context display
python3 scripts/verify_with_tables.py tables.json claims.json paper.txt
```

**Key feature:** Shows WHERE numbers appear, enabling 5-second human verification:
```
✓ '62' found at:
    → Page 3: "SAPS II 51 (39-62)"     ← Obviously not mortality!
```

**What it catches (with human review):**
- Numbers that exist in wrong context
- Values from table headers/footnotes
- Statistical values confused with outcomes

## Layer 4: Benford's Law Check

**Purpose:** Detect systematic fabrication in large extractions.

```bash
python3 scripts/benford_check.py tables.json
```

**How it works:**
- Natural data follows Benford's Law (leading digit 1 appears ~30%, 9 appears ~5%)
- Fabricated "random" numbers cluster in middle digits (4-7)
- Flags aggregate statistical anomalies

**What it catches:**
- LLM generating plausible-looking but fabricated datasets
- Human-invented "random" numbers

**Limitations:**
- Requires 50+ numbers for statistical power
- Clinical data may legitimately deviate (constrained ranges)
- Does NOT catch individual fabrications

## Recommended Workflow

### For verifying LLM-generated summaries:
```bash
# Extract source data
pdftotext paper.pdf paper.txt
python3 scripts/extract_tables.py paper.pdf tables.json

# Verify each claim
python3 scripts/verify_with_tables.py tables.json llm_claims.json paper.txt

# Review flagged items manually (context makes this fast)
```

### For systematic extraction:
```bash
# Anchor-based extraction (constrained)
python3 scripts/anchor_extract.py paper.txt extracted.json

# Verify extracted values against tables
python3 scripts/verify_with_tables.py tables.json extracted_claims.json paper.txt

# Benford sanity check
python3 scripts/benford_check.py tables.json
```

## Detection Rates

Tested on 6S, 3CPO, and ANIST trials with fabricated claims:

| Detection Method | Auto-Caught | Flagged | With Human Review |
|-----------------|-------------|---------|-------------------|
| Text only (v1) | 33% | 0% | 33% |
| Text + context (v2) | 50% | 17% | 100% |
| Tables + context | 50% | 17% | 100% |

**Key finding:** Context display enables 100% detection with human review. Review time: ~5 seconds per claim.

## Limitations

**Cannot detect automatically:**
- Semantic mismatches where numbers coincidentally exist
- Same-sentence context swaps (requires NLP)
- Plausible but wrong values within expected ranges

**Requires human judgment:**
- Final verification of flagged items
- Interpreting context display
- Domain expertise for edge cases

## File Formats

### Claims JSON (input)
```json
[
  {"claim": "90-day mortality was 51%", "numbers": ["90", "51"], "category": "outcome"},
  {"claim": "798 patients randomized", "numbers": ["798"], "category": "enrollment"}
]
```

### Verification output
```json
{
  "claim": "90-day mortality was 51%",
  "numbers": {"51": {"status": "TABLE_VERIFIED", "locations": [...]}},
  "overall_status": "VERIFIED"
}
```

## Dependencies

- Python 3.8+
- pdftotext (poppler-utils)
- camelot-py[cv] (table extraction)
- pdfplumber (fallback)

```bash
pip install camelot-py[cv] pdfplumber
apt-get install poppler-utils ghostscript
```

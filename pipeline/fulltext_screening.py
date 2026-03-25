#!/usr/bin/env python3
"""
DESAL Systematic Review — Full-Text Screening v1.0

Screens included/uncertain citations from title/abstract screening at the
full-text level using dual-LLM approach (same resolution logic).

Per pipeline doc Section 2.4:
  1. Full-text PDFs → pdftotext
  2. Both models screen with expanded exclusion criteria
  3. Same resolution logic as title/abstract screening

Additional exclusion criteria at full-text:
  - Not hospitalized acute heart failure
  - Not an RCT (quasi-randomized, observational)
  - No hypertonic saline intervention (>0.9% NaCl)
  - Duplicate publication of same trial data
  - Conference abstract only without sufficient data
  - Pediatric population

Usage:
    python fulltext_screening.py \
        --pdfs path/to/pdfs/ \
        --screening-log screening_output/screening_log.json \
        --output fulltext_screening_output/

Environment variables required:
    ANTHROPIC_API_KEY
    OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Reuse components from the title/abstract screening orchestrator
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from screening_orchestrator import (
    _call_model_safe,
    _model_error_entry,
    _parse_model_response,
    call_claude,
    call_gpt,
    compute_metrics,
    resolve_decision,
    save_screening_log,
    select_audit_sample,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CLAUDE_MODEL = "claude-opus-4-6"
DEFAULT_GPT_MODEL = "gpt-5.4"
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_AUDIT_FRACTION = 0.10
DEFAULT_DELAY = 1.0
MAX_TEXT_CHARS = 120_000  # ~30k tokens


# ============================================================================
# 1. FULL-TEXT SCREENING PROMPT
# ============================================================================

FULLTEXT_SYSTEM_PROMPT = """You are a systematic review screening assistant performing FULL-TEXT screening. You have been given the full text of a study identified during title/abstract screening as potentially eligible. Your task is to determine whether this study should be INCLUDED or EXCLUDED from the systematic review.

### Review Question
Does intravenous hypertonic saline, co-administered with loop diuretics, improve clinical outcomes in adults hospitalized with acute decompensated heart failure?

### Eligibility Criteria

POPULATION:
- INCLUDE: Adults (≥18 years) HOSPITALIZED with acute decompensated heart failure (ADHF), acute heart failure (AHF), or acutely decompensated chronic heart failure
- EXCLUDE: Ambulatory/outpatient heart failure (NOT hospitalized — e.g., day-hospital visits, outpatient clinics)
- EXCLUDE: Pediatric patients (<18)
- EXCLUDE: Cardiac surgery patients (post-operative fluid management)
- EXCLUDE: Patients without heart failure

INTERVENTION:
- INCLUDE: Intravenous hypertonic saline at any concentration above 0.9% NaCl (e.g., 1.4%, 3%, 4.6%, 7.5%), administered WITH intravenous loop diuretics
- EXCLUDE: Studies using only isotonic (0.9%) or hypotonic saline
- EXCLUDE: Studies where hypertonic saline is used for hyponatremia correction without a diuretic co-administration context
- EXCLUDE: Studies where BOTH arms receive hypertonic saline (no non-HSS comparator)

COMPARATOR:
- INCLUDE: Any comparator WITHOUT hypertonic saline — loop diuretics alone, loop diuretics + isotonic saline (0.9%), loop diuretics + placebo, standard of care
- EXCLUDE: Single-arm studies (no comparator group)

STUDY DESIGN:
- INCLUDE: Randomized controlled trials (RCTs), including parallel-group, crossover, factorial, cluster-randomized
- EXCLUDE: Observational studies, case reports, case series
- EXCLUDE: Reviews, editorials, commentaries, letters without original data
- EXCLUDE: Conference abstracts without sufficient data for extraction (requires at least: sample size per arm, and one extractable outcome)
- EXCLUDE: Study protocols without results

ADDITIONAL FULL-TEXT EXCLUSION CRITERIA:
- EXCLUDE: Duplicate publication of the same trial data (identify by matching sample size, enrollment period, center, and intervention details with other included studies)
- EXCLUDE: Studies where hypertonic saline is only one component of a multi-component intervention that cannot be isolated (e.g., a bundled diuretic algorithm where HSS is given only to a subset based on response)

OUTCOMES:
- The study must report at least ONE extractable quantitative outcome (mortality, length of stay, readmission, renal function, diuretic response, electrolytes, safety events)

### Output Format

Respond with a single JSON object:

{
  "citation_id": "<provided ID>",
  "decision": "include" or "exclude",
  "confidence": 0.0-1.0,
  "rationale": "Brief explanation",
  "exclusion_reason": null or one of the codes below,
  "pico_assessment": {
    "population_hospitalized_ahf": {"met": true/false/null, "note": "..."},
    "intervention_hss_with_diuretic": {"met": true/false/null, "note": "..."},
    "comparator_no_hss": {"met": true/false/null, "note": "..."},
    "study_design_rct": {"met": true/false/null, "note": "..."},
    "not_duplicate": {"met": true/false/null, "note": "..."},
    "extractable_outcome": {"met": true/false/null, "note": "..."}
  },
  "study_details": {
    "sample_size": null or integer,
    "enrollment_period": "...",
    "center": "...",
    "hss_protocol": "brief description",
    "primary_endpoint": "...",
    "is_ambulatory": true/false,
    "is_crossover": true/false
  }
}

### Exclusion Reason Codes
- population_not_hospitalized — Ambulatory or day-hospital patients only
- population_not_ahf — Not acute/decompensated heart failure
- population_pediatric — Pediatric population
- population_cardiac_surgery — Post-cardiac surgery
- intervention_no_hss — No hypertonic saline intervention
- intervention_both_arms_hss — Both arms receive HSS (no non-HSS comparator)
- intervention_bundled — HSS not isolable within multi-component protocol
- comparator_none — No comparator group
- design_not_rct — Not a randomized controlled trial
- design_review — Review, editorial, or commentary
- design_abstract_insufficient — Conference abstract without sufficient data
- design_protocol — Protocol without results
- duplicate_publication — Same trial data as another included study
- no_extractable_outcome — No quantitative outcomes reported
"""


# ============================================================================
# 2. PDF PROCESSING
# ============================================================================

def extract_text(pdf_path: str, output_dir: str) -> str:
    """Extract text from a PDF using pdftotext."""
    stem = Path(pdf_path).stem
    txt_path = os.path.join(output_dir, f"{stem}.txt")

    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    try:
        subprocess.run(
            ["pdftotext", "-layout", pdf_path, txt_path],
            check=True, capture_output=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "pdftotext not found. Install poppler-utils: "
            "brew install poppler (macOS) or apt-get install poppler-utils (Linux)"
        )

    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ============================================================================
# 3. SCREENING LOGIC
# ============================================================================

def build_user_message(citation_id: str, text: str) -> str:
    """Build user message for full-text screening."""
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[TEXT TRUNCATED AT 120,000 CHARACTERS]"

    return f"Citation ID: {citation_id}\n\n--- FULL TEXT ---\n\n{text}"


def screen_fulltext(
    citation_id: str,
    text: str,
    claude_model: str,
    gpt_model: str,
    delay: float,
) -> dict[str, Any]:
    """Screen one full-text study with both models."""
    user_msg = build_user_message(citation_id, text)
    result = {"citation_id": citation_id}

    # Model A: Claude
    result["model_a"] = _call_model_safe(
        call_fn=call_claude,
        model_name=claude_model,
        label="A (Claude)",
        system_prompt=FULLTEXT_SYSTEM_PROMPT,
        user_message=user_msg,
    )
    time.sleep(delay)

    # Model B: GPT
    result["model_b"] = _call_model_safe(
        call_fn=call_gpt,
        model_name=gpt_model,
        label="B (GPT)",
        system_prompt=FULLTEXT_SYSTEM_PROMPT,
        user_message=user_msg,
    )
    time.sleep(delay)

    return result


# ============================================================================
# 4. MATCH PDFS TO CITATIONS
# ============================================================================

def find_pdfs(pdf_dir: str) -> dict[str, str]:
    """Find all PDFs and map filename stems to paths."""
    pdf_map = {}
    for p in Path(pdf_dir).glob("*.pdf"):
        pdf_map[p.stem] = str(p)
    return pdf_map


def load_included_citations(screening_log_path: str) -> list[dict[str, Any]]:
    """Load citations that passed title/abstract screening (include or human_review→include)."""
    with open(screening_log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    included = []
    for entry in log:
        final = entry.get("resolution", {}).get("final_decision", "")
        if final == "include":
            included.append(entry)
        elif final == "human_review":
            # Human review decisions: check if manually included
            override = entry.get("resolution", {}).get("human_override")
            if override == "include":
                included.append(entry)
    return included


# ============================================================================
# 5. OUTPUT
# ============================================================================

def save_fulltext_results(
    log_entries: list[dict[str, Any]],
    output_dir: str,
) -> None:
    """Save all full-text screening outputs."""
    os.makedirs(output_dir, exist_ok=True)

    # Full log
    log_path = os.path.join(output_dir, "fulltext_screening_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, indent=2, ensure_ascii=False)

    # Summary
    included = [e for e in log_entries
                if e.get("resolution", {}).get("final_decision") == "include"]
    excluded = [e for e in log_entries
                if e.get("resolution", {}).get("final_decision") == "exclude"]
    human_review = [e for e in log_entries
                    if e.get("resolution", {}).get("final_decision") == "human_review"]

    summary = {
        "total_screened": len(log_entries),
        "included": len(included),
        "excluded": len(excluded),
        "human_review": len(human_review),
        "included_ids": [e["citation_id"] for e in included],
        "excluded_ids": [
            {"id": e["citation_id"],
             "reason_a": e.get("model_a", {}).get("exclusion_reason"),
             "reason_b": e.get("model_b", {}).get("exclusion_reason")}
            for e in excluded
        ],
    }
    summary_path = os.path.join(output_dir, "fulltext_screening_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Human review queue
    if human_review:
        queue_path = os.path.join(output_dir, "fulltext_human_review.json")
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(human_review, f, indent=2, ensure_ascii=False)

    print(f"Full-text screening: {len(included)} included, "
          f"{len(excluded)} excluded, {len(human_review)} need human review")


# ============================================================================
# 6. MAIN
# ============================================================================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="DESAL Full-Text Screening (Dual-LLM)",
    )
    parser.add_argument("--pdfs", required=True,
                        help="Directory containing PDFs of included citations.")
    parser.add_argument("--screening-log", required=False, default=None,
                        help="Path to title/abstract screening_log.json (optional).")
    parser.add_argument("--output", default="./fulltext_screening_output/")
    parser.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL)
    parser.add_argument("--gpt-model", default=DEFAULT_GPT_MODEL)
    parser.add_argument("--confidence-threshold", type=float,
                        default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument("--audit-fraction", type=float,
                        default=DEFAULT_AUDIT_FRACTION)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args(argv)


def main():
    args = parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY not set.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY not set.")

    os.makedirs(args.output, exist_ok=True)
    text_dir = os.path.join(args.output, "extracted_text")
    os.makedirs(text_dir, exist_ok=True)

    # Find PDFs
    pdf_map = find_pdfs(args.pdfs)
    if not pdf_map:
        print(f"No PDFs found in {args.pdfs}")
        sys.exit(1)
    print(f"Found {len(pdf_map)} PDFs to screen.")

    # Screen each PDF
    log_entries = []
    for i, (stem, pdf_path) in enumerate(sorted(pdf_map.items())):
        citation_id = stem  # Use filename as citation ID
        print(f"[{i + 1}/{len(pdf_map)}] Screening: {stem}...", end=" ", flush=True)

        try:
            text = extract_text(pdf_path, text_dir)
        except Exception as e:
            print(f"PDF extraction error: {e}")
            log_entries.append({
                "citation_id": citation_id,
                "model_a": _model_error_entry(args.claude_model, f"PDF error: {e}"),
                "model_b": _model_error_entry(args.gpt_model, f"PDF error: {e}"),
                "resolution": {
                    "method": "human_review_model_error",
                    "final_decision": "human_review",
                    "confidence_check_passed": False,
                    "human_reviewer": None,
                    "human_override": None,
                    "audit_selected": False,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
            continue

        result = screen_fulltext(
            citation_id, text,
            args.claude_model, args.gpt_model, args.delay,
        )

        resolution = resolve_decision(
            result["model_a"], result["model_b"],
            args.confidence_threshold,
        )
        result["resolution"] = resolution
        log_entries.append(result)

        dec_a = result["model_a"].get("decision", "error")
        dec_b = result["model_b"].get("decision", "error")
        final = resolution["final_decision"]
        print(f"A:{dec_a.upper()} B:{dec_b.upper()} → {resolution['method']}")

        # Save progress
        save_screening_log(log_entries, args.output)

    # Audit sampling of auto-excludes
    select_audit_sample(log_entries, args.audit_fraction, args.seed)

    # Save outputs
    save_fulltext_results(log_entries, args.output)

    # Metrics
    metrics = compute_metrics(log_entries)
    metrics_path = os.path.join(args.output, "fulltext_screening_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nFull-text screening complete.")
    print(f"Cohen's kappa: {metrics['cohens_kappa']}")
    print(f"Outputs saved to {args.output}")


if __name__ == "__main__":
    main()

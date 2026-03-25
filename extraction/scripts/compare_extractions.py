#!/usr/bin/env python3
"""
DESAL Systematic Review — Disagreement Classifier v1.0

Cell-by-cell comparison of dual-model extractions, classified into
disagreement Levels 0-5 per pipeline specification Section 3.4.

Levels:
    0: Perfect agreement — same value, both verified
    1: Trivial difference — rounding, units, formatting
    2: Minor difference — close values, likely from different locations
    3: Moderate difference — different values, one verified / one not
    4: Major difference — contradictory values, both models confident
    5: Structural disagreement — one found data the other said not reported

Resolution rules:
    Level 0-1: Auto-accept
    Level 2:   Auto-accept if both verified; else flag for human review
    Level 3-5: Route to LLM auditor → human review if auditor confidence < 0.8

Usage:
    python compare_extractions.py extraction/data/extraction_log.json
    python compare_extractions.py --claude extraction/data/claude_extractions.json \
                                  --gpt extraction/data/gpt_extractions.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tolerance for Level 1 (trivial) differences
TRIVIAL_REL_TOL = 0.01   # 1% relative tolerance
TRIVIAL_ABS_TOL = 0.05   # absolute tolerance for small numbers

# Tolerance for Level 2 (minor) differences
MINOR_REL_TOL = 0.10     # 10% relative tolerance
MINOR_ABS_TOL = 1.0      # absolute tolerance

# Fields where exact match is required (no tolerance)
EXACT_MATCH_FIELDS = {
    "study_id", "pmid", "doi", "author", "year", "title", "journal",
    "country", "single_center", "study_design", "registration_number",
    "sample_size_total", "sample_size_intervention", "sample_size_control",
    "palermo_group", "blinding",
    "mortality.events_intervention", "mortality.events_control",
    "mortality.n_intervention", "mortality.n_control",
    "readmission.events_intervention", "readmission.events_control",
    "readmission.n_intervention", "readmission.n_control",
    "hypernatremia.events_intervention", "hypernatremia.events_control",
    "aki.events_intervention", "aki.events_control",
}

# Fields to skip in comparison (metadata, not clinical data)
SKIP_FIELDS = {
    "confidence_notes", "extraction_source",
}


# ============================================================================
# 1. FLATTEN NESTED EXTRACTION
# ============================================================================

def flatten_extraction(extraction: dict[str, Any]) -> dict[str, Any]:
    """Flatten a nested extraction dict into dot-separated field paths.

    Example: {"mortality": {"events_intervention": 15}} → {"mortality.events_intervention": 15}
    """
    flat = {}

    def _walk(obj: Any, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                new_key = f"{prefix}.{key}" if prefix else key
                _walk(val, new_key)
        elif isinstance(obj, list):
            for i, val in enumerate(obj):
                _walk(val, f"{prefix}[{i}]")
        else:
            flat[prefix] = obj

    _walk(extraction)
    return flat


# ============================================================================
# 2. CLASSIFY A SINGLE FIELD
# ============================================================================

def classify_field(
    field: str,
    val_a: Any,
    val_b: Any,
    verified_a: bool = False,
    verified_b: bool = False,
) -> dict[str, Any]:
    """Classify the disagreement level for a single field.

    Returns a dict with: field, val_a, val_b, level, level_name, detail.
    """
    result = {
        "field": field,
        "val_a": val_a,
        "val_b": val_b,
        "verified_a": verified_a,
        "verified_b": verified_b,
    }

    # --- Level 5: Structural disagreement ---
    # One model returned a value, the other returned null/missing
    a_is_null = val_a is None
    b_is_null = val_b is None

    if a_is_null and b_is_null:
        result.update(level=0, level_name="perfect_agreement",
                      detail="Both null (not reported)")
        return result

    if a_is_null != b_is_null:
        result.update(level=5, level_name="structural_disagreement",
                      detail="One model found data, the other did not")
        return result

    # --- Both have values. Compare them. ---

    # String fields
    if isinstance(val_a, str) and isinstance(val_b, str):
        if val_a.strip().lower() == val_b.strip().lower():
            result.update(level=0, level_name="perfect_agreement",
                          detail="Exact string match (case-insensitive)")
        else:
            result.update(level=4, level_name="major_difference",
                          detail=f"String mismatch: '{val_a}' vs '{val_b}'")
        return result

    # Boolean fields
    if isinstance(val_a, bool) and isinstance(val_b, bool):
        if val_a == val_b:
            result.update(level=0, level_name="perfect_agreement",
                          detail="Boolean match")
        else:
            result.update(level=4, level_name="major_difference",
                          detail=f"Boolean mismatch: {val_a} vs {val_b}")
        return result

    # Numeric fields
    if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
        return _classify_numeric(result, field, float(val_a), float(val_b),
                                 verified_a, verified_b)

    # Mixed types
    result.update(level=4, level_name="major_difference",
                  detail=f"Type mismatch: {type(val_a).__name__} vs {type(val_b).__name__}")
    return result


def _classify_numeric(
    result: dict,
    field: str,
    a: float,
    b: float,
    verified_a: bool,
    verified_b: bool,
) -> dict[str, Any]:
    """Classify disagreement for numeric values."""

    # Exact match
    if a == b:
        result.update(level=0, level_name="perfect_agreement",
                      detail="Exact numeric match")
        return result

    # For fields requiring exact match
    if field in EXACT_MATCH_FIELDS:
        result.update(level=4, level_name="major_difference",
                      detail=f"Exact-match field differs: {a} vs {b}")
        return result

    # Compute difference metrics
    abs_diff = abs(a - b)
    max_abs = max(abs(a), abs(b), 1e-10)
    rel_diff = abs_diff / max_abs

    # Level 1: Trivial difference (rounding)
    if rel_diff <= TRIVIAL_REL_TOL or abs_diff <= TRIVIAL_ABS_TOL:
        result.update(level=1, level_name="trivial_difference",
                      detail=f"Rounding: {a} vs {b} (rel diff {rel_diff:.4f})")
        return result

    # Level 2: Minor difference
    if rel_diff <= MINOR_REL_TOL or abs_diff <= MINOR_ABS_TOL:
        if verified_a and verified_b:
            result.update(
                level=2, level_name="minor_difference",
                detail=f"Minor diff, both verified: {a} vs {b} (rel diff {rel_diff:.4f})",
            )
        else:
            result.update(
                level=2, level_name="minor_difference",
                detail=f"Minor diff, verification incomplete: {a} vs {b}",
            )
        return result

    # Level 3: Moderate difference
    if verified_a != verified_b:
        result.update(
            level=3, level_name="moderate_difference",
            detail=f"Different values, asymmetric verification: {a} vs {b}",
        )
        return result

    # Level 4: Major difference
    result.update(level=4, level_name="major_difference",
                  detail=f"Contradictory values: {a} vs {b} (rel diff {rel_diff:.4f})")
    return result


# ============================================================================
# 3. COMPARE TWO FULL EXTRACTIONS
# ============================================================================

def compare_extractions(
    extraction_a: dict[str, Any],
    extraction_b: dict[str, Any],
    verification_a: Optional[dict] = None,
    verification_b: Optional[dict] = None,
) -> dict[str, Any]:
    """Compare two model extractions cell-by-cell.

    Returns a comparison report with per-field classifications and summary.
    """
    flat_a = flatten_extraction(extraction_a)
    flat_b = flatten_extraction(extraction_b)

    # Build verification lookup
    verified_fields_a = set()
    verified_fields_b = set()
    if verification_a:
        verified_fields_a = set(verification_a.get("verified_fields", []))
    if verification_b:
        verified_fields_b = set(verification_b.get("verified_fields", []))

    # All fields from both models
    all_fields = sorted(set(flat_a.keys()) | set(flat_b.keys()))

    comparisons = []
    level_counts = {i: 0 for i in range(6)}

    for field in all_fields:
        if any(field.startswith(skip) or field.endswith(skip)
               for skip in SKIP_FIELDS):
            continue

        val_a = flat_a.get(field)
        val_b = flat_b.get(field)
        v_a = field in verified_fields_a
        v_b = field in verified_fields_b

        classification = classify_field(field, val_a, val_b, v_a, v_b)
        comparisons.append(classification)
        level_counts[classification["level"]] += 1

    # Determine which fields need human review
    auto_accept = [c for c in comparisons if c["level"] <= 1]
    auto_accept_if_verified = [c for c in comparisons
                               if c["level"] == 2 and c["verified_a"] and c["verified_b"]]
    needs_auditor = [c for c in comparisons if c["level"] >= 3]
    needs_auditor += [c for c in comparisons
                      if c["level"] == 2 and not (c["verified_a"] and c["verified_b"])]

    return {
        "study_id": extraction_a.get("study_id", "unknown"),
        "n_fields_compared": len(comparisons),
        "level_counts": level_counts,
        "auto_accepted": len(auto_accept) + len(auto_accept_if_verified),
        "needs_auditor": len(needs_auditor),
        "comparisons": comparisons,
        "fields_for_auditor": [c["field"] for c in needs_auditor],
    }


# ============================================================================
# 4. BUILD RECOMMENDED EXTRACTION
# ============================================================================

def build_recommended(
    extraction_a: dict[str, Any],
    extraction_b: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    """Build a recommended extraction from auto-accepted fields.

    For Level 0: use either value (they agree).
    For Level 1: use the more precise value (more decimal places or non-rounded).
    For Level 2+ auto-accepted (both verified): use Model A by default.
    For Level 2+ needing auditor: leave as null with a flag.
    """
    flat_a = flatten_extraction(extraction_a)
    flat_b = flatten_extraction(extraction_b)
    recommended = {}

    for comp in comparison["comparisons"]:
        field = comp["field"]
        level = comp["level"]
        val_a = comp["val_a"]
        val_b = comp["val_b"]

        if level == 0:
            # Perfect agreement — use whichever is non-null
            recommended[field] = val_a if val_a is not None else val_b
        elif level == 1:
            # Trivial — use more precise
            recommended[field] = _more_precise(val_a, val_b)
        elif level == 2 and comp.get("verified_a") and comp.get("verified_b"):
            # Both verified minor diff — default to Model A
            recommended[field] = val_a
        else:
            # Needs auditor or human review
            recommended[field] = None  # placeholder

    return recommended


def _more_precise(a: Any, b: Any) -> Any:
    """Return the more precise of two numeric values."""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a
    str_a = str(a).rstrip("0").rstrip(".")
    str_b = str(b).rstrip("0").rstrip(".")
    if len(str_a) >= len(str_b):
        return a
    return b


# ============================================================================
# 5. BATCH COMPARISON
# ============================================================================

def compare_all_studies(extraction_log_path: str) -> dict[str, Any]:
    """Run comparison on all studies in an extraction log.

    Returns a batch report with per-study comparisons and aggregate stats.
    """
    with open(extraction_log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    studies = log.get("studies", [])
    results = []

    for study in studies:
        label = study.get("study_label", "unknown")
        model_a = study.get("model_a", {})
        model_b = study.get("model_b", {})

        if not model_a.get("extraction") or not model_b.get("extraction"):
            print(f"  Skipping {label}: missing extraction from one or both models.")
            continue

        print(f"  Comparing: {label}")
        comparison = compare_extractions(
            model_a["extraction"],
            model_b["extraction"],
            model_a.get("verification"),
            model_b.get("verification"),
        )
        comparison["study_label"] = label
        results.append(comparison)

    # Aggregate statistics
    total_fields = sum(r["n_fields_compared"] for r in results)
    total_auto = sum(r["auto_accepted"] for r in results)
    total_auditor = sum(r["needs_auditor"] for r in results)

    agg_levels = {i: 0 for i in range(6)}
    for r in results:
        for level, count in r["level_counts"].items():
            agg_levels[int(level)] += count

    batch_report = {
        "n_studies": len(results),
        "total_fields_compared": total_fields,
        "total_auto_accepted": total_auto,
        "total_needs_auditor": total_auditor,
        "auto_accept_rate": total_auto / total_fields if total_fields else 0,
        "aggregate_level_counts": agg_levels,
        "studies": results,
    }

    return batch_report


# ============================================================================
# 6. OUTPUT
# ============================================================================

def save_comparison_report(report: dict[str, Any], output_dir: str) -> str:
    """Save full comparison report."""
    path = os.path.join(output_dir, "disagreements.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Comparison report saved to {path}")
    return path


def save_auditor_queue(report: dict[str, Any], output_dir: str) -> str:
    """Save fields needing LLM auditor review as a structured queue."""
    queue = []
    for study in report["studies"]:
        for comp in study["comparisons"]:
            if comp["level"] >= 2 and comp["field"] in study.get("fields_for_auditor", []):
                queue.append({
                    "study_label": study.get("study_label", ""),
                    "study_id": study.get("study_id", ""),
                    "field": comp["field"],
                    "level": comp["level"],
                    "level_name": comp["level_name"],
                    "val_a": comp["val_a"],
                    "val_b": comp["val_b"],
                    "verified_a": comp.get("verified_a", False),
                    "verified_b": comp.get("verified_b", False),
                    "detail": comp["detail"],
                })

    path = os.path.join(output_dir, "auditor_queue.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
    print(f"Auditor queue saved to {path} ({len(queue)} fields)")
    return path


# ============================================================================
# 7. MAIN
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DESAL Disagreement Classifier — compare dual-model extractions",
    )
    parser.add_argument(
        "extraction_log",
        help="Path to extraction_log.json from the orchestrator.",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory (default: same as extraction log).",
    )
    args = parser.parse_args()

    output_dir = args.output or str(Path(args.extraction_log).parent)
    os.makedirs(output_dir, exist_ok=True)

    print("Running disagreement classifier...")
    report = compare_all_studies(args.extraction_log)

    save_comparison_report(report, output_dir)
    save_auditor_queue(report, output_dir)

    print(f"\nSummary:")
    print(f"  Studies compared: {report['n_studies']}")
    print(f"  Total fields: {report['total_fields_compared']}")
    print(f"  Auto-accepted: {report['total_auto_accepted']} "
          f"({report['auto_accept_rate']:.1%})")
    print(f"  Needs auditor: {report['total_needs_auditor']}")
    print(f"  Level distribution: {report['aggregate_level_counts']}")


if __name__ == "__main__":
    main()

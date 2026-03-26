#!/usr/bin/env python3
"""
DESAL Systematic Review — LLM Auditor Layer v1.0

Third LLM call to triage Level 2-5 disagreements between dual-model
extractions, per pipeline specification Section 3.5.

The auditor receives:
  - Original source text and extracted tables
  - Both models' values for the disputed field(s)
  - Verification results from clinical-data-extractor skill
  - Disagreement classification level

The auditor outputs a recommendation with confidence. If confidence < 0.80,
the field is routed to human review.

Usage:
    python llm_auditor.py \
        --queue extraction/data/auditor_queue.json \
        --extraction-log extraction/data/extraction_log.json \
        --output extraction/data/
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_AUDITOR_MODEL = "claude-opus-4-6"
AUDITOR_CONFIDENCE_THRESHOLD = 0.80
MAX_RETRIES = 3
BACKOFF_BASE = 2.0
DEFAULT_DELAY = 0.5

# Alternate models to avoid self-bias: if the original extraction was by
# Claude, use GPT for auditing, and vice versa.
ALTERNATE_MODELS = {
    "claude": "gpt-5.4",
    "gpt": "claude-opus-4-6",
}


# ============================================================================
# 1. AUDITOR PROMPT
# ============================================================================

AUDITOR_SYSTEM_PROMPT = """You are a clinical data auditor for a systematic review of hypertonic saline in acute decompensated heart failure.

Two independent extraction models disagreed on a specific data field. You are given:
1. The original source text from the paper
2. Relevant tables extracted from the paper (if available)
3. Both models' extracted values for the disputed field
4. The disagreement level and details
5. Verification results (which values were found in the source text)

Your task: determine the correct value by carefully reading the source text and tables.

## Rules
1. Base your judgment ONLY on the source text and tables provided.
2. If the correct value is clear from the source, recommend it with high confidence.
3. If the source is genuinely ambiguous (e.g., different values in abstract vs. table), explain the ambiguity and recommend human review.
4. If neither model's value can be verified in the source, recommend null and flag for human review.
5. For event counts (mortality, readmission), exact numbers are required — do not round.
6. For continuous outcomes, report the value as stated in the paper.

## Output Format
Respond with a single JSON object:

{
  "field": "<field name>",
  "model_a_value": <value from Model A>,
  "model_b_value": <value from Model B>,
  "recommended_value": <your recommended value, or null if unclear>,
  "recommendation_source": "<where in the paper you found this, e.g., 'Table 2, row 3'>",
  "confidence": <0.0-1.0>,
  "rationale": "<brief explanation of your reasoning>",
  "human_review_needed": <true if confidence < 0.80 or source is ambiguous>
}

JSON only, no markdown fences or commentary."""


def build_auditor_user_message(
    field: str,
    val_a: Any,
    val_b: Any,
    level: int,
    level_name: str,
    detail: str,
    source_text: str,
    tables_json: str,
    verification_context: str,
) -> str:
    """Build the user message for a single field audit."""

    # Truncate source text for context window
    max_text = 60_000
    if len(source_text) > max_text:
        source_text = source_text[:max_text] + "\n[TRUNCATED]"

    return f"""## Disputed Field
Field: {field}
Model A value: {json.dumps(val_a)}
Model B value: {json.dumps(val_b)}
Disagreement level: {level} ({level_name})
Detail: {detail}

## Verification Context
{verification_context}

## Extracted Tables
{tables_json[:20000] if tables_json else "(No tables available)"}

## Source Text
{source_text}"""


# ============================================================================
# 2. LLM CALLS (ALTERNATING MODEL)
# ============================================================================

def select_auditor_model(study_result: dict[str, Any]) -> str:
    """Select auditor model to avoid self-bias.

    If both original models were used, alternate based on study index.
    For simplicity: use GPT to audit fields where models disagreed,
    since disagreements mean neither model is obviously right.
    """
    # Default: use the alternate of Model A
    model_a_name = study_result.get("model_a", {}).get("model_name", "")
    if "claude" in model_a_name.lower():
        return ALTERNATE_MODELS["claude"]
    return ALTERNATE_MODELS["gpt"]


def call_auditor(
    system_prompt: str,
    user_message: str,
    model: str,
) -> dict[str, Any]:
    """Call the auditor model and parse response."""

    if "claude" in model.lower():
        return _call_claude_auditor(system_prompt, user_message, model)
    else:
        return _call_gpt_auditor(system_prompt, user_message, model)


def _call_claude_auditor(
    system_prompt: str,
    user_message: str,
    model: str,
) -> dict[str, Any]:
    import anthropic
    client = anthropic.Anthropic()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text.strip()
            return _parse_auditor_response(text)
        except (anthropic.APIConnectionError, anthropic.RateLimitError,
                anthropic.APIStatusError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE ** (attempt + 1))
            else:
                raise


def _call_gpt_auditor(
    system_prompt: str,
    user_message: str,
    model: str,
) -> dict[str, Any]:
    import openai
    client = openai.OpenAI()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            text = response.choices[0].message.content.strip()
            return _parse_auditor_response(text)
        except (openai.APIConnectionError, openai.RateLimitError,
                openai.APIStatusError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE ** (attempt + 1))
            else:
                raise


def _parse_auditor_response(text: str) -> dict[str, Any]:
    """Parse JSON from auditor response."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    parsed = json.loads(cleaned)

    # Enforce human_review_needed based on confidence
    conf = float(parsed.get("confidence", 0))
    if conf < AUDITOR_CONFIDENCE_THRESHOLD:
        parsed["human_review_needed"] = True

    return parsed


# ============================================================================
# 3. LOAD SOURCE DATA
# ============================================================================

def load_source_text(study_result: dict[str, Any]) -> str:
    """Load the extracted text for a study."""
    txt_path = study_result.get("text_path", "")
    if txt_path and os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return "(Source text not available)"


def load_tables_json(study_result: dict[str, Any]) -> str:
    """Load the extracted tables JSON for a study."""
    tables_path = study_result.get("tables_path", "")
    if tables_path and os.path.exists(tables_path):
        with open(tables_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def build_verification_context(
    field: str,
    study_result: dict[str, Any],
) -> str:
    """Build verification context string for a field."""
    lines = []
    for model_key, label in [("model_a", "Model A"), ("model_b", "Model B")]:
        verification = study_result.get(model_key, {}).get("verification")
        if not verification:
            lines.append(f"{label}: No verification data available")
            continue

        verified = set(verification.get("verified_fields", []))
        unverified = set(verification.get("unverified_fields", []))
        flagged = set(verification.get("flagged_fields", []))

        if field in verified:
            lines.append(f"{label}: VERIFIED in source text")
        elif field in flagged:
            lines.append(f"{label}: FLAGGED — value found in suspicious context")
        elif field in unverified:
            lines.append(f"{label}: UNVERIFIED — value not found in source text")
        else:
            lines.append(f"{label}: Not checked by verification layers")

    return "\n".join(lines)


# ============================================================================
# 4. AUDIT PIPELINE
# ============================================================================

def audit_study(
    study_result: dict[str, Any],
    queue_items: list[dict[str, Any]],
    delay: float = DEFAULT_DELAY,
) -> list[dict[str, Any]]:
    """Audit all disputed fields for one study.

    Returns a list of auditor decisions.
    """
    if not queue_items:
        return []

    source_text = load_source_text(study_result)
    tables_json = load_tables_json(study_result)
    auditor_model = select_auditor_model(study_result)

    decisions = []
    for item in queue_items:
        field = item["field"]
        verification_context = build_verification_context(field, study_result)

        user_msg = build_auditor_user_message(
            field=field,
            val_a=item["val_a"],
            val_b=item["val_b"],
            level=item["level"],
            level_name=item["level_name"],
            detail=item["detail"],
            source_text=source_text,
            tables_json=tables_json,
            verification_context=verification_context,
        )

        try:
            decision = call_auditor(AUDITOR_SYSTEM_PROMPT, user_msg, auditor_model)
            decision["auditor_model"] = auditor_model
            decision["study_label"] = item.get("study_label", "")
            decision["disagreement_level"] = item["level"]
        except Exception as e:
            decision = {
                "field": field,
                "study_label": item.get("study_label", ""),
                "model_a_value": item["val_a"],
                "model_b_value": item["val_b"],
                "recommended_value": None,
                "recommendation_source": None,
                "confidence": 0.0,
                "rationale": f"Auditor error: {e}",
                "human_review_needed": True,
                "auditor_model": auditor_model,
                "disagreement_level": item["level"],
            }

        decisions.append(decision)
        time.sleep(delay)

    return decisions


def run_full_audit(
    queue_path: str,
    extraction_log_path: str,
    output_dir: str,
    delay: float = DEFAULT_DELAY,
) -> dict[str, Any]:
    """Run the auditor on all items in the queue."""

    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)

    with open(extraction_log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    # Index studies by label
    studies_by_label = {
        s["study_label"]: s for s in log.get("studies", [])
    }

    # Group queue items by study
    by_study: dict[str, list] = {}
    for item in queue:
        label = item.get("study_label", "unknown")
        by_study.setdefault(label, []).append(item)

    all_decisions = []
    for label, items in by_study.items():
        study_result = studies_by_label.get(label)
        if not study_result:
            print(f"  Warning: No extraction data for {label}, skipping.")
            continue

        print(f"  Auditing {label}: {len(items)} fields...")
        decisions = audit_study(study_result, items, delay)
        all_decisions.extend(decisions)

    # Summary
    auto_resolved = [d for d in all_decisions if not d.get("human_review_needed")]
    needs_human = [d for d in all_decisions if d.get("human_review_needed")]

    report = {
        "audit_date": datetime.now(timezone.utc).isoformat(),
        "total_fields_audited": len(all_decisions),
        "auto_resolved_by_auditor": len(auto_resolved),
        "needs_human_review": len(needs_human),
        "auto_resolve_rate": len(auto_resolved) / len(all_decisions) if all_decisions else 0,
        "decisions": all_decisions,
        "human_review_queue": needs_human,
    }

    return report


# ============================================================================
# 5. OUTPUT
# ============================================================================

def save_audit_report(report: dict[str, Any], output_dir: str) -> str:
    path = os.path.join(output_dir, "auditor_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Auditor report saved to {path}")
    return path


def save_human_review_queue(report: dict[str, Any], output_dir: str) -> str:
    """Save only the items needing human review as a separate file."""
    queue = report.get("human_review_queue", [])
    path = os.path.join(output_dir, "human_review_extraction.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
    print(f"Human review queue saved to {path} ({len(queue)} fields)")
    return path


def save_final_extractions(
    report: dict[str, Any],
    extraction_log_path: str,
    output_dir: str,
    disagreements_path: Optional[str] = None,
) -> str:
    """Build final extractions incorporating classifier and auditor decisions.

    Resolution order:
    1. Level 0-1 auto-accepted fields: use agreed/more-precise value
    2. Level 2 auto-accepted (both verified): use Model A value
    3. Auditor-resolved fields (confidence >= 0.80): use auditor recommendation
    4. Remaining fields: flag for human review

    Without disagreements_path, falls back to Model A base + auditor overrides.
    """
    with open(extraction_log_path, "r", encoding="utf-8") as f:
        log = json.load(f)

    # Load classifier results if available
    classifier_results = {}
    if disagreements_path is None:
        disagreements_path = os.path.join(
            os.path.dirname(extraction_log_path), "disagreements.json"
        )
    if os.path.exists(disagreements_path):
        with open(disagreements_path, "r", encoding="utf-8") as f:
            disagreements = json.load(f)
        for study_report in disagreements.get("studies", []):
            label = study_report.get("study_label", "")
            classifier_results[label] = study_report

    # Index auditor decisions by (study_label, field)
    auditor_lookup = {}
    for d in report.get("decisions", []):
        key = (d.get("study_label", ""), d.get("field", ""))
        auditor_lookup[key] = d

    final_studies = []
    for study in log.get("studies", []):
        label = study.get("study_label", "")
        # Start from Model A extraction as base
        base = study.get("model_a", {}).get("extraction")
        if not base:
            base = study.get("model_b", {}).get("extraction")
        if not base:
            continue

        base = copy.deepcopy(base)

        # Step 1: Apply classifier auto-accepted values (Level 0-2)
        study_comparisons = classifier_results.get(label, {}).get("comparisons", [])
        model_b_extraction = study.get("model_b", {}).get("extraction", {})
        for comp in study_comparisons:
            field = comp["field"]
            level = comp["level"]
            val_a = comp["val_a"]
            val_b = comp["val_b"]

            if level == 0:
                # Perfect agreement — keep base (Model A) value
                pass
            elif level == 1:
                # Trivial difference — use more precise value
                if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                    str_a = str(val_a).rstrip("0").rstrip(".")
                    str_b = str(val_b).rstrip("0").rstrip(".")
                    if len(str_b) > len(str_a):
                        _set_nested(base, field, val_b)
            elif level == 2 and comp.get("verified_a") and comp.get("verified_b"):
                # Both verified minor diff — keep Model A (default)
                pass

        # Step 2: Apply auditor overrides (Level 2 unverified + Level 3-5)
        pending_human = []
        for key, decision in auditor_lookup.items():
            if key[0] != label:
                continue
            field = key[1]
            if not decision.get("human_review_needed"):
                # Auto-resolved: apply recommended value
                _set_nested(base, field, decision.get("recommended_value"))
            else:
                pending_human.append(field)

        final_studies.append({
            "study_label": label,
            "study_id": base.get("study_id", ""),
            "extraction": base,
            "pending_human_review": pending_human,
        })

    path = os.path.join(output_dir, "final_extractions.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(final_studies, f, indent=2, ensure_ascii=False)
    print(f"Final extractions saved to {path}")
    return path


def _set_nested(obj: dict, dotpath: str, value: Any) -> None:
    """Set a value in a nested dict using a dot-separated path."""
    parts = dotpath.split(".")
    for part in parts[:-1]:
        if part not in obj or not isinstance(obj.get(part), dict):
            obj[part] = {}
        obj = obj[part]
    obj[parts[-1]] = value


# ============================================================================
# 6. MAIN
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DESAL LLM Auditor — triage extraction disagreements",
    )
    parser.add_argument(
        "--queue", required=True,
        help="Path to auditor_queue.json from the disagreement classifier.",
    )
    parser.add_argument(
        "--extraction-log", required=True,
        help="Path to extraction_log.json from the orchestrator.",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output directory (default: same as queue file).",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help="Seconds between API calls.",
    )
    args = parser.parse_args()

    output_dir = args.output or str(Path(args.queue).parent)
    os.makedirs(output_dir, exist_ok=True)

    # Validate environment
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        print("Warning: No API keys set. At least one of ANTHROPIC_API_KEY "
              "or OPENAI_API_KEY is required.", file=sys.stderr)

    print("Running LLM auditor...")
    report = run_full_audit(
        queue_path=args.queue,
        extraction_log_path=args.extraction_log,
        output_dir=output_dir,
        delay=args.delay,
    )

    save_audit_report(report, output_dir)
    save_human_review_queue(report, output_dir)
    save_final_extractions(report, args.extraction_log, output_dir)

    print(f"\nAudit Summary:")
    print(f"  Fields audited: {report['total_fields_audited']}")
    print(f"  Auto-resolved: {report['auto_resolved_by_auditor']} "
          f"({report['auto_resolve_rate']:.1%})")
    print(f"  Needs human review: {report['needs_human_review']}")


if __name__ == "__main__":
    main()

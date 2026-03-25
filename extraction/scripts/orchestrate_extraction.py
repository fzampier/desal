#!/usr/bin/env python3
"""
DESAL Systematic Review — Dual-LLM Extraction Orchestrator v1.0

Extracts structured data from included RCTs using two independent LLMs
(Claude + GPT-5.4), runs clinical-data-extractor verification layers,
then feeds outputs into the disagreement classifier and LLM auditor.

Usage:
    python orchestrate_extraction.py --pdfs extraction/pdfs/ --output extraction/data/
    python orchestrate_extraction.py --pdfs extraction/pdfs/ --resume

Environment variables required:
    ANTHROPIC_API_KEY
    OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CLAUDE_MODEL = "claude-opus-4-6"
DEFAULT_GPT_MODEL = "gpt-5.4"
DEFAULT_DELAY = 1.0
MAX_RETRIES = 3
BACKOFF_BASE = 2.0

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
SCHEMA_DIR = PROJECT_ROOT / "extraction" / "schema"
SKILL_SCRIPTS = PROJECT_ROOT / "clinical-data-extractor" / "scripts"


# ============================================================================
# 1. PDF PROCESSING
# ============================================================================

def extract_text_from_pdf(pdf_path: str, output_dir: str) -> str:
    """Convert PDF to plain text using pdftotext.

    Returns path to the generated .txt file.
    """
    pdf_name = Path(pdf_path).stem
    txt_path = os.path.join(output_dir, f"{pdf_name}.txt")

    if os.path.exists(txt_path):
        return txt_path

    try:
        subprocess.run(
            ["pdftotext", "-layout", pdf_path, txt_path],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "pdftotext not found. Install poppler-utils: "
            "brew install poppler (macOS) or apt-get install poppler-utils (Linux)"
        )
    return txt_path


def extract_tables_from_pdf(pdf_path: str, output_dir: str) -> str:
    """Extract tables from PDF using clinical-data-extractor's extract_tables.py.

    Returns path to the generated tables JSON file.
    """
    pdf_name = Path(pdf_path).stem
    tables_path = os.path.join(output_dir, f"{pdf_name}_tables.json")

    if os.path.exists(tables_path):
        return tables_path

    extract_script = SKILL_SCRIPTS / "extract_tables.py"
    if not extract_script.exists():
        print(f"  Warning: {extract_script} not found. Skipping table extraction.")
        # Write empty tables file so downstream doesn't break
        with open(tables_path, "w") as f:
            json.dump([], f)
        return tables_path

    try:
        subprocess.run(
            [sys.executable, str(extract_script), pdf_path, tables_path],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  Warning: Table extraction failed: {e.stderr.decode()[:200]}")
        with open(tables_path, "w") as f:
            json.dump([], f)

    return tables_path


# ============================================================================
# 2. SCHEMA AND PROMPT LOADING
# ============================================================================

def load_extraction_schema() -> dict:
    """Load the JSON schema for StudyExtraction."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from extraction.schema.study_extraction import export_json_schema
    return export_json_schema()


def build_extraction_system_prompt(schema: dict) -> str:
    """Build the system prompt for data extraction."""
    schema_json = json.dumps(schema, indent=2)
    return f"""You are a clinical data extraction assistant for a systematic review of hypertonic saline in acute decompensated heart failure.

You will be given the full text of a randomized controlled trial. Your task is to extract all relevant data into a structured JSON object matching the schema below.

## Extraction Rules

1. Extract data ONLY from the text provided. Do not use external knowledge.
2. If a value is not reported, use null (not zero, not "not reported").
3. For numerical values, extract the exact number from the paper. Do not calculate or derive values unless explicitly stated (e.g., if the paper gives a percentage, extract it; if only counts are given, extract counts).
4. For outcomes reported as median (IQR), set measure_type to "median_iqr" and fill iqr_low/iqr_high fields. For mean (SD), use "mean_sd" and fill sd fields.
5. If the study is from the Paterna/Tuttolomondo/Parrinello group (University of Palermo, Italy), set palermo_group to true.
6. For Risk of Bias assessment, evaluate each domain carefully based on the methods described in the paper. Use the RoB 2.0 criteria.
7. study_id format: FirstAuthor_Year (e.g., "Paterna_2000")
8. Include confidence_notes for any fields where the extraction is uncertain or the paper is ambiguous.

## Output Format

Respond with a single JSON object conforming to this schema. No markdown fences, no commentary — JSON only.

## Schema

{schema_json}"""


def build_extraction_user_message(
    study_text: str,
    study_label: str,
) -> str:
    """Build the user message for extraction of one study."""
    # Truncate very long texts to fit context windows
    max_chars = 120_000  # ~30k tokens
    if len(study_text) > max_chars:
        study_text = study_text[:max_chars] + "\n\n[TEXT TRUNCATED]"

    return (
        f"Study: {study_label}\n\n"
        f"--- FULL TEXT ---\n\n{study_text}"
    )


# ============================================================================
# 3. LLM API CALLS
# ============================================================================

def call_claude_extract(
    system_prompt: str,
    user_message: str,
    model: str,
) -> dict[str, Any]:
    """Extract data using Claude (Anthropic API)."""
    import anthropic

    client = anthropic.Anthropic()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text.strip()
            return _parse_extraction_response(text)

        except (anthropic.APIConnectionError, anthropic.RateLimitError,
                anthropic.APIStatusError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                print(f"    Claude API error (attempt {attempt + 1}): {e}. "
                      f"Retrying in {wait:.0f}s...")
                time.sleep(wait)
            else:
                raise


def call_gpt_extract(
    system_prompt: str,
    user_message: str,
    model: str,
) -> dict[str, Any]:
    """Extract data using GPT (OpenAI API)."""
    import openai

    client = openai.OpenAI()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            text = response.choices[0].message.content.strip()
            return _parse_extraction_response(text)

        except (openai.APIConnectionError, openai.RateLimitError,
                openai.APIStatusError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                print(f"    GPT API error (attempt {attempt + 1}): {e}. "
                      f"Retrying in {wait:.0f}s...")
                time.sleep(wait)
            else:
                raise


def _parse_extraction_response(text: str) -> dict[str, Any]:
    """Parse JSON from model response, handling markdown fences."""
    import re
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    return json.loads(cleaned)


# ============================================================================
# 4. VERIFICATION (CLINICAL-DATA-EXTRACTOR SKILL)
# ============================================================================

def run_verification_layers(
    extraction: dict[str, Any],
    source_text_path: str,
    tables_json_path: str,
) -> dict[str, Any]:
    """Run Layers 1-3 of clinical-data-extractor on an extraction.

    Returns a verification report dict with per-field results.
    """
    report = {
        "layer1_anchor": None,
        "layer2_text": None,
        "layer3_tables": None,
        "verified_fields": [],
        "unverified_fields": [],
        "flagged_fields": [],
    }

    # Build claims from extraction for verification
    claims = _extraction_to_claims(extraction)
    if not claims:
        return report

    claims_path = tables_json_path.replace("_tables.json", "_claims.json")
    with open(claims_path, "w", encoding="utf-8") as f:
        json.dump(claims, f, indent=2)

    # Layer 2: Text verification
    verify_script = SKILL_SCRIPTS / "verify_numbers.py"
    if verify_script.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(verify_script), source_text_path, claims_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                report["layer2_text"] = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            print(f"    Layer 2 warning: {e}")

    # Layer 3: Table verification
    table_verify_script = SKILL_SCRIPTS / "verify_with_tables.py"
    if table_verify_script.exists() and os.path.exists(tables_json_path):
        try:
            result = subprocess.run(
                [sys.executable, str(table_verify_script),
                 tables_json_path, claims_path, source_text_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                report["layer3_tables"] = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            print(f"    Layer 3 warning: {e}")

    # Summarize verification status
    _summarize_verification(report, claims)
    return report


def _extraction_to_claims(extraction: dict[str, Any]) -> list[dict]:
    """Convert extraction dict to claims format for verification scripts.

    Pulls numerical values from the extraction and creates claim objects
    with the field path and the number to verify.
    """
    claims = []

    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                _walk(val, f"{path}.{key}" if path else key)
        elif isinstance(obj, list):
            for i, val in enumerate(obj):
                _walk(val, f"{path}[{i}]")
        elif isinstance(obj, (int, float)) and obj != 0:
            claims.append({
                "field": path,
                "numbers": [str(obj)],
                "category": _categorize_field(path),
            })

    _walk(extraction)
    return claims


def _categorize_field(path: str) -> str:
    """Map a field path to a claim category."""
    if "mortality" in path:
        return "outcome"
    if "los" in path:
        return "outcome"
    if "readmission" in path:
        return "outcome"
    if "sample_size" in path or "n_" in path or ".n" in path:
        return "enrollment"
    if "baseline" in path or "mean_age" in path:
        return "baseline"
    if "hss_" in path or "diuretic" in path:
        return "intervention"
    return "other"


def _summarize_verification(
    report: dict[str, Any],
    claims: list[dict],
) -> None:
    """Populate verified/unverified/flagged lists in the report."""
    text_results = report.get("layer2_text") or {}
    table_results = report.get("layer3_tables") or {}

    for claim in claims:
        field = claim["field"]
        # Check if verified by either layer
        text_status = _get_claim_status(text_results, claim)
        table_status = _get_claim_status(table_results, claim)

        if text_status == "VERIFIED" or table_status == "TABLE_VERIFIED":
            report["verified_fields"].append(field)
        elif text_status == "CITATION_ONLY" or table_status == "CONTEXT_MISMATCH":
            report["flagged_fields"].append(field)
        elif text_status == "UNVERIFIED" and table_status != "TABLE_VERIFIED":
            report["unverified_fields"].append(field)


def _get_claim_status(results: Any, claim: dict) -> str:
    """Extract verification status for a claim from layer results."""
    if not results:
        return "UNKNOWN"
    if isinstance(results, dict):
        return results.get("overall_status", "UNKNOWN")
    if isinstance(results, list):
        for r in results:
            if r.get("field") == claim.get("field"):
                return r.get("overall_status", "UNKNOWN")
    return "UNKNOWN"


# ============================================================================
# 5. EXTRACTION PIPELINE FOR ONE STUDY
# ============================================================================

def extract_single_study(
    pdf_path: str,
    text_dir: str,
    tables_dir: str,
    system_prompt: str,
    claude_model: str,
    gpt_model: str,
    delay: float,
) -> dict[str, Any]:
    """Run the full extraction pipeline for one study.

    Steps:
        1. PDF → text + tables
        2. Model A (Claude) extracts
        3. Verify Model A with skill layers
        4. Model B (GPT) extracts
        5. Verify Model B with skill layers

    Returns a result dict with both extractions and verification reports.
    """
    study_label = Path(pdf_path).stem
    result = {"study_label": study_label, "pdf_path": pdf_path}

    # Step 1: PDF processing
    print(f"  [1/5] Extracting text and tables...")
    txt_path = extract_text_from_pdf(pdf_path, text_dir)
    tables_path = extract_tables_from_pdf(pdf_path, tables_dir)
    result["text_path"] = txt_path
    result["tables_path"] = tables_path

    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
        study_text = f.read()

    user_msg = build_extraction_user_message(study_text, study_label)

    # Step 2: Model A (Claude) extraction
    print(f"  [2/5] Extracting with Claude ({claude_model})...")
    try:
        claude_extraction = call_claude_extract(system_prompt, user_msg, claude_model)
        result["model_a"] = {
            "model_name": claude_model,
            "extraction": claude_extraction,
            "error": None,
        }
    except Exception as e:
        print(f"    Claude extraction failed: {e}")
        result["model_a"] = {
            "model_name": claude_model,
            "extraction": None,
            "error": str(e),
        }

    time.sleep(delay)

    # Step 3: Verify Model A
    print(f"  [3/5] Verifying Claude extraction...")
    if result["model_a"]["extraction"]:
        result["model_a"]["verification"] = run_verification_layers(
            result["model_a"]["extraction"], txt_path, tables_path,
        )
    else:
        result["model_a"]["verification"] = None

    # Step 4: Model B (GPT) extraction
    print(f"  [4/5] Extracting with GPT ({gpt_model})...")
    try:
        gpt_extraction = call_gpt_extract(system_prompt, user_msg, gpt_model)
        result["model_b"] = {
            "model_name": gpt_model,
            "extraction": gpt_extraction,
            "error": None,
        }
    except Exception as e:
        print(f"    GPT extraction failed: {e}")
        result["model_b"] = {
            "model_name": gpt_model,
            "extraction": None,
            "error": str(e),
        }

    time.sleep(delay)

    # Step 5: Verify Model B
    print(f"  [5/5] Verifying GPT extraction...")
    if result["model_b"]["extraction"]:
        result["model_b"]["verification"] = run_verification_layers(
            result["model_b"]["extraction"], txt_path, tables_path,
        )
    else:
        result["model_b"]["verification"] = None

    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ============================================================================
# 6. BATCH ORCHESTRATION
# ============================================================================

def find_pdfs(pdf_dir: str) -> list[str]:
    """Find all PDF files in the given directory."""
    pdf_dir_path = Path(pdf_dir)
    if not pdf_dir_path.exists():
        raise FileNotFoundError(f"PDF directory not found: {pdf_dir}")
    pdfs = sorted(pdf_dir_path.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {pdf_dir}")
    return [str(p) for p in pdfs]


def load_existing_extractions(output_dir: str) -> dict[str, Any]:
    """Load existing extraction results for resume support."""
    path = os.path.join(output_dir, "extraction_log.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        log = json.load(f)
    return {entry["study_label"]: entry for entry in log.get("studies", [])}


def save_extraction_log(
    studies: list[dict[str, Any]],
    output_dir: str,
) -> str:
    """Save extraction log incrementally."""
    path = os.path.join(output_dir, "extraction_log.json")
    log = {
        "extraction_date": datetime.now(timezone.utc).isoformat(),
        "schema_version": "1.0",
        "n_studies": len(studies),
        "studies": studies,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    return path


def save_model_extractions(
    studies: list[dict[str, Any]],
    output_dir: str,
) -> None:
    """Save separate files for each model's extractions."""
    for model_key, filename in [
        ("model_a", "claude_extractions.json"),
        ("model_b", "gpt_extractions.json"),
    ]:
        extractions = []
        for study in studies:
            model_data = study.get(model_key, {})
            if model_data and model_data.get("extraction"):
                extractions.append({
                    "study_label": study["study_label"],
                    "extraction": model_data["extraction"],
                })
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(extractions, f, indent=2, ensure_ascii=False)


# ============================================================================
# 7. MAIN
# ============================================================================

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DESAL Dual-LLM Extraction Orchestrator",
    )
    parser.add_argument(
        "--pdfs", required=True,
        help="Directory containing included study PDFs.",
    )
    parser.add_argument(
        "--output", default=str(PROJECT_ROOT / "extraction" / "data"),
        help="Output directory for extraction results.",
    )
    parser.add_argument(
        "--text-dir", default=str(PROJECT_ROOT / "extraction" / "extracted_text"),
        help="Directory for extracted text files.",
    )
    parser.add_argument(
        "--tables-dir", default=str(PROJECT_ROOT / "extraction" / "extracted_tables"),
        help="Directory for extracted table JSON files.",
    )
    parser.add_argument(
        "--claude-model", default=DEFAULT_CLAUDE_MODEL,
    )
    parser.add_argument(
        "--gpt-model", default=DEFAULT_GPT_MODEL,
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help="Seconds between API calls.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip studies already in extraction_log.json.",
    )
    return parser.parse_args(argv)


def run(
    pdf_dir: str,
    output_dir: str,
    text_dir: str,
    tables_dir: str,
    claude_model: str = DEFAULT_CLAUDE_MODEL,
    gpt_model: str = DEFAULT_GPT_MODEL,
    delay: float = DEFAULT_DELAY,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the full extraction pipeline on all PDFs."""

    # Validate environment
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY not set.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY not set.")

    # Ensure directories exist
    for d in [output_dir, text_dir, tables_dir]:
        os.makedirs(d, exist_ok=True)

    # Load schema and build prompt
    schema = load_extraction_schema()
    system_prompt = build_extraction_system_prompt(schema)
    print(f"System prompt: {len(system_prompt)} chars")

    # Find PDFs
    pdfs = find_pdfs(pdf_dir)
    print(f"Found {len(pdfs)} PDFs to extract.")

    # Resume logic
    existing = {}
    studies = []
    if resume:
        existing = load_existing_extractions(output_dir)
        studies = list(existing.values())
        print(f"Resuming: {len(existing)} studies already extracted.")

    # Process each PDF
    remaining = [p for p in pdfs if Path(p).stem not in existing]
    print(f"Studies to extract this run: {len(remaining)}")

    start_time = time.time()
    for i, pdf_path in enumerate(remaining):
        study_label = Path(pdf_path).stem
        print(f"\n[{i + 1}/{len(remaining)}] Extracting: {study_label}")

        result = extract_single_study(
            pdf_path=pdf_path,
            text_dir=text_dir,
            tables_dir=tables_dir,
            system_prompt=system_prompt,
            claude_model=claude_model,
            gpt_model=gpt_model,
            delay=delay,
        )
        studies.append(result)

        # Save progress after each study
        save_extraction_log(studies, output_dir)

    # Save final outputs
    save_extraction_log(studies, output_dir)
    save_model_extractions(studies, output_dir)

    elapsed = time.time() - start_time
    print(f"\nExtraction complete. {len(studies)} studies processed.")
    print(f"Time: {elapsed / 60:.1f} minutes")
    print(f"Outputs saved to {output_dir}")

    # Summary
    n_claude_ok = sum(1 for s in studies
                      if s.get("model_a", {}).get("extraction") is not None)
    n_gpt_ok = sum(1 for s in studies
                   if s.get("model_b", {}).get("extraction") is not None)
    print(f"Claude extractions: {n_claude_ok}/{len(studies)}")
    print(f"GPT extractions: {n_gpt_ok}/{len(studies)}")

    return {"n_studies": len(studies), "n_claude": n_claude_ok, "n_gpt": n_gpt_ok}


def main() -> None:
    args = parse_args()
    run(
        pdf_dir=args.pdfs,
        output_dir=args.output,
        text_dir=args.text_dir,
        tables_dir=args.tables_dir,
        claude_model=args.claude_model,
        gpt_model=args.gpt_model,
        delay=args.delay,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()

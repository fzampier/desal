#!/usr/bin/env python3
"""
DESAL Systematic Review — Dual-LLM Screening Orchestrator v1.0

Screens citations using two independent LLMs (Claude + GPT-5.4), applies
pre-specified resolution logic, and produces structured output files for
the DESAL systematic review and meta-analysis.

Requirements (pip install):
    anthropic openai pandas rispy pyyaml

Usage:
    python screening_orchestrator.py --input pubmed_results.csv --format csv
    python screening_orchestrator.py --input pubmed.nbib embase.ris --format auto
    python screening_orchestrator.py --resume --output-dir ./screening_output/

Environment variables required:
    ANTHROPIC_API_KEY
    OPENAI_API_KEY
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import rispy
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CLAUDE_MODEL = "claude-opus-4-6"
DEFAULT_GPT_MODEL = "gpt-5.4"
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_AUDIT_FRACTION = 0.10
DEFAULT_SEED = 42
DEFAULT_DELAY = 0.5
MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # exponential backoff base in seconds

VALID_DECISIONS = {"include", "exclude", "uncertain"}


# ============================================================================
# 1. CITATION INGESTION
# ============================================================================

def detect_format(filepath: str) -> str:
    """Auto-detect file format from extension.

    Returns one of 'csv', 'nbib', 'ris'.
    Raises ValueError if format cannot be determined.
    """
    ext = Path(filepath).suffix.lower()
    mapping = {
        ".csv": "csv",
        ".nbib": "nbib",
        ".medline": "nbib",
        ".ris": "ris",
        ".txt": "nbib",  # PubMed NBIB exports sometimes use .txt
    }
    fmt = mapping.get(ext)
    if fmt is None:
        # Peek at first lines to guess
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(500)
        if head.startswith("PMID-") or "\nPMID-" in head:
            return "nbib"
        if head.startswith("TY  -") or "\nTY  -" in head:
            return "ris"
        raise ValueError(
            f"Cannot auto-detect format for {filepath}. "
            "Use --format to specify csv, nbib, or ris."
        )
    return fmt


def parse_csv(filepath: str) -> list[dict[str, Any]]:
    """Parse PubMed CSV export into normalized citation dicts."""
    df = pd.read_csv(filepath, dtype=str).fillna("")
    # Normalize column names to lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    citations = []
    for _, row in df.iterrows():
        pmid = str(row.get("pmid", row.get("pubmed id", ""))).strip()
        citation_id = f"PMID_{pmid}" if pmid else f"CSV_{row.name}"
        citations.append({
            "citation_id": citation_id,
            "title": str(row.get("title", "")).strip(),
            "abstract": str(row.get("abstract", "")).strip(),
            "authors": str(row.get("authors", row.get("author", ""))).strip(),
            "year": str(row.get("year", row.get("publication year", ""))).strip(),
            "journal": str(row.get("journal", row.get("journal/book", ""))).strip(),
            "doi": str(row.get("doi", "")).strip(),
            "source_db": "pubmed",
        })
    return citations


def parse_nbib(filepath: str) -> list[dict[str, Any]]:
    """Parse PubMed NBIB/MEDLINE format into normalized citation dicts."""
    citations = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Split into records on blank lines followed by a new tag
    records = re.split(r"\n\n+(?=[A-Z]{2,4}\s*-)", content)

    for record in records:
        if not record.strip():
            continue
        fields: dict[str, list[str]] = {}
        current_tag = None
        for line in record.split("\n"):
            match = re.match(r"^([A-Z]{2,4})\s*-\s*(.*)", line)
            if match:
                current_tag = match.group(1).strip()
                value = match.group(2).strip()
                fields.setdefault(current_tag, []).append(value)
            elif current_tag and line.startswith("      "):
                # Continuation line
                fields[current_tag][-1] += " " + line.strip()

        pmid = " ".join(fields.get("PMID", [])).strip()
        if not pmid and not fields.get("TI"):
            continue  # skip empty records

        title = " ".join(fields.get("TI", [])).strip()
        abstract = " ".join(fields.get("AB", [])).strip()
        authors = "; ".join(fields.get("AU", []))
        year = ""
        dp = " ".join(fields.get("DP", [])).strip()
        if dp:
            year_match = re.search(r"(\d{4})", dp)
            if year_match:
                year = year_match.group(1)
        journal = " ".join(fields.get("JT", fields.get("TA", []))).strip()
        doi_field = " ".join(fields.get("AID", [])).strip()
        doi = ""
        for aid in fields.get("AID", []):
            if "[doi]" in aid.lower():
                doi = aid.replace("[doi]", "").strip()
                break

        citation_id = f"PMID_{pmid}" if pmid else f"HASH_{hashlib.md5(title.encode('utf-8')).hexdigest()[:12]}"
        citations.append({
            "citation_id": citation_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "journal": journal,
            "doi": doi,
            "source_db": "pubmed",
        })
    return citations


def parse_ris(filepath: str) -> list[dict[str, Any]]:
    """Parse Embase/generic RIS export into normalized citation dicts."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        entries = rispy.load(f)

    def _ris_str(val: Any) -> str:
        """Safely convert a rispy field value to a string.

        rispy can return lists for multi-valued fields; join them if so.
        """
        if val is None:
            return ""
        if isinstance(val, list):
            return "; ".join(str(v) for v in val)
        return str(val)

    citations = []
    for entry in entries:
        # RIS fields vary; rispy normalizes some
        notes = _ris_str(entry.get("notes", ""))
        pmid = _ris_str(entry.get("pubmed_id", "")) or notes
        pmid = pmid.strip()
        # Try to extract PMID from notes or accession number
        if not pmid or not pmid.isdigit():
            acc = _ris_str(entry.get("accession_number", "")).strip()
            if acc and acc.isdigit():
                pmid = acc
            else:
                pmid = ""

        title = _ris_str(entry.get("title", "") or entry.get("primary_title", "")).strip()
        abstract = _ris_str(entry.get("abstract", "")).strip()
        authors_list = entry.get("authors", entry.get("first_authors", []))
        if isinstance(authors_list, list):
            authors = "; ".join(str(a) for a in authors_list)
        else:
            authors = str(authors_list)
        year = _ris_str(entry.get("year", "") or entry.get("publication_year", "")).strip()
        journal = _ris_str(entry.get("journal_name", "") or entry.get("secondary_title", "")).strip()
        doi = _ris_str(entry.get("doi", "")).strip()

        if pmid:
            citation_id = f"PMID_{pmid}"
        else:
            citation_id = f"HASH_{hashlib.md5(title.encode('utf-8')).hexdigest()[:12]}"

        citations.append({
            "citation_id": citation_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "journal": journal,
            "doi": doi,
            "source_db": "embase",
        })
    return citations


def ingest_citations(input_paths: list[str], fmt: str) -> list[dict[str, Any]]:
    """Load citations from one or more input files.

    Args:
        input_paths: List of file paths.
        fmt: One of 'csv', 'nbib', 'ris', or 'auto'.

    Returns:
        List of normalized citation dicts.
    """
    all_citations: list[dict[str, Any]] = []
    for path in input_paths:
        file_fmt = fmt if fmt != "auto" else detect_format(path)
        print(f"Ingesting {path} as {file_fmt}...")
        if file_fmt == "csv":
            all_citations.extend(parse_csv(path))
        elif file_fmt == "nbib":
            all_citations.extend(parse_nbib(path))
        elif file_fmt == "ris":
            all_citations.extend(parse_ris(path))
        else:
            raise ValueError(f"Unknown format: {file_fmt}")
    return all_citations


def _normalize_title(title: str) -> str:
    """Normalize a title for fuzzy comparison: lowercase, strip punctuation/whitespace."""
    t = title.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)  # remove punctuation
    t = re.sub(r"\s+", " ", t).strip()  # collapse whitespace
    return t


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Insertions, deletions, substitutions
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def deduplicate(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate citations by DOI, PMID, and fuzzy title matching.

    De-duplication proceeds in three stages (per pipeline spec Section 1.2):
    1. Exact DOI match
    2. Exact PMID match
    3. Fuzzy title matching (Levenshtein distance ≤ 3 after normalization)
       — flagged as potential duplicates for manual review

    Keeps the first occurrence. Merges source_db if a duplicate came from
    a different database.
    """
    seen_dois: dict[str, int] = {}
    seen_pmids: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    fuzzy_flagged: list[tuple[str, str, int]] = []  # (title_a, title_b, distance)

    for cit in citations:
        doi = cit["doi"].lower().strip() if cit["doi"] else ""
        pmid = ""
        if cit["citation_id"].startswith("PMID_"):
            pmid = cit["citation_id"].replace("PMID_", "")

        is_dup = False
        dup_idx: Optional[int] = None

        # Stage 1: Exact DOI match
        if doi and doi in seen_dois:
            is_dup = True
            dup_idx = seen_dois[doi]
        # Stage 2: Exact PMID match
        elif pmid and pmid in seen_pmids:
            is_dup = True
            dup_idx = seen_pmids[pmid]

        if is_dup and dup_idx is not None:
            existing = deduped[dup_idx]
            if cit["source_db"] not in existing["source_db"]:
                existing["source_db"] += f",{cit['source_db']}"
            continue

        # Stage 3: Fuzzy title matching for records without DOI/PMID overlap
        if not doi and not pmid and cit["title"]:
            norm_title = _normalize_title(cit["title"])
            if len(norm_title) > 20:  # skip very short titles
                for j, existing in enumerate(deduped):
                    existing_norm = _normalize_title(existing["title"])
                    if len(existing_norm) <= 20:
                        continue
                    # Quick length filter to avoid computing distance on obviously
                    # different titles (distance can't be ≤3 if lengths differ by >3)
                    if abs(len(norm_title) - len(existing_norm)) > 3:
                        continue
                    dist = _levenshtein(norm_title, existing_norm)
                    if dist <= 3:
                        fuzzy_flagged.append((cit["title"], existing["title"], dist))
                        is_dup = True
                        dup_idx = j
                        break

            if is_dup and dup_idx is not None:
                existing = deduped[dup_idx]
                if cit["source_db"] not in existing["source_db"]:
                    existing["source_db"] += f",{cit['source_db']}"
                existing.setdefault("fuzzy_duplicate_of", []).append(cit["title"])
                continue

        idx = len(deduped)
        if doi:
            seen_dois[doi] = idx
        if pmid:
            seen_pmids[pmid] = idx
        deduped.append(cit)

    removed = len(citations) - len(deduped)
    if removed:
        print(f"De-duplication removed {removed} duplicate(s). {len(deduped)} unique citations remain.")
    if fuzzy_flagged:
        print(f"  ({len(fuzzy_flagged)} removed by fuzzy title matching — review these:)")
        for title_a, title_b, dist in fuzzy_flagged[:10]:
            print(f"    Distance {dist}: \"{title_a[:60]}...\" ≈ \"{title_b[:60]}...\"")
        if len(fuzzy_flagged) > 10:
            print(f"    ... and {len(fuzzy_flagged) - 10} more.")
    return deduped


# ============================================================================
# 2. SYSTEM PROMPT LOADING
# ============================================================================

def load_system_prompt(template_path: str) -> str:
    """Load the screening system prompt from screening_prompt_template.md.

    Extracts the content of the first fenced code block (``` ... ```)
    that contains the system prompt.
    """
    content = Path(template_path).read_text(encoding="utf-8")
    # Extract the first large code block (the system prompt)
    blocks = re.findall(r"```\n(.*?)```", content, re.DOTALL)
    if not blocks:
        raise FileNotFoundError(
            f"No code block found in {template_path}. "
            "Expected the system prompt inside a fenced code block."
        )
    # The first block is the system prompt; subsequent blocks are JSON examples
    return blocks[0].strip()


def build_user_message(citation: dict[str, Any]) -> str:
    """Build the user message for a single citation screening request."""
    abstract = citation["abstract"] if citation["abstract"] else "(No abstract available)"
    return (
        f"Citation ID: {citation['citation_id']}\n"
        f"Title: {citation['title']}\n"
        f"Abstract: {abstract}"
    )


# ============================================================================
# 3. LLM API CALLS
# ============================================================================

def call_claude(
    system_prompt: str,
    user_message: str,
    model: str,
    retry_count: int = 0,
) -> dict[str, Any]:
    """Screen a citation using Claude (Anthropic API).

    Returns the parsed JSON response dict or raises on final failure.
    """
    import anthropic

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

    for attempt in range(MAX_RETRIES):
        try:
            # If retrying due to bad JSON, append a nudge
            messages = [{"role": "user", "content": user_message}]
            if retry_count > 0:
                messages[0]["content"] += (
                    "\n\nIMPORTANT: Please respond with valid JSON only, "
                    "matching the expected output format exactly."
                )

            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )
            text = response.content[0].text.strip()
            return _parse_model_response(text)

        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                print(f"  Claude API error (attempt {attempt + 1}): {e}. Retrying in {wait:.0f}s...")
                time.sleep(wait)
            else:
                raise


def call_gpt(
    system_prompt: str,
    user_message: str,
    model: str,
    retry_count: int = 0,
) -> dict[str, Any]:
    """Screen a citation using GPT (OpenAI API).

    Returns the parsed JSON response dict or raises on final failure.
    """
    import openai

    client = openai.OpenAI()  # uses OPENAI_API_KEY env var

    for attempt in range(MAX_RETRIES):
        try:
            content = user_message
            if retry_count > 0:
                content += (
                    "\n\nIMPORTANT: Please respond with valid JSON only, "
                    "matching the expected output format exactly."
                )

            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
            )
            text = response.choices[0].message.content.strip()
            return _parse_model_response(text)

        except (openai.APIConnectionError, openai.RateLimitError, openai.APIStatusError) as e:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                print(f"  GPT API error (attempt {attempt + 1}): {e}. Retrying in {wait:.0f}s...")
                time.sleep(wait)
            else:
                raise


def _parse_model_response(text: str) -> dict[str, Any]:
    """Parse JSON from a model's text response.

    Handles cases where the model wraps JSON in markdown fences.
    Raises ValueError if JSON cannot be parsed.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    parsed = json.loads(cleaned)  # raises ValueError/JSONDecodeError on bad JSON

    # Validate required fields
    decision = parsed.get("decision", "").lower().strip()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Invalid decision value: '{decision}'")
    parsed["decision"] = decision

    confidence = parsed.get("confidence")
    if confidence is None or not isinstance(confidence, (int, float)):
        raise ValueError(f"Missing or invalid confidence: {confidence}")
    parsed["confidence"] = float(confidence)

    return parsed


def screen_single_citation(
    citation: dict[str, Any],
    system_prompt: str,
    claude_model: str,
    gpt_model: str,
    delay: float,
) -> dict[str, Any]:
    """Screen one citation with both models.

    Returns a log entry dict with both models' outputs.
    On unrecoverable parse/API failure for a model, returns a model_error entry.
    """
    user_msg = build_user_message(citation)
    result: dict[str, Any] = {"citation_id": citation["citation_id"]}

    # --- Model A: Claude ---
    result["model_a"] = _call_model_safe(
        call_fn=call_claude,
        model_name=claude_model,
        label="A (Claude)",
        system_prompt=system_prompt,
        user_message=user_msg,
    )
    time.sleep(delay)

    # --- Model B: GPT ---
    result["model_b"] = _call_model_safe(
        call_fn=call_gpt,
        model_name=gpt_model,
        label="B (GPT)",
        system_prompt=system_prompt,
        user_message=user_msg,
    )
    time.sleep(delay)

    return result


def _call_model_safe(
    call_fn,
    model_name: str,
    label: str,
    system_prompt: str,
    user_message: str,
) -> dict[str, Any]:
    """Call a model with retry-on-bad-JSON and full error wrapping.

    Returns either the parsed response dict (with model_name added)
    or a model_error dict.
    """
    try:
        resp = call_fn(system_prompt, user_message, model_name, retry_count=0)
        resp["model_name"] = model_name
        return resp
    except (json.JSONDecodeError, ValueError):
        # Retry once with a JSON nudge
        try:
            resp = call_fn(system_prompt, user_message, model_name, retry_count=1)
            resp["model_name"] = model_name
            return resp
        except Exception as e2:
            return _model_error_entry(model_name, f"Unparseable JSON after retry: {e2}")
    except Exception as e:
        return _model_error_entry(model_name, str(e))


def _model_error_entry(model_name: str, error_msg: str) -> dict[str, Any]:
    """Create a placeholder entry when a model call fails entirely."""
    return {
        "model_name": model_name,
        "decision": "model_error",
        "confidence": 0.0,
        "rationale": f"MODEL ERROR: {error_msg}",
        "exclusion_reason": None,
        "pico_assessment": None,
    }


# ============================================================================
# 4. RESOLUTION LOGIC
# ============================================================================

def resolve_decision(
    model_a: dict[str, Any],
    model_b: dict[str, Any],
    confidence_threshold: float,
) -> dict[str, Any]:
    """Apply the pre-specified resolution logic from screening_resolution_logic.md.

    Returns a resolution dict with fields: method, confidence_check_passed,
    final_decision, human_reviewer, human_override, audit_selected, timestamp.
    """
    dec_a = model_a.get("decision", "model_error")
    dec_b = model_b.get("decision", "model_error")
    conf_a = model_a.get("confidence", 0.0)
    conf_b = model_b.get("confidence", 0.0)

    timestamp = datetime.now(timezone.utc).isoformat()

    # Any model error → human review
    if dec_a == "model_error" or dec_b == "model_error":
        return {
            "method": "human_review_model_error",
            "confidence_check_passed": False,
            "final_decision": "human_review",
            "human_reviewer": None,
            "human_override": None,
            "audit_selected": False,
            "timestamp": timestamp,
        }

    # Both agree on INCLUDE
    if dec_a == "include" and dec_b == "include":
        if conf_a >= confidence_threshold and conf_b >= confidence_threshold:
            return {
                "method": "auto_include",
                "confidence_check_passed": True,
                "final_decision": "include",
                "human_reviewer": None,
                "human_override": None,
                "audit_selected": False,
                "timestamp": timestamp,
            }
        else:
            return {
                "method": "human_review_low_confidence_agreement",
                "confidence_check_passed": False,
                "final_decision": "human_review",
                "human_reviewer": None,
                "human_override": None,
                "audit_selected": False,
                "timestamp": timestamp,
            }

    # Both agree on EXCLUDE
    if dec_a == "exclude" and dec_b == "exclude":
        if conf_a >= confidence_threshold and conf_b >= confidence_threshold:
            return {
                "method": "auto_exclude",
                "confidence_check_passed": True,
                "final_decision": "exclude",
                "human_reviewer": None,
                "human_override": None,
                "audit_selected": False,  # set later during audit sampling
                "timestamp": timestamp,
            }
        else:
            return {
                "method": "human_review_low_confidence_agreement",
                "confidence_check_passed": False,
                "final_decision": "human_review",
                "human_reviewer": None,
                "human_override": None,
                "audit_selected": False,
                "timestamp": timestamp,
            }

    # Any disagreement or UNCERTAIN involvement → human review
    method = "human_review_disagreement"
    if dec_a == "uncertain" or dec_b == "uncertain":
        if dec_a == "uncertain" and dec_b == "uncertain":
            method = "human_review_both_uncertain"
        else:
            method = "human_review_uncertain_involvement"

    return {
        "method": method,
        "confidence_check_passed": False,
        "final_decision": "human_review",
        "human_reviewer": None,
        "human_override": None,
        "audit_selected": False,
        "timestamp": timestamp,
    }


# ============================================================================
# 5. AUDIT SAMPLING
# ============================================================================

def select_audit_sample(
    log_entries: list[dict[str, Any]],
    audit_fraction: float,
    seed: int,
) -> list[str]:
    """Select a random sample of auto-excluded citations for human audit.

    Returns list of citation_ids selected for audit.
    Modifies the log_entries in-place to set audit_selected=True on chosen items.
    """
    auto_excludes = [
        entry for entry in log_entries
        if entry["resolution"]["method"] == "auto_exclude"
    ]
    n_sample = max(1, math.ceil(len(auto_excludes) * audit_fraction))
    n_sample = min(n_sample, len(auto_excludes))

    rng = random.Random(seed)
    sampled = rng.sample(auto_excludes, n_sample)
    sampled_ids = set()

    for entry in sampled:
        entry["resolution"]["audit_selected"] = True
        sampled_ids.add(entry["citation_id"])

    print(f"Audit sample: {n_sample} of {len(auto_excludes)} auto-excludes selected.")
    return list(sampled_ids)


# ============================================================================
# 6. METRICS
# ============================================================================

def compute_metrics(log_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute inter-model agreement metrics and screening summary statistics."""
    decisions_a = []
    decisions_b = []
    confidences_a = []
    confidences_b = []

    counts = {
        "total": len(log_entries),
        "auto_include": 0,
        "auto_exclude": 0,
        "human_review": 0,
        "model_error": 0,
    }

    for entry in log_entries:
        dec_a = entry["model_a"].get("decision", "model_error")
        dec_b = entry["model_b"].get("decision", "model_error")
        conf_a = entry["model_a"].get("confidence", 0.0)
        conf_b = entry["model_b"].get("confidence", 0.0)

        if dec_a != "model_error" and dec_b != "model_error":
            decisions_a.append(dec_a)
            decisions_b.append(dec_b)
            confidences_a.append(conf_a)
            confidences_b.append(conf_b)

        method = entry["resolution"]["method"]
        if method == "auto_include":
            counts["auto_include"] += 1
        elif method == "auto_exclude":
            counts["auto_exclude"] += 1
        elif "model_error" in method:
            counts["model_error"] += 1
        else:
            counts["human_review"] += 1

    # Cohen's kappa
    kappa = _cohens_kappa(decisions_a, decisions_b)

    # Percent agreement
    agree = sum(1 for a, b in zip(decisions_a, decisions_b) if a == b)
    pct_agreement = agree / len(decisions_a) if decisions_a else 0.0

    # Auto-resolution rate
    auto_resolved = counts["auto_include"] + counts["auto_exclude"]
    auto_rate = auto_resolved / counts["total"] if counts["total"] else 0.0

    # Confidence distribution summaries
    def _conf_summary(vals: list[float]) -> dict[str, float]:
        if not vals:
            return {"mean": 0, "median": 0, "min": 0, "max": 0, "std": 0}
        s = sorted(vals)
        n = len(s)
        mean = sum(s) / n
        median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
        variance = sum((x - mean) ** 2 for x in s) / n
        return {
            "mean": round(mean, 4),
            "median": round(median, 4),
            "min": round(min(s), 4),
            "max": round(max(s), 4),
            "std": round(variance ** 0.5, 4),
        }

    return {
        "cohens_kappa": round(kappa, 4),
        "percent_agreement": round(pct_agreement, 4),
        "auto_resolution_rate": round(auto_rate, 4),
        "counts": counts,
        "confidence_model_a": _conf_summary(confidences_a),
        "confidence_model_b": _conf_summary(confidences_b),
        "n_valid_pairs": len(decisions_a),
    }


def _cohens_kappa(a: list[str], b: list[str]) -> float:
    """Compute Cohen's kappa for two lists of categorical decisions.

    Categories: include, exclude, uncertain.
    Returns kappa as a float. Returns 0.0 if undefined.
    """
    categories = ["include", "exclude", "uncertain"]
    n = len(a)
    if n == 0:
        return 0.0

    # Build confusion matrix
    matrix: dict[str, dict[str, int]] = {
        c1: {c2: 0 for c2 in categories} for c1 in categories
    }
    for ai, bi in zip(a, b):
        if ai in categories and bi in categories:
            matrix[ai][bi] += 1

    # Observed agreement
    po = sum(matrix[c][c] for c in categories) / n

    # Expected agreement
    pe = 0.0
    for c in categories:
        row_sum = sum(matrix[c][c2] for c2 in categories)
        col_sum = sum(matrix[c2][c] for c2 in categories)
        pe += (row_sum * col_sum) / (n * n)

    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0

    return (po - pe) / (1.0 - pe)


# ============================================================================
# 7. OUTPUT GENERATION
# ============================================================================

def save_screening_log(log_entries: list[dict[str, Any]], output_dir: str) -> str:
    """Save complete screening log as JSON."""
    path = os.path.join(output_dir, "screening_log.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, indent=2, ensure_ascii=False)
    return path


def save_screening_summary(
    log_entries: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    output_dir: str,
) -> str:
    """Save one-row-per-citation screening summary CSV."""
    title_lookup = {c["citation_id"]: c["title"] for c in citations}
    rows = []
    for entry in log_entries:
        cid = entry["citation_id"]
        needs_human = entry["resolution"]["final_decision"] == "human_review"
        rows.append({
            "citation_id": cid,
            "title": title_lookup.get(cid, ""),
            "model_a_decision": entry["model_a"].get("decision", ""),
            "model_a_confidence": entry["model_a"].get("confidence", ""),
            "model_b_decision": entry["model_b"].get("decision", ""),
            "model_b_confidence": entry["model_b"].get("confidence", ""),
            "resolution_method": entry["resolution"]["method"],
            "final_decision": entry["resolution"]["final_decision"],
            "needs_human_review": needs_human,
            "audit_selected": entry["resolution"]["audit_selected"],
        })

    path = os.path.join(output_dir, "screening_summary.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def save_human_review_queue(
    log_entries: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    output_dir: str,
) -> str:
    """Save citations routed to human review, including both models' rationales."""
    title_lookup = {c["citation_id"]: c for c in citations}
    rows = []
    for entry in log_entries:
        if entry["resolution"]["final_decision"] != "human_review":
            continue
        cid = entry["citation_id"]
        cit = title_lookup.get(cid, {})
        rows.append({
            "citation_id": cid,
            "title": cit.get("title", ""),
            "abstract": cit.get("abstract", ""),
            "model_a_decision": entry["model_a"].get("decision", ""),
            "model_a_confidence": entry["model_a"].get("confidence", ""),
            "model_a_rationale": entry["model_a"].get("rationale", ""),
            "model_a_exclusion_reason": entry["model_a"].get("exclusion_reason", ""),
            "model_b_decision": entry["model_b"].get("decision", ""),
            "model_b_confidence": entry["model_b"].get("confidence", ""),
            "model_b_rationale": entry["model_b"].get("rationale", ""),
            "model_b_exclusion_reason": entry["model_b"].get("exclusion_reason", ""),
            "resolution_method": entry["resolution"]["method"],
        })

    path = os.path.join(output_dir, "human_review_queue.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def save_audit_sample(
    log_entries: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    output_dir: str,
) -> str:
    """Save the 10% audit sample of auto-excludes."""
    title_lookup = {c["citation_id"]: c for c in citations}
    rows = []
    for entry in log_entries:
        if not entry["resolution"]["audit_selected"]:
            continue
        cid = entry["citation_id"]
        cit = title_lookup.get(cid, {})
        rows.append({
            "citation_id": cid,
            "title": cit.get("title", ""),
            "abstract": cit.get("abstract", ""),
            "model_a_decision": entry["model_a"].get("decision", ""),
            "model_a_confidence": entry["model_a"].get("confidence", ""),
            "model_a_rationale": entry["model_a"].get("rationale", ""),
            "model_a_exclusion_reason": entry["model_a"].get("exclusion_reason", ""),
            "model_b_decision": entry["model_b"].get("decision", ""),
            "model_b_confidence": entry["model_b"].get("confidence", ""),
            "model_b_rationale": entry["model_b"].get("rationale", ""),
            "model_b_exclusion_reason": entry["model_b"].get("exclusion_reason", ""),
        })

    path = os.path.join(output_dir, "audit_sample.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def save_metrics(metrics: dict[str, Any], output_dir: str) -> str:
    """Save screening metrics as JSON."""
    path = os.path.join(output_dir, "screening_metrics.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return path


# ============================================================================
# 8. RESUME LOGIC
# ============================================================================

def load_existing_log(output_dir: str) -> list[dict[str, Any]]:
    """Load an existing screening_log.json for resume functionality.

    Returns an empty list if the file doesn't exist.
    """
    path = os.path.join(output_dir, "screening_log.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_already_screened_ids(log_entries: list[dict[str, Any]]) -> set[str]:
    """Extract the set of citation_ids already in the screening log."""
    return {entry["citation_id"] for entry in log_entries}


# ============================================================================
# 9. MAIN ORCHESTRATION
# ============================================================================

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="DESAL Dual-LLM Screening Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python screening_orchestrator.py --input pubmed.csv --format csv\n"
            "  python screening_orchestrator.py --input pubmed.nbib embase.ris --format auto\n"
            "  python screening_orchestrator.py --resume --output-dir ./screening_output/\n"
        ),
    )
    parser.add_argument(
        "--input", nargs="+", required=False,
        help="Path(s) to input citation file(s). Required unless --resume.",
    )
    parser.add_argument(
        "--format", default="auto", choices=["csv", "ris", "nbib", "auto"],
        help="Input format. Use 'auto' to detect from extension (default: auto).",
    )
    parser.add_argument(
        "--output-dir", default="./screening_output/",
        help="Directory for output files (default: ./screening_output/).",
    )
    parser.add_argument(
        "--prompt-template", default=None,
        help="Path to screening_prompt_template.md. Auto-detected if adjacent to this script.",
    )
    parser.add_argument(
        "--claude-model", default=DEFAULT_CLAUDE_MODEL,
        help=f"Claude model string (default: {DEFAULT_CLAUDE_MODEL}).",
    )
    parser.add_argument(
        "--gpt-model", default=DEFAULT_GPT_MODEL,
        help=f"GPT model string (default: {DEFAULT_GPT_MODEL}).",
    )
    parser.add_argument(
        "--confidence-threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD,
        help=f"Confidence threshold for auto-resolution (default: {DEFAULT_CONFIDENCE_THRESHOLD}).",
    )
    parser.add_argument(
        "--audit-fraction", type=float, default=DEFAULT_AUDIT_FRACTION,
        help=f"Fraction of auto-excludes to audit (default: {DEFAULT_AUDIT_FRACTION}).",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"Random seed for audit sampling (default: {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"Seconds between API calls (default: {DEFAULT_DELAY}).",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from existing screening_log.json, skipping already-screened citations.",
    )
    return parser.parse_args(argv)


def run(
    input_paths: list[str],
    fmt: str = "auto",
    output_dir: str = "./screening_output/",
    prompt_template_path: Optional[str] = None,
    claude_model: str = DEFAULT_CLAUDE_MODEL,
    gpt_model: str = DEFAULT_GPT_MODEL,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    audit_fraction: float = DEFAULT_AUDIT_FRACTION,
    seed: int = DEFAULT_SEED,
    delay: float = DEFAULT_DELAY,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the full screening pipeline.

    This is the main entry point for both CLI and programmatic usage.
    Returns the computed metrics dict.
    """
    # --- Validate environment ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY environment variable not set.")

    # --- Resolve prompt template ---
    if prompt_template_path is None:
        script_dir = Path(__file__).parent
        prompt_template_path = str(script_dir / "screening_prompt_template.md")
    if not os.path.exists(prompt_template_path):
        raise FileNotFoundError(f"Prompt template not found: {prompt_template_path}")

    system_prompt = load_system_prompt(prompt_template_path)
    print(f"Loaded system prompt ({len(system_prompt)} chars) from {prompt_template_path}")

    # --- Create output directory ---
    os.makedirs(output_dir, exist_ok=True)

    # --- Ingest and deduplicate ---
    citations = ingest_citations(input_paths, fmt)
    citations = deduplicate(citations)
    total = len(citations)
    print(f"Total unique citations to screen: {total}")

    # --- Resume logic ---
    log_entries: list[dict[str, Any]] = []
    already_done: set[str] = set()
    if resume:
        log_entries = load_existing_log(output_dir)
        already_done = get_already_screened_ids(log_entries)
        print(f"Resuming: {len(already_done)} citations already screened.")

    # --- Screen each citation ---
    remaining = [c for c in citations if c["citation_id"] not in already_done]
    n_remaining = len(remaining)
    print(f"Citations to screen this run: {n_remaining}")
    start_time = time.time()

    for i, citation in enumerate(remaining):
        idx_display = len(already_done) + i + 1
        elapsed = time.time() - start_time
        rate = (i + 1) / elapsed if elapsed > 0 and i > 0 else 0
        eta = (n_remaining - i - 1) / rate if rate > 0 else 0

        print(
            f"Screening citation {idx_display}/{total}... ",
            end="", flush=True,
        )

        try:
            result = screen_single_citation(
                citation, system_prompt, claude_model, gpt_model, delay
            )
        except Exception as e:
            # Never crash on a single citation
            print(f"FATAL ERROR: {e}")
            result = {
                "citation_id": citation["citation_id"],
                "model_a": _model_error_entry(claude_model, str(e)),
                "model_b": _model_error_entry(gpt_model, str(e)),
            }

        # Resolve
        resolution = resolve_decision(
            result["model_a"], result["model_b"], confidence_threshold
        )
        result["resolution"] = resolution
        log_entries.append(result)

        # Print summary line
        dec_a = result["model_a"].get("decision", "error")
        conf_a = result["model_a"].get("confidence", 0)
        dec_b = result["model_b"].get("decision", "error")
        conf_b = result["model_b"].get("confidence", 0)
        final = resolution["final_decision"]
        method = resolution["method"]
        eta_str = f"{eta / 60:.1f}min" if eta > 60 else f"{eta:.0f}s"

        print(
            f"Model A: {dec_a.upper()} ({conf_a:.2f}), "
            f"Model B: {dec_b.upper()} ({conf_b:.2f}) "
            f"→ {method} "
            f"[ETA: {eta_str}]"
        )

        # Save progress after each citation (enables --resume)
        save_screening_log(log_entries, output_dir)

    # --- Audit sampling ---
    audit_ids = select_audit_sample(log_entries, audit_fraction, seed)

    # --- Compute metrics ---
    metrics = compute_metrics(log_entries)
    print(f"\nScreening complete. Cohen's kappa: {metrics['cohens_kappa']}")
    print(f"Auto-resolution rate: {metrics['auto_resolution_rate']:.1%}")
    print(f"Counts: {metrics['counts']}")

    # --- Save all outputs ---
    save_screening_log(log_entries, output_dir)
    save_screening_summary(log_entries, citations, output_dir)
    save_human_review_queue(log_entries, citations, output_dir)
    save_audit_sample(log_entries, citations, output_dir)
    save_metrics(metrics, output_dir)

    elapsed_total = time.time() - start_time
    print(f"\nAll outputs saved to {output_dir}")
    print(f"Total screening time: {elapsed_total / 60:.1f} minutes")

    return metrics


def main() -> None:
    """CLI entry point."""
    args = parse_args()

    if not args.input and not args.resume:
        print("Error: --input is required unless using --resume.", file=sys.stderr)
        sys.exit(1)

    input_paths = args.input or []

    # When resuming without new input, we still need the original citations
    # to rebuild output files. Check if screening_log exists.
    if args.resume and not input_paths:
        log = load_existing_log(args.output_dir)
        if not log:
            print(
                "Error: --resume specified without --input, but no existing "
                "screening_log.json found in output directory.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            "Warning: Resuming without --input. Output files (summary, "
            "human_review_queue) will only contain citations from the log, "
            "not the full citation metadata. Provide --input for complete outputs."
        )

    run(
        input_paths=input_paths,
        fmt=args.format,
        output_dir=args.output_dir,
        prompt_template_path=args.prompt_template,
        claude_model=args.claude_model,
        gpt_model=args.gpt_model,
        confidence_threshold=args.confidence_threshold,
        audit_fraction=args.audit_fraction,
        seed=args.seed,
        delay=args.delay,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()

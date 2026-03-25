#!/usr/bin/env python3
"""
Verify extracted numbers exist in source text.
Catches hallucinated statistics by checking if numbers actually appear in document.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional


def strip_references(text: str) -> tuple[str, bool]:
    """
    Remove references/bibliography section from text.
    Returns (cleaned_text, was_stripped).
    """
    # Common reference section headers - allow leading whitespace, flexible line endings
    patterns = [
        r'\n\s*References\s*[\n$]',
        r'\n\s*REFERENCES\s*[\n$]',
        r'\n\s*Bibliography\s*[\n$]',
        r'\n\s*BIBLIOGRAPHY\s*[\n$]',
        r'\n\s*Literature Cited\s*[\n$]',
        r'\n\s*Works Cited\s*[\n$]',
        r'\n\s*Citations\s*[\n$]',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return text[:match.start()], True
    
    return text, False


def strip_inline_citations(text: str) -> str:
    """
    Remove inline citation patterns that could cause false positives.
    E.g., "BMJ 2010; 340: c117" or "Lancet 2020; 395: 1569-78"
    """
    # Pattern: year; volume: page (journal citation format)
    # Matches: "2010; 340: c117", "2020; 395: 1569-78", etc.
    text = re.sub(r'\d{4};\s*\d+:\s*\w+[-–]?\w*', '[CITATION]', text)
    
    # Pattern: (ref numbers) like (1), (1,2), (1-3), superscript refs
    text = re.sub(r'\(\d+(?:[,\-–]\d+)*\)', '[REF]', text)
    
    return text


def extract_all_numbers(text: str) -> set[str]:
    """Extract all numbers from text, normalized."""
    # Normalize text: replace middle dot with period, remove spaces in numbers
    normalized = text.replace('·', '.')
    
    # Match integers, decimals, and scientific notation
    patterns = [
        r'\d+\.\d+',           # decimals: 30.8, 0.001
        r'\d{1,3}(?:\s\d{3})+', # spaced thousands: 20 211, 10 096
        r'\d+',                 # integers: 115, 281
        r'\d+e[+-]?\d+',       # scientific: 1e-5
    ]
    
    numbers = set()
    for pattern in patterns:
        for match in re.findall(pattern, normalized, re.IGNORECASE):
            # Normalize: remove spaces from spaced numbers
            clean = match.replace(' ', '')
            numbers.add(clean)
            numbers.add(match)  # keep original too
            # Also add without leading zeros for matching flexibility
            if clean.startswith('0.'):
                numbers.add(clean[1:])  # .001 from 0.001
    
    return numbers


def verify_number(number: str, source_numbers: set[str], source_text: str) -> dict:
    """Check if a specific number exists in source."""
    # Normalize source text for raw search
    normalized_source = source_text.replace('·', '.')
    
    # Direct match
    if number in source_numbers:
        return {"status": "verified", "method": "exact"}
    
    # Try with/without leading zero
    if number.startswith('.'):
        alt = '0' + number
        if alt in source_numbers:
            return {"status": "verified", "method": "leading_zero"}
    elif number.startswith('0.'):
        alt = number[1:]
        if alt in source_numbers:
            return {"status": "verified", "method": "no_leading_zero"}
    
    # Check if number appears in normalized text (catches formatting variations)
    if number in normalized_source:
        return {"status": "verified", "method": "raw_text"}
    
    # Check for spaced version of large numbers (e.g., 20211 -> 20 211)
    if len(number) > 3 and number.isdigit():
        # Try inserting space every 3 digits from right
        spaced = ' '.join([number[max(0,i-3):i] for i in range(len(number), 0, -3)][::-1])
        if spaced in source_text:
            return {"status": "verified", "method": "spaced_thousands"}
    
    return {"status": "unverified", "method": None}


def verify_claims(source_text: str, claims: list[dict]) -> list[dict]:
    """Verify all claims against source text."""
    source_numbers = extract_all_numbers(source_text)
    results = []
    
    for claim in claims:
        claim_result = {
            "claim": claim.get("claim", ""),
            "category": claim.get("category", ""),
            "numbers": [],
            "all_verified": True
        }
        
        for num in claim.get("numbers", []):
            verification = verify_number(str(num), source_numbers, source_text)
            num_result = {
                "number": num,
                "verified": verification["status"] == "verified",
                "method": verification["method"]
            }
            claim_result["numbers"].append(num_result)
            if not num_result["verified"]:
                claim_result["all_verified"] = False
        
        results.append(claim_result)
    
    return results


def format_report(results: list[dict]) -> str:
    """Format verification results as human-readable report."""
    lines = ["=" * 60, "VERIFICATION REPORT", "=" * 60, ""]
    
    verified_count = sum(1 for r in results if r["all_verified"])
    total_count = len(results)
    
    lines.append(f"Summary: {verified_count}/{total_count} claims fully verified")
    lines.append("")
    
    # Show unverified first (these need attention)
    unverified = [r for r in results if not r["all_verified"]]
    if unverified:
        lines.append("⚠️  UNVERIFIED CLAIMS (potential hallucinations):")
        lines.append("-" * 40)
        for r in unverified:
            lines.append(f"  Claim: {r['claim']}")
            for n in r["numbers"]:
                status = "✓" if n["verified"] else "✗"
                lines.append(f"    {status} {n['number']}")
            lines.append("")
    
    # Then verified
    verified = [r for r in results if r["all_verified"]]
    if verified:
        lines.append("✓ VERIFIED CLAIMS:")
        lines.append("-" * 40)
        for r in verified:
            nums = ", ".join(n["number"] for n in r["numbers"])
            lines.append(f"  [{r['category']}] {r['claim']}")
            lines.append(f"    Numbers: {nums}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: verify_numbers.py <source.txt> <claims.json>")
        print("       verify_numbers.py <source.txt> '<json_string>'")
        sys.exit(1)
    
    source_path = Path(sys.argv[1])
    claims_input = sys.argv[2]
    
    # Read source text
    if not source_path.exists():
        print(f"Error: Source file not found: {source_path}")
        sys.exit(1)
    
    source_text = source_path.read_text(encoding='utf-8', errors='ignore')
    
    # Strip references section
    source_text, refs_stripped = strip_references(source_text)
    if refs_stripped:
        print("Note: References section excluded from verification.")
    
    # Strip inline citations
    source_text = strip_inline_citations(source_text)
    print("Note: Inline citation patterns filtered.\n")
    
    # Parse claims (file or inline JSON)
    if Path(claims_input).exists():
        claims = json.loads(Path(claims_input).read_text())
    else:
        claims = json.loads(claims_input)
    
    # Verify
    results = verify_claims(source_text, claims)
    
    # Output
    print(format_report(results))
    
    # Also output JSON for programmatic use
    json_output = Path(source_path.stem + "_verification.json")
    json_output.write_text(json.dumps(results, indent=2))
    print(f"\nJSON results saved to: {json_output}")
    
    # Exit code: 0 if all verified, 1 if any unverified
    if all(r["all_verified"] for r in results):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

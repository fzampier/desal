#!/usr/bin/env python3
"""
Clinical data verification with unit-aware extraction.
Matches numbers WITH their context (units, surrounding words).
"""

import re
import json
import sys
from pathlib import Path

def strip_references(text):
    """Remove references section."""
    patterns = [
        r'\n\s*References\s*\n',
        r'\n\s*REFERENCES\s*\n',
        r'\n\s*Bibliography\s*\n',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if match:
            return text[:match.start()], True
    return text, False

def strip_inline_citations(text):
    """Filter citation patterns."""
    # Dates: MM/DD/YYYY
    text = re.sub(r'\d{1,2}/\d{1,2}/\d{2,4}', '[DATE]', text)
    # Journal citations: 2024;12(4):323-336 or 2010; 340: c117
    text = re.sub(r'\d{4};\s*\d+\(?\d*\)?:\s*[\w\-–]+', '[CITATION]', text)
    # Reference numbers: (1,2,3) or (1-5)
    text = re.sub(r'\(\d+(?:[,\-–]\d+)*\)', '[REF]', text)
    return text

def extract_number_contexts(text, window=40):
    """
    Extract all numbers with surrounding context.
    Returns list of (number_str, left_context, right_context, full_match)
    """
    contexts = []
    
    # Match numbers: integers, decimals, negative
    pattern = r'(-?\d+\.?\d*)'
    
    for match in re.finditer(pattern, text):
        num_str = match.group(1)
        start, end = match.start(), match.end()
        
        # Get surrounding context
        left_start = max(0, start - window)
        right_end = min(len(text), end + window)
        
        left_ctx = text[left_start:start].lower()
        right_ctx = text[end:right_end].lower()
        
        contexts.append({
            'number': num_str,
            'left': left_ctx,
            'right': right_ctx,
            'position': start
        })
    
    return contexts

def categorize_context(left, right):
    """
    Categorize what type of number this is based on context.
    Returns set of categories.
    """
    combined = left + ' ' + right
    categories = set()
    
    # Patient counts
    if re.search(r'(patients?|subjects?|participants?|n\s*=|enrolled|completed|screened)', combined):
        categories.add('patients')
    
    # Percentages
    if re.search(r'%|\bpercent', combined):
        categories.add('percentage')
    
    # Time units
    if re.search(r'(hours?|hrs?|minutes?|mins?|days?|months?|years?|weeks?)\b', combined):
        categories.add('time')
    
    # Drug doses
    if re.search(r'(mcg|mg|μg|ug)/(kg|ml|h|min)', combined):
        categories.add('dose')
    
    # Specific drugs
    if re.search(r'(propofol|pro\b|dex\b|dexmedetomidine|fentanyl)', combined):
        if 'fentanyl' in combined:
            categories.add('fentanyl')
        if re.search(r'(propofol|pro\b)', combined):
            categories.add('propofol')
        if re.search(r'(dex\b|dexmedetomidine)', combined):
            categories.add('dexmedetomidine')
    
    # Score/scale
    if re.search(r'(score|scale|ace\b|sofa|rass|points?)', combined):
        categories.add('score')
    
    # Confidence intervals
    if re.search(r'(ci|confidence|interval)', combined):
        categories.add('ci')
    
    # Age
    if re.search(r'(age|years?\s*old|\byears?\b.*median|\byears?\b.*mean)', combined):
        categories.add('age')
    
    # BMI ranges
    if re.search(r'(bmi|body mass|underweight|overweight|obese|normal\s*\()', combined):
        categories.add('bmi')
    
    # Hemodynamics
    if re.search(r'(bpm|heart rate|pulse|bp\b|mmhg)', combined):
        categories.add('hemodynamic')
    
    # Effect sizes / changes
    if re.search(r'(change|difference|improvement|decrease|increase|delta)', combined):
        categories.add('effect')
    
    return categories

def parse_claim_context(claim_text):
    """Extract expected context from claim text."""
    claim_lower = claim_text.lower()
    expected = set()
    
    if re.search(r'patients?|completed|enrolled|screened', claim_lower):
        expected.add('patients')
    if '%' in claim_lower or 'percent' in claim_lower:
        expected.add('percentage')
    if re.search(r'hours?|mins?|minutes?|days?', claim_lower):
        expected.add('time')
    if re.search(r'dose|mcg|mg', claim_lower):
        expected.add('dose')
    if 'fentanyl' in claim_lower:
        expected.add('fentanyl')
    if re.search(r'propofol|pro\b', claim_lower):
        expected.add('propofol')
    if re.search(r'dex\b|dexmedetomidine', claim_lower):
        expected.add('dexmedetomidine')
    if re.search(r'score|ace\b|sofa', claim_lower):
        expected.add('score')
    if re.search(r'ci|confidence', claim_lower):
        expected.add('ci')
    if re.search(r'\bage\b', claim_lower):
        expected.add('age')
    if re.search(r'bpm|bradycardia', claim_lower):
        expected.add('hemodynamic')
    if re.search(r'change|difference|decreased|improved', claim_lower):
        expected.add('effect')
    
    return expected

def context_compatible(claim_ctx, source_ctx):
    """
    Check if claim context is compatible with source context.
    Returns (compatible, reason)
    """
    # If claim expects specific drug, source must match
    drugs = {'fentanyl', 'propofol', 'dexmedetomidine'}
    claim_drugs = claim_ctx & drugs
    source_drugs = source_ctx & drugs
    
    if claim_drugs and source_drugs:
        if not (claim_drugs & source_drugs):  # No overlap
            return False, f"drug mismatch: claim={claim_drugs}, source={source_drugs}"
    
    # BMI context shouldn't match patient counts or scores
    if 'bmi' in source_ctx:
        if claim_ctx & {'patients', 'score', 'effect'}:
            return False, "BMI range vs clinical measure"
    
    # Patient counts shouldn't come from other contexts
    if 'patients' in claim_ctx:
        if source_ctx & {'bmi', 'dose', 'ci'}:
            return False, f"patient count from wrong context: {source_ctx}"
    
    return True, "compatible"

def verify_number_with_context(num_str, claim_text, source_contexts):
    """
    Verify a number exists in source with compatible context.
    Returns (found, match_info)
    """
    claim_ctx = parse_claim_context(claim_text)
    
    # Normalize number for matching
    try:
        num_val = float(num_str)
    except:
        return False, "invalid number"
    
    matches = []
    for ctx in source_contexts:
        try:
            src_val = float(ctx['number'])
        except:
            continue
        
        # Check if numbers match (with tolerance for floats)
        if abs(src_val - num_val) < 0.01 or ctx['number'] == num_str:
            source_ctx = categorize_context(ctx['left'], ctx['right'])
            compatible, reason = context_compatible(claim_ctx, source_ctx)
            matches.append({
                'source_num': ctx['number'],
                'source_ctx': list(source_ctx),
                'claim_ctx': list(claim_ctx),
                'compatible': compatible,
                'reason': reason,
                'snippet': f"...{ctx['left'][-20:]}{ctx['number']}{ctx['right'][:20]}..."
            })
    
    # Check for compatible matches
    compatible_matches = [m for m in matches if m['compatible']]
    
    if compatible_matches:
        return True, compatible_matches[0]
    elif matches:
        return False, matches[0]  # Found but incompatible
    else:
        return False, "not found"

def verify_claims(source_text, claims):
    """Verify all claims against source."""
    # Preprocess
    source_text, refs_stripped = strip_references(source_text)
    source_text = strip_inline_citations(source_text)
    
    # Extract all number contexts from source
    source_contexts = extract_number_contexts(source_text)
    
    results = {
        'verified': [],
        'unverified': [],
        'context_mismatch': []
    }
    
    for claim in claims:
        claim_text = claim.get('claim', '')
        numbers = claim.get('numbers', [])
        category = claim.get('category', 'unknown')
        
        all_verified = True
        failed_numbers = []
        mismatch_info = []
        
        for num in numbers:
            found, info = verify_number_with_context(num, claim_text, source_contexts)
            if not found:
                all_verified = False
                if isinstance(info, dict):
                    failed_numbers.append(num)
                    mismatch_info.append(info)
                else:
                    failed_numbers.append(num)
        
        result = {
            'claim': claim_text,
            'numbers': numbers,
            'category': category
        }
        
        if all_verified:
            results['verified'].append(result)
        elif mismatch_info:
            result['failed'] = failed_numbers
            result['mismatch'] = mismatch_info
            results['context_mismatch'].append(result)
        else:
            result['failed'] = failed_numbers
            results['unverified'].append(result)
    
    return results, refs_stripped

def print_report(results, refs_stripped):
    """Print verification report."""
    if refs_stripped:
        print("Note: References section excluded from verification.")
    print("Note: Unit-aware context matching enabled.\n")
    
    total = len(results['verified']) + len(results['unverified']) + len(results['context_mismatch'])
    verified = len(results['verified'])
    
    print("=" * 60)
    print("VERIFICATION REPORT (v2 - Context-Aware)")
    print("=" * 60)
    print(f"\nSummary: {verified}/{total} claims verified")
    
    if results['context_mismatch']:
        print(f"\n⚠️  CONTEXT MISMATCH ({len(results['context_mismatch'])} claims):")
        print("-" * 40)
        for r in results['context_mismatch']:
            print(f"  Claim: {r['claim']}")
            print(f"    Numbers found but WRONG CONTEXT:")
            for m in r.get('mismatch', []):
                print(f"      '{m['source_num']}': {m['reason']}")
                print(f"        Source context: {m['source_ctx']}")
                print(f"        Claim expects: {m['claim_ctx']}")
            print()
    
    if results['unverified']:
        print(f"\n✗ UNVERIFIED ({len(results['unverified'])} claims):")
        print("-" * 40)
        for r in results['unverified']:
            print(f"  Claim: {r['claim']}")
            print(f"    Missing: {', '.join(r['failed'])}")
            print()
    
    if results['verified']:
        print(f"\n✓ VERIFIED ({len(results['verified'])} claims):")
        print("-" * 40)
        for r in results['verified']:
            print(f"  [{r['category']}] {r['claim']}")
            print(f"    Numbers: {', '.join(r['numbers'])}")
    
    print()

def main():
    if len(sys.argv) < 3:
        print("Usage: verify_numbers_v2.py <source.txt> <claims.json>")
        sys.exit(1)
    
    source_path = Path(sys.argv[1])
    claims_path = Path(sys.argv[2])
    
    source_text = source_path.read_text()
    claims = json.loads(claims_path.read_text())
    
    results, refs_stripped = verify_claims(source_text, claims)
    print_report(results, refs_stripped)
    
    # Save JSON
    out_path = source_path.stem + "_verification_v2.json"
    Path(out_path).write_text(json.dumps(results, indent=2))
    print(f"JSON results saved to: {out_path}")

if __name__ == "__main__":
    main()

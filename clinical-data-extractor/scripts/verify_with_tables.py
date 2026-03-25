#!/usr/bin/env python3
"""
Two-layer verification with context display for human review.

Key insight: Table verification finds numbers reliably, but humans must
verify the CONTEXT matches the claim. This script highlights where each
number was found to speed up human review.
"""

import json
import re
import sys
from pathlib import Path


def load_table_data(tables_json_path):
    with open(tables_json_path) as f:
        return json.load(f)


def load_claims(claims_path):
    with open(claims_path) as f:
        return json.load(f)


def normalize_number(num_str):
    num_str = str(num_str).strip()
    try:
        if '.' in num_str:
            return str(float(num_str))
        else:
            return str(int(num_str))
    except:
        return num_str


def is_citation_context(context):
    """Detect if context looks like a citation/reference."""
    patterns = [
        r'\d{4};\d+:\d+',  # Journal citation: 2011;112:635
        r'page \d+',
        r'reference',
        r'et al\.',
        r'Lancet|JAMA|NEJM|BMJ|Ann|Crit Care|Intensive Care'
    ]
    for p in patterns:
        if re.search(p, context, re.IGNORECASE):
            return True
    return False


def verify_number_in_tables(number, table_lookup):
    num_str = str(number)
    normalized = normalize_number(num_str)
    
    if num_str in table_lookup:
        return table_lookup[num_str]
    if normalized in table_lookup:
        return table_lookup[normalized]
    return None


def verify_number_in_text(number, text):
    num_str = str(number)
    pattern = r'(?<![0-9\.])\b' + re.escape(num_str) + r'\b(?![0-9])'
    return len(re.findall(pattern, text)) > 0


def verify_claims(claims, table_data, source_text=None):
    """Verify claims and provide context for human review."""
    
    table_lookup = table_data.get('number_lookup', {})
    results = []
    
    for claim in claims:
        claim_text = claim.get('claim', '')
        numbers = claim.get('numbers', [])
        category = claim.get('category', 'unknown')
        
        verification = {
            'claim': claim_text,
            'category': category,
            'numbers': {},
            'overall_status': 'VERIFIED',
            'confidence': 'HIGH',
            'needs_review': False,
            'review_reason': []
        }
        
        all_table_verified = True
        all_verified = True
        
        for num in numbers:
            num_result = {
                'value': num,
                'status': 'UNVERIFIED',
                'confidence': 'NONE',
                'table_locations': [],
                'in_text': False,
                'warning': None
            }
            
            table_matches = verify_number_in_tables(num, table_lookup)
            if table_matches:
                num_result['status'] = 'TABLE_VERIFIED'
                num_result['confidence'] = 'HIGH'
                num_result['table_locations'] = table_matches[:3]
                
                # Check for suspicious contexts
                all_citations = all(is_citation_context(m['context']) for m in table_matches)
                if all_citations:
                    num_result['warning'] = 'CITATION_ONLY'
                    num_result['confidence'] = 'LOW'
                    verification['needs_review'] = True
                    verification['review_reason'].append(f"'{num}' only found in citations")
                    
            elif source_text and verify_number_in_text(num, source_text):
                num_result['status'] = 'TEXT_ONLY'
                num_result['confidence'] = 'MEDIUM'
                num_result['in_text'] = True
                all_table_verified = False
                verification['needs_review'] = True
                verification['review_reason'].append(f"'{num}' not in tables")
            else:
                num_result['status'] = 'UNVERIFIED'
                num_result['confidence'] = 'NONE'
                all_verified = False
                all_table_verified = False
            
            verification['numbers'][num] = num_result
        
        if not all_verified:
            verification['overall_status'] = 'UNVERIFIED'
            verification['confidence'] = 'NONE'
        elif all_table_verified:
            verification['overall_status'] = 'TABLE_VERIFIED'
            verification['confidence'] = 'HIGH'
        else:
            verification['overall_status'] = 'TEXT_ONLY'
            verification['confidence'] = 'MEDIUM'
        
        results.append(verification)
    
    return results


def print_report(results):
    """Print report with context for human review."""
    print("=" * 70)
    print("VERIFICATION REPORT (Table-Enhanced v2)")
    print("=" * 70)
    
    table_verified = [r for r in results if r['overall_status'] == 'TABLE_VERIFIED']
    text_only = [r for r in results if r['overall_status'] == 'TEXT_ONLY']
    unverified = [r for r in results if r['overall_status'] == 'UNVERIFIED']
    needs_review = [r for r in results if r.get('needs_review')]
    
    print(f"\nSummary:")
    print(f"  ✓✓ TABLE VERIFIED:  {len(table_verified)}")
    print(f"  ✓  TEXT ONLY:       {len(text_only)}")
    print(f"  ✗  UNVERIFIED:      {len(unverified)}")
    print(f"  ⚠️  NEEDS REVIEW:    {len(needs_review)}")
    
    if unverified:
        print(f"\n{'='*70}")
        print("✗ UNVERIFIED (numbers not found - likely fabrication)")
        print("-" * 70)
        for r in unverified:
            print(f"\n  Claim: {r['claim']}")
            for num, info in r['numbers'].items():
                if info['status'] == 'UNVERIFIED':
                    print(f"    ✗ '{num}' NOT FOUND anywhere")
    
    # Show ALL verified claims with their context for human review
    print(f"\n{'='*70}")
    print("CONTEXT CHECK (verify numbers match claim semantically)")
    print("-" * 70)
    
    for r in results:
        if r['overall_status'] == 'UNVERIFIED':
            continue
            
        flag = "⚠️ " if r.get('needs_review') else "✓ "
        print(f"\n{flag}[{r['category']}] {r['claim']}")
        
        for num, info in r['numbers'].items():
            status_icon = {
                'TABLE_VERIFIED': '✓',
                'TEXT_ONLY': '~',
                'UNVERIFIED': '✗'
            }.get(info['status'], '?')
            
            warn = f" ⚠️ {info['warning']}" if info.get('warning') else ""
            print(f"    {status_icon} '{num}'{warn}")
            
            # Show where found
            for loc in info.get('table_locations', [])[:2]:
                ctx = loc['context'][:60].replace('\n', ' ')
                print(f"        → Page {loc['page']}: \"{ctx}...\"")
    
    return {
        'table_verified': len(table_verified),
        'text_only': len(text_only),
        'unverified': len(unverified),
        'needs_review': len(needs_review)
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python verify_with_tables.py <tables.json> <claims.json> [source.txt]")
        sys.exit(1)
    
    tables_path = sys.argv[1]
    claims_path = sys.argv[2]
    source_text = None
    
    if len(sys.argv) > 3:
        with open(sys.argv[3]) as f:
            source_text = f.read()
    
    table_data = load_table_data(tables_path)
    claims = load_claims(claims_path)
    
    results = verify_claims(claims, table_data, source_text)
    summary = print_report(results)
    
    output_path = Path(claims_path).stem + '_table_verification.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n\nResults saved to: {output_path}")


if __name__ == '__main__':
    main()

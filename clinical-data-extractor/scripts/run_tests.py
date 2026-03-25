#!/usr/bin/env python3
"""
Automated test suite for clinical-data-extractor.
Generates known fabrications and measures detection rates.
"""

import json
import subprocess
import sys
import random
from pathlib import Path

# Test cases: real values from papers + fabricated variants
TEST_CASES = {
    "6s_trial": {
        "text_file": "/home/claude/6s_trial.txt",
        "tables_file": "/home/claude/6s_tables.json",
        "real_claims": [
            {"claim": "798 patients in modified ITT", "numbers": ["798"]},
            {"claim": "90-day mortality 51% HES vs 43% Ringer's", "numbers": ["51", "43"]},
            {"claim": "RR 1.17 (95% CI 1.01-1.36)", "numbers": ["1.17", "1.01", "1.36"]},
            {"claim": "RRT: 22% vs 16%, RR 1.35", "numbers": ["22", "16", "1.35"]},
            {"claim": "Severe bleeding 10% vs 6%", "numbers": ["10", "6"]},
        ],
        "fabricated_claims": [
            {"claim": "920 patients randomized", "numbers": ["920"], "type": "wrong_n"},
            {"claim": "90-day mortality 62%", "numbers": ["62"], "type": "context_swap"},  # From SAPS IQR
            {"claim": "RR 1.45 (95% CI 1.15-1.82)", "numbers": ["1.45", "1.15", "1.82"], "type": "invented_effect"},
            {"claim": "RRT in 112 patients", "numbers": ["112"], "type": "citation_number"},  # Journal ref
            {"claim": "Mortality 38%", "numbers": ["38"], "type": "context_swap"},  # Bleeding count
            {"claim": "SOFA score 9 median", "numbers": ["9"], "type": "context_swap"},  # Address
        ]
    },
    "3cpo_trial": {
        "text_file": "/home/claude/3cpo.txt", 
        "tables_file": "/home/claude/3cpo_tables.json",
        "real_claims": [
            {"claim": "1069 patients randomized", "numbers": ["1069"]},
            {"claim": "7-day mortality 9.8% standard vs 9.5% NIV", "numbers": ["9.8", "9.5"]},
            {"claim": "OR 0.97 (95% CI 0.63-1.48)", "numbers": ["0.97", "0.63", "1.48"]},
            {"claim": "30-day mortality 16.4% vs 15.2%", "numbers": ["16.4", "15.2"]},
            {"claim": "Mean age 77.7 years", "numbers": ["77.7"]},
        ],
        "fabricated_claims": [
            {"claim": "1250 patients enrolled", "numbers": ["1250"], "type": "wrong_n"},
            {"claim": "7-day mortality 6.2%", "numbers": ["6.2"], "type": "invented"},
            {"claim": "OR 1.45 (95% CI 1.12-1.89)", "numbers": ["1.45", "1.12", "1.89"], "type": "invented_effect"},
            {"claim": "30-day mortality 22.5%", "numbers": ["22.5"], "type": "invented"},
            {"claim": "Mean age 72.3 years", "numbers": ["72.3"], "type": "wrong_baseline"},
            {"claim": "Intubation rate 8.4%", "numbers": ["8.4"], "type": "context_swap"},  # Treatment failure %
        ]
    }
}


def run_verification(tables_file, claims, text_file):
    """Run table verification and return results."""
    # Write claims to temp file
    claims_file = "/tmp/test_claims.json"
    with open(claims_file, 'w') as f:
        json.dump(claims, f)
    
    # Run verification
    result = subprocess.run([
        "python3", 
        "/home/claude/clinical-data-extractor/scripts/verify_with_tables.py",
        tables_file,
        claims_file,
        text_file
    ], capture_output=True, text=True)
    
    # Parse output
    output = result.stdout
    
    # Count results
    unverified = output.count("NOT FOUND anywhere")
    citation_only = output.count("CITATION_ONLY") + output.count("⚠️")
    
    return {
        'output': output,
        'unverified_count': unverified,
        'flagged_count': citation_only
    }


def run_benford(tables_file):
    """Run Benford check."""
    result = subprocess.run([
        "python3",
        "/home/claude/clinical-data-extractor/scripts/benford_check.py",
        tables_file
    ], capture_output=True, text=True)
    
    if "SUSPICIOUS" in result.stdout:
        return "SUSPICIOUS"
    elif "CONSISTENT" in result.stdout:
        return "CONSISTENT"
    else:
        return "UNKNOWN"


def test_paper(name, config):
    """Run full test suite on a paper."""
    print(f"\n{'='*70}")
    print(f"TESTING: {name}")
    print(f"{'='*70}")
    
    # Check files exist
    if not Path(config['text_file']).exists():
        print(f"  ⚠️  Text file not found: {config['text_file']}")
        return None
    if not Path(config['tables_file']).exists():
        print(f"  ⚠️  Tables file not found: {config['tables_file']}")
        return None
    
    results = {
        'real': {'total': 0, 'verified': 0},
        'fabricated': {'total': 0, 'caught': 0, 'flagged': 0, 'missed': 0},
        'by_type': {}
    }
    
    # Test real claims
    print(f"\n--- Real Claims ({len(config['real_claims'])}) ---")
    real_result = run_verification(
        config['tables_file'],
        config['real_claims'],
        config['text_file']
    )
    
    results['real']['total'] = len(config['real_claims'])
    # Count verified (not unverified)
    for claim in config['real_claims']:
        all_found = True
        for num in claim['numbers']:
            if f"'{num}' NOT FOUND" in real_result['output']:
                all_found = False
                break
        if all_found:
            results['real']['verified'] += 1
            print(f"  ✓ {claim['claim'][:50]}...")
        else:
            print(f"  ✗ {claim['claim'][:50]}... (FALSE NEGATIVE)")
    
    # Test fabricated claims
    print(f"\n--- Fabricated Claims ({len(config['fabricated_claims'])}) ---")
    fab_result = run_verification(
        config['tables_file'],
        config['fabricated_claims'],
        config['text_file']
    )
    
    results['fabricated']['total'] = len(config['fabricated_claims'])
    
    for claim in config['fabricated_claims']:
        fab_type = claim.get('type', 'unknown')
        if fab_type not in results['by_type']:
            results['by_type'][fab_type] = {'total': 0, 'caught': 0}
        results['by_type'][fab_type]['total'] += 1
        
        # Check if any number was flagged as not found
        any_not_found = False
        any_flagged = False
        for num in claim['numbers']:
            if f"'{num}' NOT FOUND" in fab_result['output']:
                any_not_found = True
                break
            if f"'{num}'" in fab_result['output'] and "CITATION" in fab_result['output']:
                any_flagged = True
        
        if any_not_found:
            results['fabricated']['caught'] += 1
            results['by_type'][fab_type]['caught'] += 1
            print(f"  ✓ CAUGHT: {claim['claim'][:45]}... [{fab_type}]")
        elif any_flagged:
            results['fabricated']['flagged'] += 1
            print(f"  ⚠️ FLAGGED: {claim['claim'][:45]}... [{fab_type}]")
        else:
            results['fabricated']['missed'] += 1
            print(f"  ✗ MISSED: {claim['claim'][:45]}... [{fab_type}]")
    
    # Benford check
    print(f"\n--- Benford Check ---")
    benford = run_benford(config['tables_file'])
    results['benford'] = benford
    print(f"  Status: {benford}")
    
    return results


def print_summary(all_results):
    """Print overall summary."""
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    
    total_real = sum(r['real']['total'] for r in all_results.values() if r)
    total_real_verified = sum(r['real']['verified'] for r in all_results.values() if r)
    
    total_fab = sum(r['fabricated']['total'] for r in all_results.values() if r)
    total_caught = sum(r['fabricated']['caught'] for r in all_results.values() if r)
    total_flagged = sum(r['fabricated']['flagged'] for r in all_results.values() if r)
    total_missed = sum(r['fabricated']['missed'] for r in all_results.values() if r)
    
    print(f"\nReal claims: {total_real_verified}/{total_real} verified ({100*total_real_verified/total_real:.0f}%)")
    print(f"Fabrications: {total_caught}/{total_fab} auto-caught ({100*total_caught/total_fab:.0f}%)")
    print(f"             {total_flagged}/{total_fab} flagged ({100*total_flagged/total_fab:.0f}%)")
    print(f"             {total_missed}/{total_fab} missed ({100*total_missed/total_fab:.0f}%)")
    print(f"\nEffective detection (caught + flagged): {total_caught + total_flagged}/{total_fab} ({100*(total_caught+total_flagged)/total_fab:.0f}%)")
    
    # By fabrication type
    print(f"\n--- Detection by Fabrication Type ---")
    all_types = {}
    for r in all_results.values():
        if r and 'by_type' in r:
            for t, v in r['by_type'].items():
                if t not in all_types:
                    all_types[t] = {'total': 0, 'caught': 0}
                all_types[t]['total'] += v['total']
                all_types[t]['caught'] += v['caught']
    
    for t, v in sorted(all_types.items()):
        pct = 100 * v['caught'] / v['total'] if v['total'] > 0 else 0
        status = "✓" if pct >= 50 else "⚠️" if pct > 0 else "✗"
        print(f"  {status} {t}: {v['caught']}/{v['total']} ({pct:.0f}%)")


def main():
    print("="*70)
    print("CLINICAL DATA EXTRACTOR - TEST SUITE")
    print("="*70)
    
    all_results = {}
    
    for name, config in TEST_CASES.items():
        result = test_paper(name, config)
        all_results[name] = result
    
    print_summary(all_results)
    
    print(f"\n{'='*70}")
    print("TEST COMPLETE")
    print("="*70)


if __name__ == '__main__':
    main()

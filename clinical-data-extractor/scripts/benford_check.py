#!/usr/bin/env python3
"""
Benford's Law check for extracted numbers.
Detects systematic fabrication patterns in aggregate.

Benford expected distribution for leading digit:
  1: 30.1%, 2: 17.6%, 3: 12.5%, 4: 9.7%, 5: 7.9%
  6: 6.7%, 7: 5.8%, 8: 5.1%, 9: 4.6%
"""

import json
import math
import sys
from collections import Counter

# Benford's Law expected frequencies
BENFORD = {
    1: 0.301, 2: 0.176, 3: 0.125, 4: 0.097, 5: 0.079,
    6: 0.067, 7: 0.058, 8: 0.051, 9: 0.046
}


def get_leading_digit(num_str):
    """Extract leading digit from number string."""
    # Remove negative sign, leading zeros, decimal point
    num_str = str(num_str).lstrip('-0').replace('.', '')
    if not num_str or not num_str[0].isdigit():
        return None
    digit = int(num_str[0])
    return digit if digit > 0 else None


def chi_square_test(observed, expected, n):
    """Calculate chi-square statistic and approximate p-value."""
    chi2 = 0
    for digit in range(1, 10):
        obs = observed.get(digit, 0)
        exp = expected[digit] * n
        if exp > 0:
            chi2 += (obs - exp) ** 2 / exp
    
    # Approximate p-value (df=8 for 9 categories - 1)
    # Using rough critical values
    if chi2 > 20.09:
        p_approx = "< 0.01"
    elif chi2 > 15.51:
        p_approx = "< 0.05"
    elif chi2 > 13.36:
        p_approx = "< 0.10"
    else:
        p_approx = "> 0.10"
    
    return chi2, p_approx


def analyze_numbers(numbers, label=""):
    """Analyze leading digit distribution."""
    leading_digits = []
    excluded = {'constrained': 0, 'invalid': 0}
    
    for num in numbers:
        try:
            val = float(num)
            # Exclude constrained ranges that don't follow Benford
            # - Percentages often 0-100
            # - P-values 0-1
            # - Very small numbers (likely p-values, effect sizes)
            if 0 < val < 1:
                excluded['constrained'] += 1
                continue
            if val > 100 and val < 1000:
                # Likely legitimate (patient counts, etc)
                pass
        except:
            excluded['invalid'] += 1
            continue
        
        digit = get_leading_digit(num)
        if digit:
            leading_digits.append(digit)
    
    if len(leading_digits) < 30:
        return {
            'status': 'INSUFFICIENT_DATA',
            'n': len(leading_digits),
            'message': f'Need 30+ numbers, got {len(leading_digits)}'
        }
    
    # Count observed frequencies
    observed = Counter(leading_digits)
    n = len(leading_digits)
    
    # Chi-square test
    chi2, p_approx = chi_square_test(observed, BENFORD, n)
    
    # Calculate deviation from Benford
    deviations = {}
    for digit in range(1, 10):
        obs_pct = observed.get(digit, 0) / n * 100
        exp_pct = BENFORD[digit] * 100
        deviations[digit] = {
            'observed': observed.get(digit, 0),
            'observed_pct': round(obs_pct, 1),
            'expected_pct': round(exp_pct, 1),
            'deviation': round(obs_pct - exp_pct, 1)
        }
    
    # Flag if significant deviation
    if chi2 > 15.51:
        status = 'SUSPICIOUS'
    elif chi2 > 13.36:
        status = 'MARGINAL'
    else:
        status = 'CONSISTENT'
    
    return {
        'status': status,
        'n': n,
        'excluded': excluded,
        'chi_square': round(chi2, 2),
        'p_value': p_approx,
        'distribution': deviations
    }


def print_report(result, label=""):
    """Print Benford analysis report."""
    print("=" * 60)
    print(f"BENFORD'S LAW CHECK {label}")
    print("=" * 60)
    
    if result['status'] == 'INSUFFICIENT_DATA':
        print(f"\n⚠️  {result['message']}")
        print("Benford's Law requires larger sample sizes.")
        return
    
    status_icon = {
        'CONSISTENT': '✓',
        'MARGINAL': '⚠️',
        'SUSPICIOUS': '🚨'
    }[result['status']]
    
    print(f"\nStatus: {status_icon} {result['status']}")
    print(f"Numbers analyzed: {result['n']}")
    print(f"Chi-square: {result['chi_square']} (p {result['p_value']})")
    
    print(f"\nLeading Digit Distribution:")
    print(f"{'Digit':<6} {'Observed':<10} {'Expected':<10} {'Deviation':<10}")
    print("-" * 40)
    
    for digit in range(1, 10):
        d = result['distribution'][digit]
        dev_str = f"{d['deviation']:+.1f}%"
        flag = " ⚠️" if abs(d['deviation']) > 10 else ""
        print(f"{digit:<6} {d['observed_pct']:>6.1f}%    {d['expected_pct']:>6.1f}%    {dev_str:>8}{flag}")
    
    if result['status'] == 'SUSPICIOUS':
        print(f"\n🚨 WARNING: Distribution significantly deviates from Benford's Law")
        print("   This MAY indicate fabricated or manipulated data.")
        print("   However, clinical data often has legitimate deviations due to")
        print("   constrained ranges (ages, percentages, physiologic values).")
    elif result['status'] == 'MARGINAL':
        print(f"\n⚠️  Marginal deviation - worth reviewing but not conclusive")


def main():
    if len(sys.argv) < 2:
        print("Usage: python benford_check.py <claims.json|tables.json>")
        print("\nAnalyzes leading digit distribution of extracted numbers.")
        sys.exit(1)
    
    with open(sys.argv[1]) as f:
        data = json.load(f)
    
    # Extract numbers based on file format
    numbers = []
    
    if 'number_lookup' in data:
        # Tables JSON format
        numbers = list(data['number_lookup'].keys())
        label = "(from tables)"
    elif isinstance(data, list) and data and 'numbers' in data[0]:
        # Claims JSON format
        for claim in data:
            numbers.extend(claim.get('numbers', []))
        label = "(from claims)"
    else:
        print("Unknown file format")
        sys.exit(1)
    
    result = analyze_numbers(numbers, label)
    print_report(result, label)
    
    return result


if __name__ == '__main__':
    main()

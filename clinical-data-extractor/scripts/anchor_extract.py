#!/usr/bin/env python3
"""
Anchor-based extraction: Extract numbers only when near semantically relevant context.
Adapted from DeepSeek approach with additions for clinical trial data.

This constrains extraction upfront — numbers are only captured if they appear
within a window of relevant anchor terms.
"""

import re
import json
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Callable
from pathlib import Path


@dataclass
class FieldRule:
    name: str
    value_regex: re.Pattern
    anchors: List[re.Pattern]
    window_chars: int = 250
    require_anchor: bool = True
    postcheck: Optional[Callable] = None
    category: str = "unknown"


def normalize(text: str) -> str:
    """Normalize whitespace and remove soft hyphens."""
    t = text.replace("\u00ad", "")
    t = re.sub(r"\s+", " ", t)
    return t


def find_with_anchor(text: str, rule: FieldRule) -> List[Dict]:
    """
    Find all matches with anchor context.
    Returns list of {start, end, match, evidence, anchor}
    """
    hits = []
    
    if not rule.require_anchor or not rule.anchors:
        # No anchor required - search whole text
        for m in rule.value_regex.finditer(text):
            s, e = m.span()
            snippet = text[max(0, s-100):min(len(text), e+100)]
            hits.append({
                'start': s,
                'end': e,
                'match': m.group(0),
                'evidence': snippet,
                'anchor': None
            })
        return hits
    
    # Search within windows around anchors
    for anchor_pattern in rule.anchors:
        for am in anchor_pattern.finditer(text):
            anchor_start, anchor_end = am.span()
            anchor_text = am.group(0)
            
            # Define window around anchor
            window_start = max(0, anchor_start - rule.window_chars)
            window_end = min(len(text), anchor_end + rule.window_chars)
            window = text[window_start:window_end]
            
            # Find values within window
            for vm in rule.value_regex.finditer(window):
                s, e = vm.span()
                match_text = vm.group(0)
                
                # Position in full text
                full_start = window_start + s
                full_end = window_start + e
                
                # Evidence snippet
                snippet_start = max(0, window_start - 30)
                snippet_end = min(len(text), window_end + 30)
                snippet = text[snippet_start:snippet_end]
                
                hits.append({
                    'start': full_start,
                    'end': full_end,
                    'match': match_text,
                    'evidence': snippet,
                    'anchor': anchor_text
                })
    
    # Deduplicate by position
    seen = set()
    unique_hits = []
    for h in hits:
        key = (h['start'], h['end'])
        if key not in seen:
            seen.add(key)
            unique_hits.append(h)
    
    return unique_hits


def extract_field(text: str, rule: FieldRule) -> Dict:
    """Extract first valid match for a field."""
    hits = find_with_anchor(text, rule)
    
    if not hits:
        return {
            'status': 'NOT_FOUND',
            'match': None,
            'evidence': None,
            'anchor': None
        }
    
    # Sort by length (prefer shorter/cleaner), then position
    hits.sort(key=lambda x: (len(x['match']), x['start']))
    
    for hit in hits:
        # Apply postcheck if defined
        if rule.postcheck and not rule.postcheck(hit['match']):
            continue
        return {
            'status': 'FOUND',
            'match': hit['match'],
            'evidence': hit['evidence'][:200],
            'anchor': hit['anchor']
        }
    
    return {
        'status': 'POSTCHECK_FAILED',
        'match': hits[0]['match'] if hits else None,
        'evidence': hits[0]['evidence'][:200] if hits else None,
        'anchor': hits[0]['anchor'] if hits else None
    }


def extract_all_matches(text: str, rule: FieldRule) -> List[Dict]:
    """Extract all matches for a field (not just first)."""
    hits = find_with_anchor(text, rule)
    
    valid_hits = []
    for hit in hits:
        if rule.postcheck and not rule.postcheck(hit['match']):
            continue
        valid_hits.append({
            'match': hit['match'],
            'evidence': hit['evidence'][:150],
            'anchor': hit['anchor']
        })
    
    return valid_hits


# ============ REGEX PATTERNS ============

# Registration/identifiers
RX_NCT = re.compile(r"\bNCT\d{8}\b", re.I)
RX_ISRCTN = re.compile(r"\bISRCTN\d{8,11}\b", re.I)
RX_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)

# Sample size
RX_N_EQ = re.compile(r"\b[nN]\s*=\s*(\d{1,5})\b")
RX_N_PATIENTS = re.compile(r"\b(\d{2,5})\s*(?:patients?|subjects?|participants?)\b", re.I)

# Effect estimates
RX_RR = re.compile(r"\b(?:RR|relative risk)\s*[=:,]?\s*(\d+\.?\d*)\b", re.I)
RX_OR = re.compile(r"\b(?:OR|odds ratio)\s*[=:,]?\s*(\d+\.?\d*)\b", re.I)
RX_HR = re.compile(r"\b(?:HR|hazard ratio)\s*[=:,]?\s*(\d+\.?\d*)\b", re.I)
RX_ARR = re.compile(r"\b(?:ARR|absolute risk reduction)\s*[=:,]?\s*-?(\d+\.?\d*)\s*%?\b", re.I)
RX_NNT = re.compile(r"\b(?:NNT|number needed to treat)\s*[=:,]?\s*(\d+\.?\d*)\b", re.I)
RX_MD = re.compile(r"\b(?:MD|mean difference)\s*[=:,]?\s*-?(\d+\.?\d*)\b", re.I)

# Confidence intervals
RX_CI = re.compile(r"\b(95%?|90%?|99%?)\s*CI\s*[=:,]?\s*\(?(-?\d+\.?\d*)\s*(?:to|,|-)\s*(-?\d+\.?\d*)\)?", re.I)

# P-values
RX_P = re.compile(r"\b[Pp]\s*([=<>])\s*(0\.\d+|<?\s*0\.0+1)\b")

# Events/denominators with percentage: 201/398 (51%)
RX_EVENTS_PCT = re.compile(r"\b(\d{1,5})\s*/\s*(\d{1,5})\s*\(\s*(\d{1,3}\.?\d*)\s*%\s*\)")

# Percentage alone
RX_PCT = re.compile(r"\b(\d{1,3}\.?\d*)\s*%\b")

# Follow-up duration
RX_FOLLOWUP = re.compile(r"\b(?:follow-?up|followed)\s*(?:for|of|period)?\s*(\d+)\s*(days?|weeks?|months?|years?)\b", re.I)

# Mortality rate as percentage
RX_MORT_PCT = re.compile(r"\b(\d{1,3}\.?\d*)\s*%", re.I)

# Doses
RX_DOSE = re.compile(r"\b(\d+\.?\d*)\s*(mg|mcg|µg|g|mL|IU|U)(?:/kg)?(?:/(min|h|hr|hour|day))?\b", re.I)

# Time to event
RX_MEDIAN_TIME = re.compile(r"\bmedian\s*(?:time)?\s*(?:to)?\s*(\d+\.?\d*)\s*(days?|hours?|weeks?)\b", re.I)


# ============ ANCHOR PATTERNS ============

A_RANDOM = [
    re.compile(r"\brandomi[sz]ed\b", re.I),
    re.compile(r"\brandom(?:ly)?\s+assign", re.I),
    re.compile(r"\ballocat(?:ed|ion)\b", re.I),
    re.compile(r"\benroll(?:ed|ment)\b", re.I),
]

A_PRIMARY = [
    re.compile(r"\bprimary\s+(?:outcome|endpoint|end-?point)\b", re.I),
    re.compile(r"\bprimary\s+(?:efficacy|objective)\b", re.I),
]

A_SECONDARY = [
    re.compile(r"\bsecondary\s+(?:outcome|endpoint)\b", re.I),
]

A_MORTALITY = [
    re.compile(r"\bmortality\b", re.I),
    re.compile(r"\bdeath(?:s)?\b", re.I),
    re.compile(r"\bdied\b", re.I),
    re.compile(r"\bsurvival\b", re.I),
    re.compile(r"\bfatal(?:ity)?\b", re.I),
]

A_AKI = [
    re.compile(r"\bacute kidney\b", re.I),
    re.compile(r"\bAKI\b"),
    re.compile(r"\brenal.{0,20}(?:failure|injury|replacement)\b", re.I),
    re.compile(r"\bdialysis\b", re.I),
    re.compile(r"\bRRT\b"),
]

A_VENT = [
    re.compile(r"\bmechanical ventilation\b", re.I),
    re.compile(r"\bintubat(?:ed|ion)\b", re.I),
    re.compile(r"\bventilator\b", re.I),
]

A_LOS = [
    re.compile(r"\blength of stay\b", re.I),
    re.compile(r"\bLOS\b"),
    re.compile(r"\bhospital(?:ization)?\s+(?:stay|days?|duration)\b", re.I),
    re.compile(r"\bICU\s+(?:stay|days?|duration)\b", re.I),
]

A_SAE = [
    re.compile(r"\bserious adverse event\b", re.I),
    re.compile(r"\bSAE\b"),
    re.compile(r"\badverse\s+(?:event|effect)\b", re.I),
]

A_BLEEDING = [
    re.compile(r"\bbleeding\b", re.I),
    re.compile(r"\bhemorrhag", re.I),
    re.compile(r"\btransfusion\b", re.I),
]

A_CI = [
    re.compile(r"\b(?:95%?|90%?|99%?)\s*CI\b", re.I),
    re.compile(r"\bconfidence interval\b", re.I),
]

A_P = [
    re.compile(r"\b[Pp]\s*[=<>]\s*0\.", re.I),
    re.compile(r"\b[Pp]-?value\b", re.I),
]

A_REG = [
    re.compile(r"\btrial regist", re.I),
    re.compile(r"\bregistered\b", re.I),
    re.compile(r"\bclinicaltrials\.gov\b", re.I),
    re.compile(r"\bISRCTN\b", re.I),
    re.compile(r"\bNCT\b", re.I),
]

A_DOSE = [
    re.compile(r"\bdose\b", re.I),
    re.compile(r"\bdosage\b", re.I),
    re.compile(r"\badminister(?:ed)?\b", re.I),
    re.compile(r"\binfusion\b", re.I),
]


# ============ POSTCHECKS ============

def postcheck_pval(s: str) -> bool:
    """Reject p=0.000 or p=0"""
    return not re.search(r"[Pp]\s*=\s*0(\.0+)?$", s)

def postcheck_pct_reasonable(s: str) -> bool:
    """Reject percentages > 100"""
    match = re.search(r"(\d+\.?\d*)\s*%", s)
    if match:
        val = float(match.group(1))
        return val <= 100
    return True


# ============ FIELD RULES ============

RULES = [
    # Identifiers
    FieldRule("nct_number", RX_NCT, A_REG, window_chars=600, require_anchor=False, category="registration"),
    FieldRule("isrctn", RX_ISRCTN, A_REG, window_chars=600, require_anchor=False, category="registration"),
    FieldRule("doi", RX_DOI, [re.compile(r"\bdoi\b", re.I)], window_chars=400, require_anchor=False, category="registration"),
    
    # Sample size
    FieldRule("n_randomized", RX_N_EQ, A_RANDOM, window_chars=300, category="enrollment"),
    FieldRule("n_patients", RX_N_PATIENTS, A_RANDOM, window_chars=200, category="enrollment"),
    
    # Effect estimates (near CI or primary outcome)
    FieldRule("relative_risk", RX_RR, A_CI + A_PRIMARY, window_chars=400, category="effect"),
    FieldRule("odds_ratio", RX_OR, A_CI + A_PRIMARY, window_chars=400, category="effect"),
    FieldRule("hazard_ratio", RX_HR, A_CI + A_PRIMARY, window_chars=400, category="effect"),
    FieldRule("mean_difference", RX_MD, A_CI + A_PRIMARY, window_chars=400, category="effect"),
    FieldRule("nnt", RX_NNT, A_PRIMARY + A_MORTALITY, window_chars=400, category="effect"),
    
    # CI and p-values
    FieldRule("confidence_interval", RX_CI, A_CI, window_chars=500, category="statistics"),
    FieldRule("p_value", RX_P, A_P + A_PRIMARY, window_chars=400, postcheck=postcheck_pval, category="statistics"),
    
    # Outcome-specific extractions
    FieldRule("mortality_events", RX_EVENTS_PCT, A_MORTALITY, window_chars=600, category="outcome_mortality"),
    FieldRule("mortality_pct", RX_MORT_PCT, A_MORTALITY, window_chars=400, postcheck=postcheck_pct_reasonable, category="outcome_mortality"),
    
    FieldRule("aki_events", RX_EVENTS_PCT, A_AKI, window_chars=600, category="outcome_aki"),
    FieldRule("rrt_events", RX_EVENTS_PCT, A_AKI, window_chars=600, category="outcome_aki"),
    
    FieldRule("intubation_events", RX_EVENTS_PCT, A_VENT, window_chars=600, category="outcome_vent"),
    FieldRule("bleeding_events", RX_EVENTS_PCT, A_BLEEDING, window_chars=600, category="outcome_safety"),
    FieldRule("sae_events", RX_EVENTS_PCT, A_SAE, window_chars=600, category="outcome_safety"),
    
    # Follow-up and LOS
    FieldRule("followup_duration", RX_FOLLOWUP, A_PRIMARY + A_MORTALITY, window_chars=500, category="methods"),
    FieldRule("los_icu", RX_MEDIAN_TIME, A_LOS, window_chars=400, category="outcome_los"),
    
    # Doses
    FieldRule("intervention_dose", RX_DOSE, A_DOSE, window_chars=300, category="intervention"),
]


def run_extraction(text: str, return_all: bool = False) -> Dict:
    """
    Run all extraction rules on text.
    
    Args:
        text: Source text
        return_all: If True, return all matches per field; if False, just first
    
    Returns:
        Dict of field_name -> extraction result
    """
    t = normalize(text)
    results = {}
    
    for rule in RULES:
        if return_all:
            matches = extract_all_matches(t, rule)
            results[rule.name] = {
                'status': 'FOUND' if matches else 'NOT_FOUND',
                'count': len(matches),
                'matches': matches,
                'category': rule.category
            }
        else:
            result = extract_field(t, rule)
            result['category'] = rule.category
            results[rule.name] = result
    
    return results


def print_report(results: Dict):
    """Print extraction report."""
    print("=" * 70)
    print("ANCHOR-BASED EXTRACTION REPORT")
    print("=" * 70)
    
    # Group by category
    by_category = {}
    for name, res in results.items():
        cat = res.get('category', 'unknown')
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append((name, res))
    
    found_count = sum(1 for r in results.values() if r['status'] == 'FOUND')
    print(f"\nExtracted: {found_count}/{len(results)} fields\n")
    
    for category, items in sorted(by_category.items()):
        print(f"\n[{category.upper()}]")
        print("-" * 50)
        
        for name, res in items:
            status_icon = "✓" if res['status'] == 'FOUND' else "✗"
            
            if res['status'] == 'FOUND':
                match = res.get('match', '')
                anchor = res.get('anchor', '')
                if 'matches' in res:
                    # Multiple matches mode
                    print(f"  {status_icon} {name}: {res['count']} matches")
                    for m in res['matches'][:3]:
                        print(f"      → {m['match']}")
                        if m.get('anchor'):
                            print(f"        (near '{m['anchor'][:30]}...')")
                else:
                    print(f"  {status_icon} {name}: {match}")
                    if anchor:
                        print(f"      (near '{anchor[:40]}...')")
            else:
                print(f"  {status_icon} {name}: not found")


def main():
    if len(sys.argv) < 2:
        print("Usage: python anchor_extract.py <source.txt> [output.json]")
        print("\nExtracts structured fields using anchor-based approach.")
        print("Numbers are only captured if near semantically relevant context.")
        sys.exit(1)
    
    source_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    with open(source_path) as f:
        text = f.read()
    
    # Run extraction with all matches
    results = run_extraction(text, return_all=True)
    
    print_report(results)
    
    if output_path:
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {output_path}")
    
    # Also output as claims format for verification pipeline
    claims = []
    for name, res in results.items():
        if res['status'] == 'FOUND':
            for m in res.get('matches', [{'match': res.get('match')}]):
                # Extract numbers from match
                numbers = re.findall(r'-?\d+\.?\d*', m['match'])
                if numbers:
                    claims.append({
                        'claim': f"{name}: {m['match']}",
                        'numbers': numbers,
                        'category': res['category'],
                        'anchor': m.get('anchor', '')
                    })
    
    claims_path = Path(source_path).stem + '_extracted_claims.json'
    with open(claims_path, 'w') as f:
        json.dump(claims, f, indent=2)
    print(f"Claims for verification saved to: {claims_path}")


if __name__ == '__main__':
    main()

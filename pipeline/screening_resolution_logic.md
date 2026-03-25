# DESAL SR/MA — Screening Resolution Logic v1.0

## Purpose
Pre-specified rules for resolving dual-LLM screening decisions. Both Claude and GPT-5.4 independently screen each citation. This document defines how their outputs are combined into a final screening decision.

## Decision Matrix

| Model A | Model B | Confidence Check | Resolution | Action |
|---------|---------|-----------------|------------|--------|
| INCLUDE | INCLUDE | Both ≥0.70 | Auto-include | Proceed to full-text screening |
| INCLUDE | INCLUDE | Either <0.70 | Human review | Low-confidence agreement flagged |
| EXCLUDE | EXCLUDE | Both ≥0.70 | Auto-exclude | Subject to 10% audit |
| EXCLUDE | EXCLUDE | Either <0.70 | Human review | Low-confidence agreement flagged |
| INCLUDE | EXCLUDE | Any | Human review | Classic disagreement |
| EXCLUDE | INCLUDE | Any | Human review | Classic disagreement |
| INCLUDE | UNCERTAIN | Any | Human review | Insufficient agreement |
| UNCERTAIN | INCLUDE | Any | Human review | Insufficient agreement |
| EXCLUDE | UNCERTAIN | Any | Human review | Insufficient agreement |
| UNCERTAIN | EXCLUDE | Any | Human review | Insufficient agreement |
| UNCERTAIN | UNCERTAIN | Any | Human review | Both models unsure |

## Confidence Threshold

- **Threshold: 0.70** (pre-specified, applied to both models)
- Auto-resolution requires BOTH models to have confidence ≥0.70
- If either model reports confidence <0.70, the decision is routed to human review regardless of agreement
- Rationale: 0.70 is an arbitrary but pre-specified threshold. The confidence score is the model's subjective self-assessment of certainty, not a calibrated probability. The distribution of confidence scores and the appropriateness of this threshold will be reported in the final manuscript as empirical data on LLM self-calibration.
- This threshold may be adjusted after a calibration batch (first 50 citations) if the confidence distributions make 0.70 uninformative. Any adjustment will be documented with rationale.

## Human Audit of Auto-Excludes

- **10% random sample** of all auto-excluded citations reviewed by the principal investigator (FGZ)
- Reviewer examines: title, abstract, both models' rationales and exclusion reason codes
- Purpose: estimate false-negative rate (missed eligible studies) and assess reliability of dual-LLM auto-exclusion

### Escalation Protocol
- If **≥2 missed eligible studies** found in any audit batch → escalate to 25% audit
- If further misses at 25% → escalate to 50%
- If further misses at 50% → escalate to 100% (full human review of all auto-excludes)
- Escalation decisions and counts documented in the PRISMA flow diagram

## Logging Requirements

Every screening decision is logged with the following fields:

```json
{
  "citation_id": "PMID_12345678",
  "model_a": {
    "model_name": "claude-opus-4-6",
    "decision": "include",
    "confidence": 0.85,
    "rationale": "...",
    "exclusion_reason": null,
    "pico_assessment": {...}
  },
  "model_b": {
    "model_name": "gpt-5.4",
    "decision": "include",
    "confidence": 0.90,
    "rationale": "...",
    "exclusion_reason": null,
    "pico_assessment": {...}
  },
  "resolution": {
    "method": "auto_include",
    "confidence_check_passed": true,
    "final_decision": "include",
    "human_reviewer": null,
    "human_override": null,
    "audit_selected": false,
    "timestamp": "2026-03-25T10:30:00Z"
  }
}
```

## Reporting Metrics

The following will be reported in the manuscript:

1. **Inter-model agreement:** Cohen's kappa (include/exclude/uncertain as 3 categories), percent agreement, and specific agreement for each category
2. **Confidence distributions:** Histograms of confidence scores per model, stratified by decision type
3. **Auto-resolution rate:** Proportion of citations auto-resolved vs. routed to human
4. **Audit results:** Number of auto-excludes audited, number of misses found, false-negative rate estimate with 95% CI
5. **Escalation events:** Whether the audit escalation protocol was triggered and at what stage
6. **Disagreement patterns:** Most common disagreement types (by PICO element and exclusion reason codes)
7. **Time comparison:** Time for dual-LLM screening vs. estimated time for traditional dual-human screening

## Version History
- v1.0 (2026-03-24): Initial pre-specified version, before data exposure

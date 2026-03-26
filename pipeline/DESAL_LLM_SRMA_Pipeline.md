# DESAL Systematic Review: Dual-LLM Screening and Extraction Pipeline — Methods and Technical Specification

**Version:** 1.0
**Date:** March 24, 2026
**Author:** Fernando G. Zampieri
**Project:** DESAL (Decongestion with Saline Loading)

---

## Context

This document describes the complete LLM-assisted pipeline for conducting a systematic review and meta-analysis (SR/MA) of hypertonic saline for acute decompensated heart failure (ADHF). The pipeline uses two LLMs — Claude (via Claude Code / Cowork) and GPT-5.4 (via Codex) — as independent reviewers, with the goal of reducing human burden while maintaining the rigor expected of a Cochrane-quality SR/MA.

The dual-LLM approach serves two purposes: (1) a practical tool for this specific SR/MA, and (2) a publishable methodological innovation demonstrating how LLM-assisted systematic reviews can be conducted with appropriate safeguards. The methodology itself may warrant a standalone methods paper.

The clinical protocol for this SR/MA, including PICO criteria, search strategy, and statistical analysis plan, is documented separately in `~/Desktop/DESAL/srma/DESAL_SRMA_Protocol.md`.

---

## 1. Search Phase

### 1.1 Databases and Search Strategies

Three databases are searched from inception to the search date. No study design filter is applied at the search stage — study design eligibility (RCTs only) is assessed during dual-LLM screening. This maximizes sensitivity and avoids losing relevant records to imperfect RCT filters.

Estimated yield: ~494 PubMed citations (tested March 2026), ~600-700 total after adding Embase and de-duplication.

**PubMed/MEDLINE:**

```
("saline solution, hypertonic"[MeSH Terms] OR "hypertonic saline"[tiab] OR "hypertonic sodium chloride"[tiab] OR "hypertonic saline solution"[tiab] OR "concentrated saline"[tiab] OR "small volume hypertonic"[tiab])
AND
("heart failure"[MeSH Terms] OR "heart failure"[tiab] OR "cardiac failure"[tiab] OR "decompensated heart failure"[tiab] OR "acute heart failure"[tiab] OR "congestive heart failure"[tiab] OR "ADHF"[tiab] OR "AHF"[tiab] OR "CHF"[tiab])
```

**Embase:**

```
('hypertonic saline'/exp OR 'hypertonic saline':ti,ab OR 'hypertonic sodium chloride':ti,ab OR 'hypertonic saline solution':ti,ab OR 'concentrated saline':ti,ab OR 'small volume hypertonic':ti,ab)
AND
('heart failure'/exp OR 'heart failure':ti,ab OR 'cardiac failure':ti,ab OR 'decompensated heart failure':ti,ab OR 'acute heart failure':ti,ab OR 'congestive heart failure':ti,ab OR 'ADHF':ti,ab OR 'AHF':ti,ab OR 'CHF':ti,ab)
```

**ClinicalTrials.gov:** Advanced Search with condition "heart failure" AND intervention "hypertonic saline", limited to interventional studies. This captures completed-but-unpublished trials.

Supplementary searches: reference lists of included studies and relevant SR/MAs; author contact for unpublished data.

### 1.2 Export and De-duplication

Records are exported in RIS or CSV format with the following minimum fields: title, abstract, authors, year, journal, DOI, PMID.

De-duplication is automated:

1. **Exact DOI match** — Remove duplicates sharing the same DOI across databases.
2. **Exact PMID match** — Remove duplicates sharing the same PMID.
3. **Fuzzy title matching** — For records lacking DOI/PMID, flag potential duplicates using normalized title similarity (Levenshtein distance ≤ 3 after lowercasing and removing punctuation). These are reviewed manually.

Output: a single deduplicated CSV file with one row per unique citation, ready for screening.

---

## 2. Screening Phase

**Status: Built.** Pre-specified before data exposure.

The screening phase replaces the traditional dual-human reviewer approach with dual-LLM screening, followed by targeted human review. Both models receive identical inputs and prompts; disagreements are escalated to human adjudication.

### 2.1 Title/Abstract Screening

Both Claude and GPT-5.4 independently screen each citation. They receive the same system prompt containing the PICO criteria:

**PICO Criteria:**

- **P:** Adults ≥18 years hospitalized with acute decompensated heart failure
- **I:** Intravenous hypertonic saline (>0.9% NaCl) co-administered with loop diuretics
- **C:** Loop diuretics alone ± isotonic saline or placebo (no hypertonic saline)
- **O:** All-cause mortality, length of stay, readmission, renal function, diuretic response, safety events
- **Study type:** Randomized controlled trials only

Each model outputs structured JSON per citation:

```json
{
  "pmid": "12345678",
  "decision": "include | exclude | uncertain",
  "confidence": 0.0-1.0,
  "rationale": "Brief explanation of decision",
  "pico_match": {
    "population": true,
    "intervention": true,
    "comparator": true,
    "outcome": true,
    "study_type": true
  }
}
```

The `pico_match` object provides transparency into which criteria drove the decision. A citation that fails on `study_type` (not an RCT) vs. `intervention` (no hypertonic saline) generates different rationales, which matters for auditing systematic errors.

### 2.2 Resolution Logic

| Model A (Claude) | Model B (GPT-5.4) | Resolution |
|---|---|---|
| INCLUDE | INCLUDE | Auto-include |
| EXCLUDE | EXCLUDE | Auto-exclude (subject to 10% audit) |
| INCLUDE | EXCLUDE | → Human review |
| EXCLUDE | INCLUDE | → Human review |
| UNCERTAIN | Any | → Human review |
| Any | UNCERTAIN | → Human review |

This is conservative by design. The only citations that bypass human eyes entirely are those where both models agree to include (low risk — erring on the side of inclusion) or both agree to exclude (audited at 10%, see Section 2.3).

### 2.3 Human Audit of Auto-Excludes

A 10% random sample of auto-excluded citations (both models said EXCLUDE) is reviewed by a human reviewer (Fernando). This serves three purposes:

1. **Calculate sensitivity/specificity** of the dual-LLM screening against the human gold standard on this subset.
2. **Detect systematic blind spots** where both models agree incorrectly — e.g., consistently excluding non-English studies, or missing studies that use uncommon terminology for hypertonic saline.
3. **Calibrate confidence** — if the 10% audit reveals any missed eligible studies, expand to 20% or full human review of auto-excludes.

Sampling is simple random (not stratified) since all citations come from the same auto-exclude pool. The audit sample size depends on the total number of auto-excludes; with the expected yield of ~200-500 citations total, a 10% audit means reviewing ~15-40 citations manually, which is feasible.

### 2.4 Full-Text Screening

Citations classified as INCLUDE or UNCERTAIN after title/abstract screening advance to full-text review. The same dual-LLM approach is applied:

1. Full-text PDFs are converted to text using `pdftotext`.
2. Both models receive the extracted text + the same PICO prompt (expanded to include additional exclusion criteria).
3. Same resolution logic from Section 2.2 applies.

**Additional exclusion criteria checked at full-text stage:**

- Not hospitalized acute heart failure (e.g., chronic outpatient HF)
- Not a randomized controlled trial (e.g., quasi-randomized, observational)
- No hypertonic saline intervention (>0.9% NaCl)
- Duplicate publication of same trial data
- Conference abstract only without sufficient data for extraction
- Pediatric population

### 2.5 Reporting Metrics

The following metrics are reported for the screening phase:

**Inter-model agreement:**

- Cohen's kappa for the binary include/exclude decision (treating UNCERTAIN as a separate category, or collapsing UNCERTAIN into INCLUDE for a more conservative estimate)
- Proportion of citations where both models agreed vs. disagreed
- Distribution of disagreement types (which model was more liberal/conservative)

**Accuracy vs. human audit:**

- Sensitivity: proportion of truly eligible studies correctly auto-included by both models
- Specificity: proportion of truly ineligible studies correctly auto-excluded by both models
- False negative rate from the 10% audit (missed eligible studies)

**PRISMA flow diagram:**

The standard PRISMA 2020 flow diagram is annotated with LLM-specific information:

- Number of citations screened by each model
- Number auto-resolved (both agree) vs. escalated to human
- Number from the 10% audit that changed classification
- Final included/excluded counts with reasons

**Efficiency comparison:**

- Total screening time (wall clock) for dual-LLM vs. estimated time for traditional dual-human screening
- Cost per citation (API costs)
- Human time spent (disagreement resolution + 10% audit only)

---

## 3. Extraction Phase

The extraction phase combines the existing `clinical-data-extractor` skill (a multi-layer verification system already built and tested) with new orchestration components that coordinate dual-model extraction and automated disagreement resolution.

### 3.1 Existing Skill: clinical-data-extractor

**Location:** `~/Desktop/DESAL/clinical-data-extractor/`
**Status:** Built and tested on 6S, 3CPO, and ANIST trials.

The skill implements four verification layers, each targeting different failure modes of LLM-generated numerical claims:

**Layer 1: Anchor-Based Extraction (`anchor_extract.py`)**

Constrains extraction upfront rather than filtering afterward. Numbers are only extracted when they appear within a character window (250-600 chars) of semantically relevant anchor terms. For example, mortality anchors include "mortality", "death(s)", "died", "survival", "fatal" — so the number "62" from "SAPS II 51 (39-62)" is never extracted when looking for mortality data.

This is the inverse of traditional extraction: instead of extracting all numbers and then verifying, it only pulls numbers that appear in the right context.

**Layer 2: Text Verification (`verify_numbers.py`)**

Checks whether claimed numbers actually exist in the source text. Catches completely invented numbers, transposed digits, and wrong units. Output categories:

- ✓ VERIFIED: Number found in source text
- ✗ UNVERIFIED: Number not found (likely fabrication)
- ⚠️ CITATION_ONLY: Found only in reference section (suspicious)

**Layer 3: Table Verification (`verify_with_tables.py`)**

The most important layer for human-aided review. Extracts tables from PDFs (using `extract_tables.py` with camelot-py and pdfplumber as fallback), then shows WHERE each number appears in context. This enables rapid human verification (~5 seconds per claim):

```
✓ '62' found at:
    → Page 3: "SAPS II 51 (39-62)"     ← Obviously not mortality!
```

This catches semantic mismatches where a number exists in the paper but in the wrong context — the hardest type of error for automated systems to detect.

**Layer 4: Benford's Law Check (`benford_check.py`)**

For large extraction datasets (50+ numbers), checks whether the distribution of leading digits follows Benford's Law. Natural data has ~30% leading 1s and ~5% leading 9s; fabricated "random" numbers cluster in middle digits (4-7). Catches systematic fabrication but not individual errors.

**Measured Detection Rates:**

| Method | Auto-Caught | Flagged for Review | With Human Review |
|---|---|---|---|
| Text verification only (v1) | 33% | 0% | 33% |
| Text + context display (v2) | 50% | 17% | 100% |
| Tables + context display | 50% | 17% | 100% |

Key finding: context display enables 100% detection with human review, at ~5 seconds per flagged claim.

### 3.2 Pydantic Extraction Schema

**Status: Built.** Pre-specified before data exposure.
**Location:** `~/Desktop/DESAL/extraction/schema/study_extraction.py`

A structured schema that both models must output into. Using Pydantic v2 enforces type validation, required fields, and consistent formatting across extractors. The schema captures all variables from the protocol's Appendix B data extraction form.

**Architecture:** The schema uses nested Pydantic models rather than flat fields. This reduces field duplication (e.g., arm-level characteristics are defined once in `ArmCharacteristics` and instantiated for intervention and control arms) and groups outcome data into reusable structures (`BinaryOutcome`, `ContinuousOutcome`).

**Enums** constrain categorical fields to valid values:

- `RoBJudgment` — "Low", "Some concerns", "High" (RoB 2.0 domains)
- `LOSMeasure` — "mean_sd", "median_iqr"
- `StudyDesign` — "parallel", "crossover", "factorial", "cluster"
- `ComparatorFluid` — "none", "normal_saline", "dextrose", "placebo", "other"

**Nested models:**

- `ArmCharacteristics` — Baseline characteristics for one study arm: demographics (age, sex), cardiac (EF, NYHA, etiology), labs (sodium, creatinine, eGFR, BNP, chloride with units/SDs), and baseline medications (diuretic dose, SGLT2i, ACEi/ARB/ARNI, beta-blocker, MRA as percentages). Includes a `@field_validator` that enforces 0–100 range on all percentage fields.
- `BinaryOutcome` — Events and denominators per arm plus timepoint (e.g., mortality, readmission, hypernatremia, AKI, troponin elevation).
- `ContinuousOutcome` — Value/SD per arm, plus `measure_type` ("mean_sd" or "median_iqr"), IQR bounds (Q1/Q3) for median-reported data, timepoint, and unit. Used for LOS, creatinine change, sodium change, chloride change, urine output, natriuresis, weight change, net fluid balance, and BNP change.

**Top-level `StudyExtraction` field groups:**

1. **Study identification** — study_id, PMID, DOI, author, year, title, journal, country, single_center, study_design (enum), registration_number, funding_source
2. **Sample sizes** — total, intervention, control, plus analyzed_intervention/control (if ITT ≠ randomized)
3. **Intervention details** — HSS concentration (with variable-concentration flag and range for Palermo protocol), volume, frequency, duration, infusion time, loop diuretic (drug, dose, frequency, route), co-interventions
4. **Comparator details** — comparator_fluid (enum), fluid detail, diuretic drug/dose/route, co-interventions
5. **Trial eligibility criteria** — age bounds, EF requirement, sodium requirement, renal threshold, time window, HF diagnosis method, NYHA requirement, exclusion flags (cardiogenic shock, dialysis, mechanical support), SGLT2i policy, diuretic resistance required/definition, minimum prior diuretic dose, other exclusions
6. **Population/setting flags** — is_ambulatory, is_crossover, first_period_data_available, overlapping_cohort_flag, companion_publications
7. **Baseline characteristics** — `intervention_arm: ArmCharacteristics`, `control_arm: ArmCharacteristics`
8. **Outcomes** — Each is an Optional nested model: mortality (`BinaryOutcome`), los (`ContinuousOutcome`), readmission (`BinaryOutcome`), creatinine_change, sodium_change, peak_sodium, chloride_change, urine_output_24h, natriuresis_24h, weight_change, net_fluid_balance, bnp_change (all `ContinuousOutcome`), hypernatremia, aki, troponin_elevation (all `BinaryOutcome`)
9. **Risk of Bias** — Six RoB 2.0 domains plus overall, each typed as `Optional[RoBJudgment]`
10. **Classification flags** — palermo_group (bool, critical for key subgroup), blinding, follow_up_duration
11. **Extraction metadata** — confidence_notes, extraction_source

**Batch container:** `ExtractionBatch` wraps a list of `StudyExtraction` objects with model_name, extraction_date, and schema_version — used by the orchestrator to serialize each model's full extraction run.

**JSON schema export:** `export_json_schema()` generates a JSON Schema from the Pydantic model, which is passed to both LLMs as part of the extraction prompt to ensure output conformance.

The `palermo_group` flag is critical for the key subgroup analysis. Trial eligibility criteria are collected to assess GRADE indirectness and explain heterogeneity. Sodium and chloride values are critical given the intervention mechanism and the trial's sodium-based stratification.

### 3.3 Cross-Model Orchestration

**Status: Built.** Pre-specified before data exposure.
**Location:** `~/Desktop/DESAL/extraction/scripts/orchestrate_extraction.py`

This is the core pipeline that coordinates dual-model extraction with multi-layer verification. For each included study:

```
Step 1: PDF → text extraction (pdftotext) + table extraction (extract_tables.py)
        ↓
Step 2: Model A (Claude) extracts into Pydantic schema
        ↓
Step 3: Run existing skill verification (Layers 1-3) on Model A output
        ↓
Step 4: Model B (GPT-5.4 via Codex) extracts into same Pydantic schema
        ↓
Step 5: Run existing skill verification (Layers 1-3) on Model B output
        ↓
Step 6: Cell-by-cell comparison of Model A vs. Model B outputs
        ↓
Step 7: Disagreement classification (Section 3.4)
        ↓
Step 8: LLM auditor triages discrepancies (Section 3.5)
        ↓
Step 9: Human reviews remaining conflicts
```

Steps 2-3 and 4-5 can run in parallel since the two models are independent. Step 6 onward is sequential.

The orchestration script manages the full pipeline for a batch of studies, tracks status per study, and produces a summary report of extraction quality metrics.

### 3.4 Disagreement Classifier

**Status: Built.** Pre-specified before data exposure.
**Location:** `~/Desktop/DESAL/extraction/scripts/compare_extractions.py`

After both models extract data for a study, each cell (field) is compared and classified into one of six disagreement levels:

| Level | Name | Definition | Example |
|---|---|---|---|
| 0 | Perfect agreement | Same value, both verified by skill | Both say mortality = 15/108 |
| 1 | Trivial difference | Rounding, units, formatting | 3.2 vs. 3.20, or "mg" vs. "milligrams" |
| 2 | Minor difference | Close values, likely from different table/text locations | Mean age 62.3 vs. 63.1 |
| 3 | Moderate difference | Different values, one verified and one not, or both verified from different contexts | LOS 8.5 vs. 9.2, one from abstract, one from table |
| 4 | Major difference | Contradictory values, both models confident | Mortality 15% vs. 23% |
| 5 | Structural disagreement | One model found data the other said was not reported | Model A: readmission = 12/54; Model B: "not reported" |

**Resolution rules:**

| Level | Action |
|---|---|
| 0-1 | Auto-accept. Use the verified value (Level 0) or the more precise value (Level 1). |
| 2 | Accept if both verified by skill. Flag for human review if only one verified. |
| 3-5 | Route to LLM auditor (Section 3.5). If auditor confidence < 0.8, route to human review with full context from both models + verification layers. |

The classifier is deterministic — it compares values numerically (with configurable tolerance for Level 1-2 boundaries) and checks verification status from the skill output.

### 3.5 LLM Auditor Layer

**Status: Built.** Pre-specified before data exposure.
**Location:** `~/Desktop/DESAL/extraction/scripts/llm_auditor.py`

A third LLM call (using either Claude or GPT-5.4, alternating to avoid self-bias) that serves as an automated triage step before human review. The auditor receives:

- The original source text and extracted tables
- Both models' extractions for the disputed field(s)
- The verification results from the clinical-data-extractor skill (Layers 1-3)
- The disagreement classification level

The auditor outputs:

```json
{
  "field": "mortality_intervention",
  "model_a_value": 15,
  "model_b_value": 23,
  "recommended_value": 15,
  "recommendation_source": "Table 2, page 5",
  "confidence": 0.95,
  "rationale": "Model A value matches Table 2 exactly. Model B appears to have extracted from the combined mortality endpoint in the discussion.",
  "human_review_needed": false
}
```

The auditor partially replaces the human in the Layer 3 loop. It triages which discrepancies genuinely need expert judgment (ambiguous source data, genuinely conflicting reports in the paper) vs. which are resolvable by careful re-reading of the source.

Expected outcome: the auditor resolves ~60-70% of Level 2-3 disagreements automatically, reducing human review to Level 4-5 disagreements and low-confidence auditor outputs.

---

## 4. Analysis Phase

All analysis code will be written in R and made publicly available.

### 4.1 Meta-Analysis

**R packages:** `meta`, `metafor`

**Model:** Random-effects with restricted maximum likelihood (REML) estimator for tau-squared.

**Effect measures:**

- Dichotomous outcomes (mortality, readmission, hypernatremia, AKI): Risk Ratios (RR) with 95% CI
- Continuous outcomes (LOS, weight change, urine output, creatinine change, sodium change, BNP change): Mean Differences (MD) with 95% CI

Where studies report medians and IQRs, means and SDs will be estimated using validated methods (Wan et al., 2014; Luo et al., 2018).

**Heterogeneity:** Cochran's Q test (p < 0.10), I² statistic, prediction intervals.

**Small-study effects:** Funnel plots + Egger's regression test if ≥10 studies for an outcome.

**Outputs:** Forest plots, funnel plots per outcome.

### 4.2 Trial Sequential Analysis

**Status: Built.** Pre-specified before data exposure.
**Location:** `~/Desktop/DESAL/analysis/R/tsa.R`

TSA is implemented in custom R code, not the Copenhagen TSA software. This is intentional — custom code allows full transparency, reproducibility, and integration with the meta-analysis pipeline.

**Parameters:**

- Alpha spending function: O'Brien-Fleming boundaries
- Type I error: 5% (two-sided)
- Type II error: 20% (power = 80%)
- Relative risk reduction: derived from the pooled random-effects estimate
- Control event rate: pooled from control arms of included studies
- Heterogeneity adjustment: D² from the meta-analysis

**Interpretation:**

- If cumulative Z-curve crosses the TSA monitoring boundary → evidence is conclusive
- If it does not → evidence is inconclusive; the gap between current information size and the required information size (RIS) directly informs DESAL sample size planning

### 4.3 Subgroup and Sensitivity Analyses

**Pre-specified subgroup analyses (at least 2 studies per subgroup required):**

1. HSS concentration: ≤3% vs. >3%
2. Dosing frequency: single dose vs. repeated doses
3. Baseline serum sodium: ≤135 mEq/L vs. >135 mEq/L
4. Heart failure phenotype: HFrEF (EF ≤40%) vs. HFpEF (EF >40%)
5. Risk of bias: low vs. some concerns/high (per RoB 2 overall judgment)
6. **Research group: Paterna/Tuttolomondo (Palermo) vs. independent groups** — This is the key sensitivity analysis, given that the majority of published evidence comes from a single research group.
7. **Diuretic-resistant populations vs. unselected ADHF populations** — based on whether the trial's inclusion criteria required demonstrated diuretic resistance (e.g., minimum prior diuretic dose, documented inadequate response) or enrolled any hospitalized ADHF patient regardless of diuretic response

Interaction tests will be reported for each subgroup analysis.

**Pre-specified sensitivity analyses:**

1. Excluding all Paterna/Tuttolomondo group studies
2. Excluding high risk of bias studies
3. Fixed-effect model (inverse-variance) as alternative to random-effects
4. Leave-one-out analysis
5. Broadened population (including ambulatory worsening HF trials)
6. Excluding crossover trials (or studies with combined crossover data only)
7. Treatment-arm continuity correction (TACC) for binary outcomes
8. Alternative outcome timepoints for physiological outcomes

### 4.4 GRADE Assessment

Certainty of evidence assessed per outcome using the GRADE framework. RCT evidence starts at high certainty and is downgraded across five domains:

1. **Risk of bias** — informed by RoB 2.0 assessments
2. **Inconsistency** — informed by I², prediction intervals, subgroup analyses
3. **Indirectness** — population, intervention, comparator, outcome directness
4. **Imprecision** — width of confidence intervals, whether the interval crosses clinically meaningful thresholds
5. **Publication bias** — funnel plot asymmetry, Egger's test, whether most evidence comes from a single group

Results presented in a Summary of Findings table.

---

## 5. Build Status

| Component | Status | Location |
|---|---|---|
| clinical-data-extractor skill (Layers 1-4) | ✅ Built | `~/Desktop/DESAL/clinical-data-extractor/` |
| PubMed search strategy | ✅ In protocol | `~/Desktop/DESAL/srma/DESAL_SRMA_Protocol.md` |
| SR/MA protocol (PRISMA-P) | ✅ Written | `~/Desktop/DESAL/srma/DESAL_SRMA_Protocol.md` |
| Screening prompt templates | ✅ Built | `~/Desktop/DESAL/pipeline/screening_prompt_template.md` |
| Screening orchestration script | ✅ Built | `~/Desktop/DESAL/pipeline/screening_orchestrator.py` |
| Screening resolution logic | ✅ Built | `~/Desktop/DESAL/pipeline/screening_resolution_logic.md` |
| Pydantic extraction schema | ✅ Built | `~/Desktop/DESAL/extraction/schema/study_extraction.py` |
| Cross-model orchestration | ✅ Built | `~/Desktop/DESAL/extraction/scripts/orchestrate_extraction.py` |
| Disagreement classifier (Levels 0-5) | ✅ Built | `~/Desktop/DESAL/extraction/scripts/compare_extractions.py` |
| LLM auditor layer | ✅ Built | `~/Desktop/DESAL/extraction/scripts/llm_auditor.py` |
| Data preparation (JSON → CSV) | ✅ Built | `~/Desktop/DESAL/analysis/R/prepare_data.R` |
| Meta-analysis R scripts | ✅ Built | `~/Desktop/DESAL/analysis/R/meta_analysis.R` |
| TSA R implementation | ✅ Built | `~/Desktop/DESAL/analysis/R/tsa.R` |

All pipeline components are now pre-specified and coded before data exposure. The git history serves as evidence of pre-specification.

---

## 6. Reporting the Methodology

### 6.1 For the SR/MA Paper

The methods section of the published SR/MA should describe:

- The dual-LLM screening approach, framed as a methodological innovation with transparency about its experimental nature
- Inter-model agreement statistics (Cohen's kappa, proportion of auto-resolved vs. human-reviewed citations)
- Sensitivity and specificity of dual-LLM screening from the 10% human audit of auto-excludes
- The multi-layer verification pipeline (4 layers) and its measured detection rates
- How extraction disagreements were classified (Levels 0-5) and resolved (auto-accept, auditor, human)
- Time and cost comparison vs. traditional dual-human approach

### 6.2 Potential Standalone Methods Paper

The LLM-assisted SR/MA methodology is independently publishable. A methods paper would cover:

- Rationale for dual-LLM over single-LLM with human
- The screening protocol with resolution logic
- The extraction pipeline with multi-layer verification
- The disagreement classification system
- Empirical results: agreement rates, error types caught, time savings
- Comparison with existing tools (e.g., ASReview, Rayyan AI features)

### 6.3 Limitations to Acknowledge

- **Correlated errors between LLMs:** Both models share training data and may have similar blind spots. The 10% audit partially addresses this but cannot fully eliminate the risk.
- **Model version dependency:** Results are specific to Claude and GPT-5.4 as of the study date. Different model versions may produce different results. Exact model versions and API parameters must be reported.
- **Reproducibility:** LLM outputs are stochastic. Temperature settings, system prompts, and random seeds (where available) must be documented. Running the same pipeline twice may yield slightly different screening decisions.
- **Cost and access:** Requires API access to two commercial LLMs, which limits accessibility compared to free tools.
- **Validation scope:** The 10% audit of auto-excludes provides a point estimate of screening accuracy but has limited statistical power to detect rare systematic errors.
- **Not a replacement for domain expertise:** The LLM auditor and disagreement classifier reduce but do not eliminate the need for human judgment, particularly for ambiguous source data and clinical context.

---

## Appendix A: Dependencies

### Python

```
pydantic>=2.0
camelot-py[cv]
pdfplumber
poppler-utils (system package for pdftotext)
ghostscript (system package for camelot)
```

### R

```
meta
metafor
dplyr
ggplot2
readr
```

### External APIs

- Claude API (Anthropic) — for Model A extraction and screening
- GPT-5.4 API (OpenAI / Codex) — for Model B extraction and screening

---

## Appendix B: File Structure

```
~/Desktop/DESAL/
├── CLAUDE.md                            # Project context (for Claude Code)
├── AGENTS.md                            # Project context (for Codex)
├── srma/
│   ├── DESAL_SRMA_Protocol.md           # SR/MA protocol (PRISMA-P)
│   └── HTS_AHF_Literature_Review.md     # Literature search summary
├── pipeline/
│   ├── DESAL_LLM_SRMA_Pipeline.md       # This document
│   ├── screening_prompt_template.md     # Pre-specified screening prompt (v1.0, locked)
│   ├── screening_resolution_logic.md    # Dual-LLM resolution rules
│   ├── screening_orchestrator.py        # Screening pipeline script
│   └── screening_README.md              # Screening usage instructions
├── trial/
│   ├── DESAL_Trial_Synopsis.md / .pdf   # Trial synopsis
│   ├── desal_power_analysis.py          # Power simulation script
│   ├── desal_power_curves.png           # Power curves figure
│   ├── desal_power_results.csv          # Simulation results
│   ├── win_ratio_sample_size.R / .py    # Formula-based sample size
│   └── win_ratio_sample_sizes.csv       # Formula-based results
├── clinical-data-extractor/             # Multi-layer verification skill
│   ├── SKILL.md
│   └── scripts/
│       ├── anchor_extract.py            # Layer 1: Anchor-based extraction
│       ├── verify_numbers.py            # Layer 2: Text verification
│       ├── verify_with_tables.py        # Layer 3: Table verification
│       ├── benford_check.py             # Layer 4: Benford's law check
│       ├── extract_tables.py            # PDF table extraction
│       └── run_tests.py                 # Test suite
├── extraction/
│   ├── schema/
│   │   ├── __init__.py
│   │   └── study_extraction.py          # Pydantic schema (77 fields)
│   ├── scripts/
│   │   ├── orchestrate_extraction.py    # Dual-LLM extraction orchestrator
│   │   ├── compare_extractions.py       # Disagreement classifier (L0-5)
│   │   └── llm_auditor.py              # LLM auditor triage layer
│   ├── pdfs/                            # Included study PDFs (to populate)
│   ├── extracted_text/                  # pdftotext outputs (generated)
│   ├── extracted_tables/                # Table JSONs (generated)
│   └── data/                            # Extraction outputs (generated)
│       ├── extraction_log.json
│       ├── claude_extractions.json
│       ├── gpt_extractions.json
│       ├── disagreements.json
│       ├── auditor_queue.json
│       ├── auditor_report.json
│       ├── human_review_extraction.json
│       └── final_extractions.json
├── analysis/
│   ├── R/
│   │   ├── prepare_data.R               # JSON → analysis-ready CSV
│   │   ├── meta_analysis.R              # Random-effects MA + subgroups
│   │   └── tsa.R                        # Custom trial sequential analysis
│   ├── data/
│   │   └── analysis_ready.csv           # (generated by prepare_data.R)
│   └── output/
│       ├── forest_plots/                # Forest plot PDFs (generated)
│       ├── funnel_plots/                # Funnel plot PDFs (generated)
│       ├── tsa_plots/                   # TSA plots (generated)
│       └── meta_analysis_summary.csv    # (generated)
└── reporting/                           # (future: PRISMA, GRADE tables)
```

# DESAL Trial Design

## Overview

DESAL (Decongestion with Saline Loading) is a pragmatic, open-label, multicentre, randomized controlled trial of hypertonic saline for acute heart failure. The SR/MA in this repository was designed to inform this trial — specifically, the trial sequential analysis determines whether the existing evidence is sufficient or whether a new trial is needed, and the pooled estimates inform DESAL's sample size assumptions.

The trial design documents are in the `trial/` folder (not tracked in git).

## Trial Synopsis

| Element | Description |
|---|---|
| **Design** | Pragmatic, open-label, multicentre, parallel-group, 1:1 RCT |
| **Population** | Adults ≥18 years hospitalized or in ED with acute heart failure, elevated BNP/NT-proBNP, planned IV loop diuretics; multicentre across Canada |
| **Intervention** | 250 mL of 3% NaCl IV over 30-60 min + standard of care; up to 3 doses q6h within first 24 hours |
| **Control** | Standard of care alone (open-label, no placebo) |
| **Stratification** | Baseline serum sodium (≤135 vs >135 mEq/L) |
| **Primary endpoint** | Day 14 hierarchical win ratio — Tier 1: all-cause mortality; Tier 2: days alive and out of hospital |
| **Sample size** | ~900 (450/arm); 80% power for WR 1.27 (~1-day LOS reduction) |
| **Analysis** | Frequentist, stratified Mann-Whitney, two-sided α = 0.05, mITT |
| **PIs** | Fernando G. Zampieri, Justin Ezekowitz |

## Key Inclusion/Exclusion Criteria

**Inclusion:** Age ≥18, hospitalized/ED with primary diagnosis of ADHF, elevated natriuretic peptide (locally determined threshold), planned IV loop diuretics.

**Exclusion:** Na >145 mEq/L, eGFR <15 or dialysis, expected RRT within 48h, cardiogenic shock requiring vasopressors/MCS, allergy to HSS, anticipated discharge within 24h, unable to consent.

## Endpoints

**Primary:** Day 14 hierarchical win ratio (Tier 1: all-cause death, Tier 2: days alive out of hospital; any readmission counts as in-hospital days).

**Key secondary:** Total furosemide dose (IV equivalent), index LOS, creatinine change (baseline to 72h), weight change (baseline to 72h), 30-day all-cause mortality, 30-day all-cause readmission, net fluid balance at 48h, BNP/NT-proBNP change (baseline to 72h).

**Safety:** Hypernatremia (Na >145), AKI (KDIGO criteria), symptomatic hypernatremia, serious adverse events.

## Pre-Specified Subgroups

1. HFpEF vs HFrEF (EF ≥50% vs <50%)
2. Baseline sodium stratum (≤135 vs >135 mEq/L)
3. Baseline eGFR (≥30 vs <30 mL/min/1.73m²)
4. SGLT2 inhibitor use at baseline (yes/no)

## Sample Size Rationale

The sample size assumes a **conservative** 1.0-day LOS reduction (WR ~1.27), which is approximately one-third of the pooled estimates from existing meta-analyses (Eng et al. 2021: 3.3 days; Diaz-Arocutipa et al. 2023: 3.6 days). This discounting accounts for the likely inflation in the existing literature, which is dominated by the Paterna/Tuttolomondo group's single-center studies.

**Simulation parameters:** Control median LOS 7 days (log-normal, σ = 0.7), Day 14 mortality 4.5%, readmission rate 10%, integer-day measurement, 2000 iterations per scenario. At N = 900, power is ~80% for WR 1.27 and >95% for WR 1.40 (1.5-day reduction).

## Connection to SR/MA

The SR/MA directly informs the trial in several ways:

1. **TSA determines trial necessity** — if the cumulative Z-curve crosses the monitoring boundary, existing evidence may be sufficient and the trial may not be needed. If inconclusive, the gap between current information size and the required information size informs DESAL's sample size.
2. **Pooled effect estimates** — the meta-analytic LOS reduction (discounted for Palermo-group inflation) underpins the sample size calculation.
3. **Subgroup signals** — SR/MA subgroup analyses (HFrEF vs HFpEF, hyponatremic vs normonatremic, diuretic-resistant vs unselected) inform DESAL's subgroup pre-specification.
4. **Safety profile** — pooled hypernatremia and AKI rates inform the safety monitoring plan.
5. **Intervention parameters** — the literature review of HSS concentration (1.4-10% NaCl), volume (50-150 mL), frequency (single to BID), and duration informed DESAL's choice of 3% NaCl, 250 mL, up to 3 doses within 24h.

## Statistical Methodology Notes

- **Win ratio:** Fernando is familiar with R packages (WWR, WRestimate) and the Dong et al. 2020 variance formula.
- **No Health Canada submission** — minimal-risk pragmatic trial.
- **Platform trial context** — DESAL is the flagship trial for the AHF state of a broader HF platform trial infrastructure (two states: AHF and outpatient).

## Files in `trial/` (Local Only)

| File | Description |
|---|---|
| `DESAL_Trial_Synopsis.md` / `.pdf` | Full trial synopsis with power curves figure |
| `desal_power_analysis.py` | Python simulation script (2000 iterations per scenario) |
| `desal_power_curves.png` | Simulation-based power curves across sample sizes and effect sizes |
| `desal_power_results.csv` | Full simulation results (all scenarios) |
| `win_ratio_sample_size.R` | Formula-based sample size calculator (Dong et al. 2020) |
| `win_ratio_sample_size.py` | Same calculator in Python |
| `win_ratio_sample_sizes.csv` | Formula-based results across WR/tie scenarios |

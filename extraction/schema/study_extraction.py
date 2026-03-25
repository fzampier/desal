"""
DESAL Systematic Review — Pydantic Extraction Schema v1.0

Pre-specified data extraction schema for dual-LLM extraction pipeline.
All fields match the SR/MA protocol Appendix B and pipeline doc Section 3.2.

Both Claude and GPT-5.4 must output JSON conforming to this schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RoBJudgment(str, Enum):
    """Cochrane Risk of Bias 2.0 domain judgment."""
    LOW = "Low"
    SOME_CONCERNS = "Some concerns"
    HIGH = "High"


class LOSMeasure(str, Enum):
    """How length of stay was reported."""
    MEAN_SD = "mean_sd"
    MEDIAN_IQR = "median_iqr"


class StudyDesign(str, Enum):
    """RCT design type."""
    PARALLEL = "parallel"
    CROSSOVER = "crossover"
    FACTORIAL = "factorial"
    CLUSTER = "cluster"


class ComparatorFluid(str, Enum):
    """Fluid given in comparator arm."""
    NONE = "none"
    NORMAL_SALINE = "normal_saline"
    DEXTROSE = "dextrose"
    PLACEBO = "placebo"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Arm-level patient characteristics
# ---------------------------------------------------------------------------

class ArmCharacteristics(BaseModel):
    """Baseline characteristics for one study arm."""

    n: int = Field(description="Number of patients in this arm")

    # Demographics
    mean_age: Optional[float] = Field(
        default=None, description="Mean or median age (years)"
    )
    sd_age: Optional[float] = Field(
        default=None, description="SD or IQR for age"
    )
    age_reported_as: Optional[str] = Field(
        default=None, description="'mean_sd' or 'median_iqr'"
    )
    percent_female: Optional[float] = Field(
        default=None, description="Percentage female (0-100)"
    )

    # Cardiac
    mean_ef: Optional[float] = Field(
        default=None, description="Mean/median LVEF (%)"
    )
    sd_ef: Optional[float] = None
    nyha_class_distribution: Optional[Dict[str, float]] = Field(
        default=None,
        description="e.g., {'II': 0.15, 'III': 0.60, 'IV': 0.25}",
    )
    hf_etiology: Optional[str] = Field(
        default=None, description="Ischemic vs non-ischemic distribution"
    )

    # Labs
    baseline_sodium: Optional[float] = Field(
        default=None, description="Baseline serum sodium (mEq/L)"
    )
    sd_sodium: Optional[float] = None
    baseline_creatinine: Optional[float] = Field(
        default=None, description="Baseline serum creatinine (mg/dL or µmol/L)"
    )
    sd_creatinine: Optional[float] = None
    creatinine_unit: Optional[str] = Field(
        default=None, description="'mg/dL' or 'µmol/L'"
    )
    baseline_egfr: Optional[float] = Field(
        default=None, description="Baseline eGFR (mL/min/1.73m²)"
    )
    sd_egfr: Optional[float] = None
    baseline_bnp: Optional[float] = Field(
        default=None, description="Baseline BNP or NT-proBNP (pg/mL)"
    )
    sd_bnp: Optional[float] = None
    bnp_type: Optional[str] = Field(
        default=None, description="'BNP' or 'NT-proBNP'"
    )
    baseline_chloride: Optional[float] = Field(
        default=None, description="Baseline serum chloride (mEq/L)"
    )
    sd_chloride: Optional[float] = None

    # Medications
    baseline_diuretic_dose_mg: Optional[float] = Field(
        default=None,
        description="Baseline oral loop diuretic dose (furosemide equivalents, mg/day)",
    )
    sglt2i_use_percent: Optional[float] = Field(
        default=None, description="Percentage on SGLT2 inhibitor at baseline"
    )
    acei_arb_arni_percent: Optional[float] = Field(
        default=None, description="Percentage on ACEi/ARB/ARNI at baseline"
    )
    beta_blocker_percent: Optional[float] = Field(
        default=None, description="Percentage on beta-blocker at baseline"
    )
    mra_percent: Optional[float] = Field(
        default=None, description="Percentage on MRA at baseline"
    )

    @field_validator("percent_female", "sglt2i_use_percent",
                     "acei_arb_arni_percent", "beta_blocker_percent",
                     "mra_percent")
    @classmethod
    def validate_percentage(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 100):
            raise ValueError(f"Percentage must be 0-100, got {v}")
        return v


# ---------------------------------------------------------------------------
# Outcome data structures
# ---------------------------------------------------------------------------

class BinaryOutcome(BaseModel):
    """Event count / denominator for a binary outcome."""
    events_intervention: Optional[int] = None
    n_intervention: Optional[int] = None
    events_control: Optional[int] = None
    n_control: Optional[int] = None
    timepoint: Optional[str] = Field(
        default=None, description="e.g., 'in-hospital', '30-day', '6-month'"
    )


class ContinuousOutcome(BaseModel):
    """Summary statistics for a continuous outcome."""
    value_intervention: Optional[float] = None
    sd_intervention: Optional[float] = None
    value_control: Optional[float] = None
    sd_control: Optional[float] = None
    measure_type: Optional[str] = Field(
        default=None, description="'mean_sd' or 'median_iqr'"
    )
    iqr_low_intervention: Optional[float] = Field(
        default=None, description="Q1 if median_iqr"
    )
    iqr_high_intervention: Optional[float] = Field(
        default=None, description="Q3 if median_iqr"
    )
    iqr_low_control: Optional[float] = None
    iqr_high_control: Optional[float] = None
    timepoint: Optional[str] = None
    unit: Optional[str] = None


# ---------------------------------------------------------------------------
# Main extraction schema
# ---------------------------------------------------------------------------

class StudyExtraction(BaseModel):
    """
    Complete data extraction for one included RCT.

    Every field is typed and documented. Optional fields accommodate studies
    that do not report all outcomes. The palermo_group flag is critical for
    the key subgroup/sensitivity analysis.
    """

    # ------------------------------------------------------------------
    # Study identification
    # ------------------------------------------------------------------
    study_id: str = Field(
        description="first_author_year format, e.g., 'Paterna_2000'"
    )
    pmid: Optional[str] = Field(default=None, description="PubMed ID")
    doi: Optional[str] = None
    author: str = Field(description="First author surname")
    year: int
    title: str
    journal: str
    country: str
    single_center: bool
    study_design: StudyDesign = Field(
        description="RCT design type"
    )
    registration_number: Optional[str] = Field(
        default=None, description="e.g., NCT number"
    )
    funding_source: Optional[str] = None

    # ------------------------------------------------------------------
    # Sample sizes
    # ------------------------------------------------------------------
    sample_size_total: int
    sample_size_intervention: int
    sample_size_control: int
    analyzed_intervention: Optional[int] = Field(
        default=None, description="N analyzed if different from randomized"
    )
    analyzed_control: Optional[int] = None

    # ------------------------------------------------------------------
    # Intervention details
    # ------------------------------------------------------------------
    hss_concentration_percent: float = Field(
        description="NaCl concentration, e.g., 1.4, 3.0, 4.6"
    )
    hss_concentration_variable: bool = Field(
        default=False,
        description="True if concentration adjusted to serum Na (Palermo protocol)",
    )
    hss_concentration_range: Optional[str] = Field(
        default=None, description="e.g., '1.4-4.6%' if variable"
    )
    hss_volume_ml: float = Field(description="Volume per dose in mL")
    hss_frequency: str = Field(
        description="e.g., 'BID', 'once daily', 'single dose'"
    )
    hss_duration_days: Optional[int] = Field(
        default=None, description="Number of days HSS administered"
    )
    hss_infusion_duration_min: Optional[int] = Field(
        default=None, description="Infusion time per dose in minutes"
    )
    loop_diuretic: str = Field(
        description="Drug name, e.g., 'furosemide', 'torasemide'"
    )
    loop_diuretic_dose_mg: float = Field(
        description="Dose per administration (mg)"
    )
    loop_diuretic_frequency: Optional[str] = Field(
        default=None, description="e.g., 'BID', 'continuous infusion'"
    )
    loop_diuretic_route: Optional[str] = Field(
        default=None, description="'IV bolus', 'IV infusion', 'IV in HSS'"
    )
    co_interventions: Optional[str] = Field(
        default=None,
        description="Other protocolized interventions (e.g., fluid restriction, Na diet)",
    )

    # ------------------------------------------------------------------
    # Comparator details
    # ------------------------------------------------------------------
    comparator_fluid: ComparatorFluid = Field(
        description="What fluid (if any) the control arm received"
    )
    comparator_fluid_detail: Optional[str] = Field(
        default=None, description="e.g., 'Normal saline 150mL'"
    )
    comparator_diuretic: str = Field(
        description="Comparator loop diuretic drug name"
    )
    comparator_diuretic_dose_mg: float
    comparator_diuretic_route: Optional[str] = None
    comparator_co_interventions: Optional[str] = None

    # ------------------------------------------------------------------
    # Trial eligibility criteria (for GRADE indirectness assessment)
    # ------------------------------------------------------------------
    age_min: Optional[int] = Field(
        default=None, description="Minimum age for inclusion"
    )
    age_max: Optional[int] = Field(
        default=None, description="Maximum age for inclusion"
    )
    ef_requirement: Optional[str] = Field(
        default=None,
        description="EF cutoff, e.g., '<40%', '>50%', 'any', 'not specified'",
    )
    sodium_requirement: Optional[str] = Field(
        default=None,
        description="e.g., 'Na ≤135', 'hyponatremic only', 'no restriction'",
    )
    renal_function_threshold: Optional[str] = Field(
        default=None,
        description="eGFR or creatinine cutoff for inclusion/exclusion",
    )
    time_window_hours: Optional[float] = Field(
        default=None,
        description="Max hours from admission to enrollment",
    )
    hf_diagnosis_method: Optional[str] = Field(
        default=None,
        description="'clinical only', 'BNP required', 'echo required', etc.",
    )
    nyha_class_requirement: Optional[str] = Field(
        default=None, description="Required NYHA class, e.g., 'III-IV', 'any'"
    )
    excluded_cardiogenic_shock: Optional[bool] = None
    excluded_dialysis: Optional[bool] = None
    excluded_mechanical_support: Optional[bool] = None
    sglt2i_policy: Optional[str] = Field(
        default=None,
        description="'allowed', 'excluded', 'mandated', 'not mentioned'",
    )
    diuretic_resistance_required: Optional[bool] = Field(
        default=None,
        description="Whether trial required demonstrated diuretic resistance",
    )
    diuretic_resistance_definition: Optional[str] = Field(
        default=None,
        description="How resistance was defined if required",
    )
    minimum_prior_diuretic_dose: Optional[str] = Field(
        default=None,
        description="Min prior diuretic dose for inclusion, if specified",
    )
    key_other_exclusions: Optional[str] = Field(
        default=None, description="Other notable exclusion criteria"
    )

    # ------------------------------------------------------------------
    # Population / setting flags
    # ------------------------------------------------------------------
    is_ambulatory: bool = Field(
        default=False,
        description="True if study enrolled ambulatory/day-hospital patients "
                    "(not admitted to hospital). Used for broadened-population "
                    "sensitivity analysis.",
    )
    is_crossover: bool = Field(
        default=False,
        description="True if crossover design. First-period data preferred.",
    )
    first_period_data_available: Optional[bool] = Field(
        default=None,
        description="For crossover trials: True if first-period data are "
                    "reported separately, False if only combined crossover data.",
    )
    overlapping_cohort_flag: Optional[str] = Field(
        default=None,
        description="If this study may share patients with another included "
                    "study, note which study and the basis for suspicion.",
    )
    companion_publications: Optional[str] = Field(
        default=None,
        description="PMIDs or citations of companion publications from the "
                    "same trial cohort.",
    )

    # ------------------------------------------------------------------
    # Baseline characteristics (per arm)
    # ------------------------------------------------------------------
    intervention_arm: ArmCharacteristics
    control_arm: ArmCharacteristics

    # ------------------------------------------------------------------
    # Outcomes — Mortality
    # ------------------------------------------------------------------
    mortality: Optional[BinaryOutcome] = None

    # ------------------------------------------------------------------
    # Outcomes — Length of stay
    # ------------------------------------------------------------------
    los: Optional[ContinuousOutcome] = Field(
        default=None, description="Hospital length of stay (days)"
    )

    # ------------------------------------------------------------------
    # Outcomes — Readmission
    # ------------------------------------------------------------------
    readmission: Optional[BinaryOutcome] = None

    # ------------------------------------------------------------------
    # Outcomes — Renal / Electrolytes
    # ------------------------------------------------------------------
    creatinine_change: Optional[ContinuousOutcome] = None
    sodium_change: Optional[ContinuousOutcome] = None
    peak_sodium: Optional[ContinuousOutcome] = Field(
        default=None,
        description="Peak serum sodium during treatment",
    )
    chloride_change: Optional[ContinuousOutcome] = None

    # ------------------------------------------------------------------
    # Outcomes — Diuretic response
    # ------------------------------------------------------------------
    urine_output_24h: Optional[ContinuousOutcome] = None
    natriuresis_24h: Optional[ContinuousOutcome] = Field(
        default=None,
        description="24-hour urine sodium excretion (mEq)",
    )
    weight_change: Optional[ContinuousOutcome] = None
    net_fluid_balance: Optional[ContinuousOutcome] = None

    # ------------------------------------------------------------------
    # Outcomes — Natriuretic peptides
    # ------------------------------------------------------------------
    bnp_change: Optional[ContinuousOutcome] = None

    # ------------------------------------------------------------------
    # Outcomes — Safety
    # ------------------------------------------------------------------
    hypernatremia: Optional[BinaryOutcome] = None
    aki: Optional[BinaryOutcome] = None
    troponin_elevation: Optional[BinaryOutcome] = Field(
        default=None,
        description="Troponin elevation events during treatment "
                    "(as defined by study authors)",
    )

    # ------------------------------------------------------------------
    # Risk of Bias (RoB 2.0)
    # ------------------------------------------------------------------
    rob_randomization: Optional[RoBJudgment] = None
    rob_deviations: Optional[RoBJudgment] = None
    rob_missing_data: Optional[RoBJudgment] = None
    rob_measurement: Optional[RoBJudgment] = None
    rob_selection: Optional[RoBJudgment] = None
    rob_overall: Optional[RoBJudgment] = None

    # ------------------------------------------------------------------
    # Classification flags
    # ------------------------------------------------------------------
    palermo_group: bool = Field(
        description="True if from Paterna/Tuttolomondo research group"
    )
    blinding: Optional[str] = Field(
        default=None,
        description="'open-label', 'single-blind', 'double-blind'",
    )
    follow_up_duration: Optional[str] = Field(
        default=None,
        description="Duration of follow-up, e.g., '30 days', '6 months'",
    )

    # ------------------------------------------------------------------
    # Extraction metadata
    # ------------------------------------------------------------------
    confidence_notes: Optional[str] = Field(
        default=None,
        description="Any extraction uncertainties or ambiguities",
    )
    extraction_source: Optional[str] = Field(
        default=None,
        description="'full_text', 'abstract_only', 'registry_data'",
    )


# ---------------------------------------------------------------------------
# Batch container
# ---------------------------------------------------------------------------

class ExtractionBatch(BaseModel):
    """Collection of extractions from one model for one screening batch."""

    model_name: str = Field(description="e.g., 'claude-opus-4-6' or 'gpt-5.4'")
    extraction_date: str = Field(description="ISO date string")
    schema_version: str = Field(default="1.0")
    studies: List[StudyExtraction]


# ---------------------------------------------------------------------------
# JSON schema export (for passing to LLMs as instruction)
# ---------------------------------------------------------------------------

def export_json_schema(path: Optional[str] = None) -> dict:
    """Export the StudyExtraction JSON schema for use in LLM prompts.

    If path is provided, writes to file. Always returns the schema dict.
    """
    import json

    schema = StudyExtraction.model_json_schema()
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
    return schema


if __name__ == "__main__":
    import json
    import sys

    schema = export_json_schema()
    print(json.dumps(schema, indent=2))
    print(f"\nTotal fields: {len(StudyExtraction.model_fields)}", file=sys.stderr)

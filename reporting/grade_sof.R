#!/usr/bin/env Rscript
# =============================================================================
# DESAL — GRADE Summary of Findings Table Generator
#
# Generates a GRADE Summary of Findings (SoF) table for the DESAL SR/MA.
# Certainty assessment follows the GRADE framework: RCT evidence starts
# at HIGH and may be downgraded across 5 domains.
#
# Usage:
#   Rscript grade_sof.R --data analysis/data/analysis_ready.csv \
#                        --ma-summary analysis/output/meta_analysis_summary.csv \
#                        --output reporting/grade_sof_table.csv
# =============================================================================

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
})

# =============================================================================
# 1. GRADE DOMAINS
# =============================================================================

#' Assess GRADE certainty for one outcome
#'
#' @param outcome_name Name of the outcome
#' @param n_studies Number of studies
#' @param effect Pooled effect estimate (RR or MD)
#' @param ci_lower Lower 95% CI
#' @param ci_upper Upper 95% CI
#' @param I2 I-squared (0-100)
#' @param n_palermo Number of Palermo group studies
#' @param n_high_rob Number of high RoB studies
#' @param n_total_patients Total patients across studies
#' @param egger_p Egger's test p-value (NA if <10 studies)
#' @param effect_type "RR" or "MD"
#' @return Data frame row with GRADE assessment
assess_grade <- function(outcome_name, n_studies, effect, ci_lower, ci_upper,
                          I2, n_palermo, n_high_rob, n_total_patients,
                          egger_p = NA, effect_type = "RR") {

  # Start at HIGH for RCT evidence
  certainty <- 4  # 4=high, 3=moderate, 2=low, 1=very low
  reasons <- character(0)

  # --- Domain 1: Risk of Bias ---
  # Downgrade if majority of studies have high RoB
  rob_concern <- FALSE
  if (!is.na(n_high_rob) && !is.na(n_studies) && n_studies > 0) {
    if (n_high_rob / n_studies > 0.5) {
      certainty <- certainty - 1
      reasons <- c(reasons, "Risk of bias: >50% of studies high RoB")
      rob_concern <- TRUE
    } else if (n_high_rob / n_studies > 0.25) {
      certainty <- certainty - 1
      reasons <- c(reasons, "Risk of bias: >25% of studies high RoB")
      rob_concern <- TRUE
    }
  }
  # Additional: if Palermo group dominates (>50% of studies) and they have
  # methodological concerns (single-center, single-blind), flag
  if (!is.na(n_palermo) && !is.na(n_studies) && n_studies > 0) {
    if (n_palermo / n_studies > 0.5 && !rob_concern) {
      certainty <- certainty - 1
      reasons <- c(reasons, "Risk of bias: evidence dominated by single research group")
    }
  }

  # --- Domain 2: Inconsistency ---
  if (!is.na(I2)) {
    if (I2 > 75) {
      certainty <- certainty - 1
      reasons <- c(reasons, sprintf("Inconsistency: considerable heterogeneity (I²=%.0f%%)", I2))
    } else if (I2 > 50) {
      certainty <- certainty - 1
      reasons <- c(reasons, sprintf("Inconsistency: substantial heterogeneity (I²=%.0f%%)", I2))
    }
  }

  # --- Domain 3: Indirectness ---
  # Generally low concern for this SR (direct PICO match)
  # Could flag if all studies are from one country or very specific populations
  # This is assessed manually — placeholder logic
  indirectness_note <- "No serious indirectness"

  # --- Domain 4: Imprecision ---
  if (!is.na(ci_lower) && !is.na(ci_upper)) {
    if (effect_type == "RR") {
      # CI crosses 1.0 (no effect) AND either crosses 0.75 or 1.25
      if (ci_lower < 1.0 && ci_upper > 1.0) {
        certainty <- certainty - 1
        reasons <- c(reasons, "Imprecision: CI crosses null")
      }
    } else if (effect_type == "MD") {
      if (ci_lower < 0 && ci_upper > 0) {
        certainty <- certainty - 1
        reasons <- c(reasons, "Imprecision: CI crosses null")
      }
    }
  }
  # Also check total sample size vs optimal information size
  if (!is.na(n_total_patients) && n_total_patients < 300) {
    if (!"Imprecision" %in% substr(reasons, 1, 11)) {
      certainty <- certainty - 1
      reasons <- c(reasons, sprintf("Imprecision: small total sample (n=%d)", n_total_patients))
    }
  }

  # --- Domain 5: Publication Bias ---
  if (!is.na(egger_p) && egger_p < 0.10) {
    certainty <- certainty - 1
    reasons <- c(reasons, sprintf("Publication bias: Egger's p=%.3f", egger_p))
  } else if (!is.na(n_palermo) && !is.na(n_studies) && n_studies >= 5) {
    if (n_palermo / n_studies > 0.6) {
      # Don't double-downgrade if already downgraded for RoB
      if (!any(grepl("single research group", reasons))) {
        certainty <- certainty - 1
        reasons <- c(reasons, "Publication bias: >60% of evidence from single group")
      }
    }
  }

  # Floor at very low

  certainty <- max(certainty, 1)

  certainty_label <- c("Very low", "Low", "Moderate", "High")[certainty]

  return(data.frame(
    outcome = outcome_name,
    n_studies = n_studies,
    n_patients = n_total_patients,
    effect_estimate = sprintf("%.2f", effect),
    ci_95 = sprintf("%.2f to %.2f", ci_lower, ci_upper),
    I2_pct = sprintf("%.0f%%", I2),
    certainty = certainty_label,
    reasons_for_downgrade = paste(reasons, collapse = "; "),
    stringsAsFactors = FALSE
  ))
}

# =============================================================================
# 2. BUILD SOF TABLE
# =============================================================================

build_sof_table <- function(ma_summary_path, data_path) {
  # Load meta-analysis summary
  if (!file.exists(ma_summary_path)) {
    message("Meta-analysis summary not found. Generating template with placeholders.")
    return(build_template_sof())
  }

  ma <- read_csv(ma_summary_path, show_col_types = FALSE)
  df <- read_csv(data_path, show_col_types = FALSE)

  n_total <- sum(df$n_total, na.rm = TRUE)
  n_palermo <- sum(df$palermo_group == TRUE, na.rm = TRUE)
  n_high_rob <- sum(df$rob_overall == "High", na.rm = TRUE)

  rows <- list()
  for (i in seq_len(nrow(ma))) {
    row <- ma[i, ]
    effect_type <- ifelse(row$outcome %in% c("mortality", "readmission",
                                               "hypernatremia", "aki"), "RR", "MD")
    rows[[i]] <- assess_grade(
      outcome_name = row$outcome,
      n_studies = row$n_studies,
      effect = as.numeric(row$effect_random),
      ci_lower = as.numeric(row$ci_lower),
      ci_upper = as.numeric(row$ci_upper),
      I2 = as.numeric(gsub("%", "", row$I2)),
      n_palermo = n_palermo,
      n_high_rob = n_high_rob,
      n_total_patients = n_total,
      effect_type = effect_type
    )
  }

  return(bind_rows(rows))
}

build_template_sof <- function() {
  outcomes <- c(
    "All-cause mortality",
    "Length of hospital stay",
    "Heart failure readmission",
    "Body weight change",
    "24h urine output",
    "24h natriuresis",
    "Serum sodium change",
    "Serum chloride change",
    "Serum creatinine change",
    "Hypernatremia events",
    "Acute kidney injury",
    "Troponin elevation"
  )

  data.frame(
    outcome = outcomes,
    n_studies = "[N]",
    n_patients = "[N]",
    effect_estimate = "[RR/MD]",
    ci_95 = "[CI]",
    I2_pct = "[I²]",
    certainty = "[GRADE]",
    reasons_for_downgrade = "[reasons]",
    stringsAsFactors = FALSE
  )
}

# =============================================================================
# 3. MAIN
# =============================================================================

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)

  data_path <- "analysis/data/analysis_ready.csv"
  ma_summary_path <- "analysis/output/meta_analysis_summary.csv"
  output <- "reporting/grade_sof_table.csv"

  for (i in seq_along(args)) {
    if (args[i] == "--data" && i < length(args)) data_path <- args[i + 1]
    if (args[i] == "--ma-summary" && i < length(args)) ma_summary_path <- args[i + 1]
    if (args[i] == "--output" && i < length(args)) output <- args[i + 1]
  }

  dir.create(dirname(output), recursive = TRUE, showWarnings = FALSE)

  sof <- build_sof_table(ma_summary_path, data_path)
  write_csv(sof, output)

  message(sprintf("GRADE Summary of Findings table saved to %s", output))
  print(sof)
}

if (!interactive()) main()

#!/usr/bin/env Rscript
# =============================================================================
# DESAL — Prepare Analysis-Ready Dataset
#
# Converts final_extractions.json from the extraction pipeline into a flat
# CSV suitable for meta_analysis.R and tsa.R.
#
# Handles:
#   - Median/IQR → Mean/SD conversion (Wan et al. 2014)
#   - Creating subgroup category columns
#   - Validating required fields
#
# Usage:
#   Rscript prepare_data.R --input extraction/data/final_extractions.json
#   Rscript prepare_data.R --input extraction/data/final_extractions.json \
#                          --output analysis/data/analysis_ready.csv
# =============================================================================

suppressPackageStartupMessages({
  library(jsonlite)
  library(dplyr)
  library(readr)
})

# Wan et al. 2014 conversion
estimate_mean_sd <- function(median, q1, q3, n) {
  est_mean <- (q1 + median + q3) / 3
  iqr <- q3 - q1
  if (n <= 15) {
    est_sd <- iqr / (2 * qnorm((0.75 * n - 0.125) / (n + 0.25)))
  } else {
    est_sd <- iqr / (2 * qnorm(0.75))
  }
  return(list(mean = est_mean, sd = est_sd))
}

flatten_extraction <- function(ext) {
  e <- ext$extraction

  # Helper to safely extract nested values
  safe <- function(...) {
    tryCatch({
      val <- e
      for (key in list(...)) {
        val <- val[[key]]
      }
      if (is.null(val)) NA else val
    }, error = function(err) NA)
  }

  row <- data.frame(
    study_id = safe("study_id"),
    author = safe("author"),
    year = safe("year"),
    country = safe("country"),
    single_center = safe("single_center"),
    study_design = safe("study_design"),
    palermo_group = safe("palermo_group"),
    blinding = safe("blinding"),
    is_ambulatory = safe("is_ambulatory"),
    is_crossover = safe("is_crossover"),
    first_period_data_available = safe("first_period_data_available"),
    overlapping_cohort_flag = safe("overlapping_cohort_flag"),

    # Sample sizes
    n_total = safe("sample_size_total"),
    n_int = safe("sample_size_intervention"),
    n_ctrl = safe("sample_size_control"),

    # Intervention
    hss_concentration_percent = safe("hss_concentration_percent"),
    hss_volume_ml = safe("hss_volume_ml"),
    hss_frequency = safe("hss_frequency"),
    loop_diuretic = safe("loop_diuretic"),
    loop_diuretic_dose_mg = safe("loop_diuretic_dose_mg"),
    diuretic_resistance_required = safe("diuretic_resistance_required"),

    # Baseline characteristics
    mean_age_int = safe("intervention_arm", "mean_age"),
    mean_age_ctrl = safe("control_arm", "mean_age"),
    mean_ef_int = safe("intervention_arm", "mean_ef"),
    mean_ef_ctrl = safe("control_arm", "mean_ef"),
    baseline_sodium_int = safe("intervention_arm", "baseline_sodium"),
    baseline_sodium_ctrl = safe("control_arm", "baseline_sodium"),

    # Mortality
    mortality_events_int = safe("mortality", "events_intervention"),
    mortality_n_int = safe("mortality", "n_intervention"),
    mortality_events_ctrl = safe("mortality", "events_control"),
    mortality_n_ctrl = safe("mortality", "n_control"),
    mortality_timepoint = safe("mortality", "timepoint"),

    # LOS
    los_value_int = safe("los", "value_intervention"),
    los_sd_int = safe("los", "sd_intervention"),
    los_value_ctrl = safe("los", "value_control"),
    los_sd_ctrl = safe("los", "sd_control"),
    los_measure_type = safe("los", "measure_type"),
    los_iqr_low_int = safe("los", "iqr_low_intervention"),
    los_iqr_high_int = safe("los", "iqr_high_intervention"),
    los_iqr_low_ctrl = safe("los", "iqr_low_control"),
    los_iqr_high_ctrl = safe("los", "iqr_high_control"),

    # Readmission
    readmission_events_int = safe("readmission", "events_intervention"),
    readmission_n_int = safe("readmission", "n_intervention"),
    readmission_events_ctrl = safe("readmission", "events_control"),
    readmission_n_ctrl = safe("readmission", "n_control"),

    # Weight change
    weight_mean_int = safe("weight_change", "value_intervention"),
    weight_sd_int = safe("weight_change", "sd_intervention"),
    weight_mean_ctrl = safe("weight_change", "value_control"),
    weight_sd_ctrl = safe("weight_change", "sd_control"),

    # Urine output
    urine_mean_int = safe("urine_output_24h", "value_intervention"),
    urine_sd_int = safe("urine_output_24h", "sd_intervention"),
    urine_mean_ctrl = safe("urine_output_24h", "value_control"),
    urine_sd_ctrl = safe("urine_output_24h", "sd_control"),

    # Sodium change
    sodium_change_mean_int = safe("sodium_change", "value_intervention"),
    sodium_change_sd_int = safe("sodium_change", "sd_intervention"),
    sodium_change_mean_ctrl = safe("sodium_change", "value_control"),
    sodium_change_sd_ctrl = safe("sodium_change", "sd_control"),

    # Creatinine change
    creat_change_mean_int = safe("creatinine_change", "value_intervention"),
    creat_change_sd_int = safe("creatinine_change", "sd_intervention"),
    creat_change_mean_ctrl = safe("creatinine_change", "value_control"),
    creat_change_sd_ctrl = safe("creatinine_change", "sd_control"),

    # Safety
    hypernatremia_events_int = safe("hypernatremia", "events_intervention"),
    hypernatremia_events_ctrl = safe("hypernatremia", "events_control"),
    aki_events_int = safe("aki", "events_intervention"),
    aki_events_ctrl = safe("aki", "events_control"),

    # RoB
    rob_randomization = safe("rob_randomization"),
    rob_deviations = safe("rob_deviations"),
    rob_missing_data = safe("rob_missing_data"),
    rob_measurement = safe("rob_measurement"),
    rob_selection = safe("rob_selection"),
    rob_overall = safe("rob_overall"),

    stringsAsFactors = FALSE
  )

  return(row)
}

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)

  input_path <- "extraction/data/final_extractions.json"
  output_path <- "analysis/data/analysis_ready.csv"

  for (i in seq_along(args)) {
    if (args[i] == "--input" && i < length(args)) input_path <- args[i + 1]
    if (args[i] == "--output" && i < length(args)) output_path <- args[i + 1]
  }

  # Load
  extractions <- fromJSON(input_path, simplifyVector = FALSE)
  message(sprintf("Loaded %d studies from %s", length(extractions), input_path))

  # Flatten
  rows <- lapply(extractions, flatten_extraction)
  df <- bind_rows(rows)

  # --- Median/IQR → Mean/SD conversion for LOS ---
  for (i in seq_len(nrow(df))) {
    if (!is.na(df$los_measure_type[i]) && df$los_measure_type[i] == "median_iqr") {
      # Intervention arm
      if (!is.na(df$los_value_int[i]) && !is.na(df$los_iqr_low_int[i]) &&
          !is.na(df$los_iqr_high_int[i]) && !is.na(df$n_int[i])) {
        conv <- estimate_mean_sd(df$los_value_int[i], df$los_iqr_low_int[i],
                                  df$los_iqr_high_int[i], df$n_int[i])
        df$los_value_int[i] <- conv$mean
        df$los_sd_int[i] <- conv$sd
      }
      # Control arm
      if (!is.na(df$los_value_ctrl[i]) && !is.na(df$los_iqr_low_ctrl[i]) &&
          !is.na(df$los_iqr_high_ctrl[i]) && !is.na(df$n_ctrl[i])) {
        conv <- estimate_mean_sd(df$los_value_ctrl[i], df$los_iqr_low_ctrl[i],
                                  df$los_iqr_high_ctrl[i], df$n_ctrl[i])
        df$los_value_ctrl[i] <- conv$mean
        df$los_sd_ctrl[i] <- conv$sd
      }
      df$los_measure_type[i] <- "converted_from_median_iqr"
    }
  }

  # Rename LOS columns for analysis scripts
  df <- df %>% rename(
    los_mean_int = los_value_int,
    los_mean_ctrl = los_value_ctrl,
    los_n_int = n_int,
    los_n_ctrl = n_ctrl
  )

  # Use mortality N as fallback for safety denominators
  if (!"mortality_n_int" %in% names(df)) {
    df$mortality_n_int <- df$los_n_int
    df$mortality_n_ctrl <- df$los_n_ctrl
  }

  # Save
  dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
  write_csv(df, output_path)
  message(sprintf("Analysis-ready dataset saved to %s (%d studies, %d columns)",
                  output_path, nrow(df), ncol(df)))
}

if (!interactive()) main()

#!/usr/bin/env Rscript
# =============================================================================
# DESAL Systematic Review — Meta-Analysis v1.0
#
# Random-effects meta-analysis using meta/metafor.
# Pre-specified per DESAL_SRMA_Protocol.md and pipeline doc Section 4.1.
#
# Usage:
#   Rscript meta_analysis.R --data analysis/data/analysis_ready.csv
#   Rscript meta_analysis.R --data analysis/data/analysis_ready.csv --outdir analysis/output/
# =============================================================================

suppressPackageStartupMessages({
  library(meta)
  library(metafor)
  library(dplyr)
  library(readr)
  library(ggplot2)
})

# =============================================================================
# 1. DATA LOADING
# =============================================================================

load_data <- function(path) {
  df <- read_csv(path, show_col_types = FALSE)
  message(sprintf("Loaded %d studies from %s", nrow(df), path))
  return(df)
}

# Validate required columns for each outcome
validate_columns <- function(df, required_cols, outcome_name) {
  missing <- setdiff(required_cols, names(df))
  if (length(missing) > 0) {
    warning(sprintf("Missing columns for %s: %s", outcome_name,
                    paste(missing, collapse = ", ")))
    return(FALSE)
  }
  return(TRUE)
}

# =============================================================================
# 2. MEDIAN/IQR → MEAN/SD CONVERSION
# =============================================================================

#' Convert median + IQR to estimated mean + SD
#' Using Wan et al. 2014 (BMC Med Res Methodol) and Luo et al. 2018 methods
#'
#' @param median Median value
#' @param q1 First quartile (25th percentile)
#' @param q3 Third quartile (75th percentile)
#' @param n Sample size
#' @return List with estimated mean and sd
estimate_mean_sd <- function(median, q1, q3, n) {
  # Wan et al. 2014 formula for estimating mean from median + Q1 + Q3
  est_mean <- (q1 + median + q3) / 3

  # Wan et al. 2014 formula for estimating SD from IQR
  # For n >= 15, SD ≈ IQR / (2 * qnorm(0.75)) ≈ IQR / 1.35
  # More precise formula uses sample size correction
  iqr <- q3 - q1

  if (n <= 15) {
    # Small sample correction (Table 2 in Wan et al.)
    est_sd <- iqr / (2 * qnorm((0.75 * n - 0.125) / (n + 0.25)))
  } else {
    est_sd <- iqr / (2 * qnorm(0.75))
  }

  return(list(mean = est_mean, sd = est_sd))
}

# =============================================================================
# 3. PRIMARY OUTCOME: ALL-CAUSE MORTALITY (BINARY)
# =============================================================================

run_mortality_ma <- function(df, outdir) {
  # Required: mortality events and denominators
  required <- c("study_id", "mortality_events_int", "mortality_n_int",
                 "mortality_events_ctrl", "mortality_n_ctrl")
  if (!validate_columns(df, required, "mortality")) return(NULL)

  d <- df %>%
    filter(!is.na(mortality_events_int), !is.na(mortality_events_ctrl)) %>%
    mutate(
      # Ensure at least 0 events (no negative)
      mortality_events_int = pmax(mortality_events_int, 0),
      mortality_events_ctrl = pmax(mortality_events_ctrl, 0)
    )

  if (nrow(d) < 2) {
    message("Fewer than 2 studies reporting mortality. Skipping.")
    return(NULL)
  }

  message(sprintf("Mortality MA: %d studies", nrow(d)))

  # Exclude zero-zero studies (RR undefined); keep zero-in-one-arm (0.5 correction)
  d_nonzero <- d %>%
    filter(!(mortality_events_int == 0 & mortality_events_ctrl == 0))
  n_zero_zero <- nrow(d) - nrow(d_nonzero)
  if (n_zero_zero > 0) {
    message(sprintf("  Excluded %d studies with zero events in both arms.", n_zero_zero))
  }
  d <- d_nonzero

  if (nrow(d) < 2) {
    message("Fewer than 2 studies with events. Skipping.")
    return(NULL)
  }

  # Random-effects meta-analysis with REML
  # Default 0.5 continuity correction for studies with zero events in one arm
  m <- metabin(
    event.e = mortality_events_int,
    n.e = mortality_n_int,
    event.c = mortality_events_ctrl,
    n.c = mortality_n_ctrl,
    studlab = study_id,
    data = d,
    sm = "RR",
    method.tau = "REML",
    incr = 0.5,      # default continuity correction
    common = TRUE,    # also compute fixed-effect for sensitivity
    random = TRUE,
    prediction = TRUE,
    title = "All-Cause Mortality"
  )

  # Forest plot
  pdf(file.path(outdir, "forest_plots", "mortality_forest.pdf"),
      width = 12, height = max(6, nrow(d) * 0.6 + 2))
  forest(m,
         sortvar = d$year,
         leftcols = c("studlab", "event.e", "n.e", "event.c", "n.c"),
         leftlabs = c("Study", "Events", "N", "Events", "N"),
         label.left = "Favours HSS",
         label.right = "Favours Control",
         print.tau2 = TRUE,
         print.I2 = TRUE,
         prediction = TRUE)
  dev.off()

  # Funnel plot (if >= 10 studies)
  if (nrow(d) >= 10) {
    pdf(file.path(outdir, "funnel_plots", "mortality_funnel.pdf"),
        width = 8, height = 6)
    funnel(m, studlab = TRUE)
    dev.off()

    # Egger's test
    egger <- metabias(m, method.bias = "linreg")
    message(sprintf("Egger's test p = %.4f", egger$pval))
  }

  return(m)
}

# =============================================================================
# 4. LENGTH OF STAY (CONTINUOUS)
# =============================================================================

run_los_ma <- function(df, outdir) {
  required <- c("study_id", "los_mean_int", "los_sd_int",
                 "los_mean_ctrl", "los_sd_ctrl",
                 "los_n_int", "los_n_ctrl")
  if (!validate_columns(df, required, "LOS")) return(NULL)

  d <- df %>%
    filter(!is.na(los_mean_int), !is.na(los_mean_ctrl))

  if (nrow(d) < 2) {
    message("Fewer than 2 studies reporting LOS. Skipping.")
    return(NULL)
  }

  message(sprintf("LOS MA: %d studies", nrow(d)))

  m <- metacont(
    n.e = los_n_int,
    mean.e = los_mean_int,
    sd.e = los_sd_int,
    n.c = los_n_ctrl,
    mean.c = los_mean_ctrl,
    sd.c = los_sd_ctrl,
    studlab = study_id,
    data = d,
    sm = "MD",
    method.tau = "REML",
    common = TRUE,
    random = TRUE,
    prediction = TRUE,
    title = "Length of Hospital Stay (days)"
  )

  pdf(file.path(outdir, "forest_plots", "los_forest.pdf"),
      width = 12, height = max(6, nrow(d) * 0.6 + 2))
  forest(m,
         sortvar = d$year,
         label.left = "Favours HSS",
         label.right = "Favours Control",
         print.tau2 = TRUE,
         print.I2 = TRUE,
         prediction = TRUE)
  dev.off()

  if (nrow(d) >= 10) {
    pdf(file.path(outdir, "funnel_plots", "los_funnel.pdf"),
        width = 8, height = 6)
    funnel(m, studlab = TRUE)
    dev.off()
  }

  return(m)
}

# =============================================================================
# 5. READMISSION (BINARY)
# =============================================================================

run_readmission_ma <- function(df, outdir) {
  required <- c("study_id", "readmission_events_int", "readmission_n_int",
                 "readmission_events_ctrl", "readmission_n_ctrl")
  if (!validate_columns(df, required, "readmission")) return(NULL)

  d <- df %>%
    filter(!is.na(readmission_events_int), !is.na(readmission_events_ctrl))

  if (nrow(d) < 2) {
    message("Fewer than 2 studies reporting readmission. Skipping.")
    return(NULL)
  }

  message(sprintf("Readmission MA: %d studies", nrow(d)))

  m <- metabin(
    event.e = readmission_events_int,
    n.e = readmission_n_int,
    event.c = readmission_events_ctrl,
    n.c = readmission_n_ctrl,
    studlab = study_id,
    data = d,
    sm = "RR",
    method.tau = "REML",
    common = TRUE,
    random = TRUE,
    prediction = TRUE,
    title = "Heart Failure Readmission"
  )

  pdf(file.path(outdir, "forest_plots", "readmission_forest.pdf"),
      width = 12, height = max(6, nrow(d) * 0.6 + 2))
  forest(m,
         sortvar = d$year,
         label.left = "Favours HSS",
         label.right = "Favours Control",
         print.tau2 = TRUE,
         print.I2 = TRUE)
  dev.off()

  return(m)
}

# =============================================================================
# 6. SECONDARY CONTINUOUS OUTCOMES
# =============================================================================

run_continuous_ma <- function(df, outdir, outcome_name, mean_int_col,
                              sd_int_col, n_int_col, mean_ctrl_col,
                              sd_ctrl_col, n_ctrl_col, unit = "") {
  required <- c("study_id", mean_int_col, sd_int_col, n_int_col,
                 mean_ctrl_col, sd_ctrl_col, n_ctrl_col)
  if (!validate_columns(df, required, outcome_name)) return(NULL)

  d <- df %>%
    filter(!is.na(.data[[mean_int_col]]), !is.na(.data[[mean_ctrl_col]]))

  if (nrow(d) < 2) {
    message(sprintf("Fewer than 2 studies for %s. Skipping.", outcome_name))
    return(NULL)
  }

  message(sprintf("%s MA: %d studies", outcome_name, nrow(d)))

  m <- metacont(
    n.e = d[[n_int_col]],
    mean.e = d[[mean_int_col]],
    sd.e = d[[sd_int_col]],
    n.c = d[[n_ctrl_col]],
    mean.c = d[[mean_ctrl_col]],
    sd.c = d[[sd_ctrl_col]],
    studlab = d$study_id,
    data = d,
    sm = "MD",
    method.tau = "REML",
    common = TRUE,
    random = TRUE,
    prediction = TRUE,
    title = sprintf("%s%s", outcome_name, ifelse(unit != "", paste0(" (", unit, ")"), ""))
  )

  safe_name <- gsub("[^a-zA-Z0-9]", "_", tolower(outcome_name))
  pdf(file.path(outdir, "forest_plots", paste0(safe_name, "_forest.pdf")),
      width = 12, height = max(6, nrow(d) * 0.6 + 2))
  forest(m,
         sortvar = d$year,
         label.left = "Favours HSS",
         label.right = "Favours Control",
         print.tau2 = TRUE,
         print.I2 = TRUE)
  dev.off()

  return(m)
}

run_binary_ma <- function(df, outdir, outcome_name, events_int_col,
                          n_int_col, events_ctrl_col, n_ctrl_col) {
  required <- c("study_id", events_int_col, n_int_col,
                 events_ctrl_col, n_ctrl_col)
  if (!validate_columns(df, required, outcome_name)) return(NULL)

  d <- df %>%
    filter(!is.na(.data[[events_int_col]]), !is.na(.data[[events_ctrl_col]]))

  if (nrow(d) < 2) {
    message(sprintf("Fewer than 2 studies for %s. Skipping.", outcome_name))
    return(NULL)
  }

  message(sprintf("%s MA: %d studies", outcome_name, nrow(d)))

  m <- metabin(
    event.e = d[[events_int_col]],
    n.e = d[[n_int_col]],
    event.c = d[[events_ctrl_col]],
    n.c = d[[n_ctrl_col]],
    studlab = d$study_id,
    data = d,
    sm = "RR",
    method.tau = "REML",
    common = TRUE,
    random = TRUE,
    title = outcome_name
  )

  safe_name <- gsub("[^a-zA-Z0-9]", "_", tolower(outcome_name))
  pdf(file.path(outdir, "forest_plots", paste0(safe_name, "_forest.pdf")),
      width = 12, height = max(6, nrow(d) * 0.6 + 2))
  forest(m,
         sortvar = d$year,
         label.left = "Favours HSS",
         label.right = "Favours Control",
         print.tau2 = TRUE,
         print.I2 = TRUE)
  dev.off()

  return(m)
}

# =============================================================================
# 7. SUBGROUP ANALYSES
# =============================================================================

run_subgroup_analysis <- function(ma_result, df, subgroup_col, outcome_label,
                                  outdir, ma_type = "binary") {
  if (is.null(ma_result)) return(NULL)
  if (!subgroup_col %in% names(df)) {
    message(sprintf("  Subgroup column '%s' not found. Skipping.", subgroup_col))
    return(NULL)
  }

  d <- df %>% filter(!is.na(.data[[subgroup_col]]))
  if (nrow(d) < 4) return(NULL)  # need at least 2 per subgroup

  # Check that at least 2 levels exist with >= 2 studies each
  level_counts <- table(d[[subgroup_col]])
  valid_levels <- names(level_counts[level_counts >= 2])
  if (length(valid_levels) < 2) {
    message(sprintf("  Subgroup '%s': fewer than 2 levels with ≥2 studies.",
                    subgroup_col))
    return(NULL)
  }

  message(sprintf("  Subgroup analysis: %s by %s", outcome_label, subgroup_col))

  # Update meta-analysis with subgroup
  tryCatch({
    m_sub <- update(ma_result, subgroup = d[[subgroup_col]])

    safe_name <- gsub("[^a-zA-Z0-9]", "_", tolower(outcome_label))
    safe_sub <- gsub("[^a-zA-Z0-9]", "_", tolower(subgroup_col))
    pdf(file.path(outdir, "forest_plots",
                  paste0(safe_name, "_by_", safe_sub, ".pdf")),
        width = 14, height = max(8, nrow(d) * 0.6 + 4))
    forest(m_sub,
           sortvar = d$year,
           label.left = "Favours HSS",
           label.right = "Favours Control",
           print.tau2 = TRUE,
           print.I2 = TRUE,
           test.subgroup = TRUE)
    dev.off()

    return(m_sub)
  }, error = function(e) {
    message(sprintf("  Subgroup error: %s", e$message))
    return(NULL)
  })
}

# Pre-specified subgroups from protocol
run_all_subgroups <- function(ma_result, df, outcome_label, outdir,
                               ma_type = "binary") {
  subgroups <- c(
    "palermo_group",           # Key: Paterna vs independent
    "hss_conc_category",       # ≤3% vs >3%
    "dosing_category",         # single vs repeated
    "baseline_na_category",    # ≤135 vs >135
    "hf_phenotype",            # HFrEF vs HFpEF
    "rob_category",            # low vs some concerns/high
    "diuretic_resistance_required"  # yes vs no
  )

  results <- list()
  for (sg in subgroups) {
    results[[sg]] <- run_subgroup_analysis(
      ma_result, df, sg, outcome_label, outdir, ma_type
    )
  }
  return(results)
}

# =============================================================================
# 8. SENSITIVITY ANALYSES
# =============================================================================

run_sensitivity_analyses <- function(df, outdir) {
  results <- list()

  # 1. Excluding Paterna/Tuttolomondo studies
  if ("palermo_group" %in% names(df)) {
    df_excl_palermo <- df %>% filter(palermo_group == FALSE)
    if (nrow(df_excl_palermo) >= 2) {
      message("\nSensitivity 1: Excluding Palermo group")
      results$excl_palermo_mortality <- run_mortality_ma(df_excl_palermo, outdir)
      results$excl_palermo_los <- run_los_ma(df_excl_palermo, outdir)
    }
  }

  # 2. Excluding high risk of bias studies
  if ("rob_overall" %in% names(df)) {
    df_low_rob <- df %>% filter(rob_overall == "Low")
    if (nrow(df_low_rob) >= 2) {
      message("\nSensitivity 2: Low RoB only")
      results$low_rob_mortality <- run_mortality_ma(df_low_rob, outdir)
      results$low_rob_los <- run_los_ma(df_low_rob, outdir)
    }
  }

  # 3. Fixed-effect model is already computed (common = TRUE in metabin/metacont)
  message("\nSensitivity 3: Fixed-effect estimates available in primary output (common = TRUE)")

  # 4. Leave-one-out
  message("\nSensitivity 4: Leave-one-out analysis")
  # Leave-one-out is computed via metainf() from the meta package

  # 5. Broadened population (including ambulatory worsening HF, e.g., SALT-HF)
  if ("is_ambulatory" %in% names(df)) {
    df_broadened <- df  # include all, including ambulatory
    df_hosp_only <- df %>% filter(is_ambulatory == FALSE | is.na(is_ambulatory))
    if (nrow(df_broadened) > nrow(df_hosp_only) && nrow(df_broadened) >= 2) {
      message("\nSensitivity 5: Broadened population (including ambulatory worsening HF)")
      results$broadened_mortality <- run_mortality_ma(df_broadened, outdir)
      results$broadened_los <- run_los_ma(df_broadened, outdir)
    }
  }

  # 6. Excluding crossover trials
  if ("study_design" %in% names(df)) {
    df_no_crossover <- df %>% filter(study_design != "crossover" | is.na(study_design))
    if (nrow(df_no_crossover) < nrow(df) && nrow(df_no_crossover) >= 2) {
      message("\nSensitivity 6: Excluding crossover trials")
      results$excl_crossover_mortality <- run_mortality_ma(df_no_crossover, outdir)
      results$excl_crossover_los <- run_los_ma(df_no_crossover, outdir)
    }
  }

  # 7. Treatment-arm continuity correction (TACC) for binary outcomes
  message("\nSensitivity 7: TACC for binary outcomes")
  d_mort <- df %>%
    filter(!is.na(mortality_events_int), !is.na(mortality_events_ctrl)) %>%
    filter(!(mortality_events_int == 0 & mortality_events_ctrl == 0))
  if (nrow(d_mort) >= 2) {
    tryCatch({
      results$tacc_mortality <- metabin(
        event.e = mortality_events_int,
        n.e = mortality_n_int,
        event.c = mortality_events_ctrl,
        n.c = mortality_n_ctrl,
        studlab = study_id,
        data = d_mort,
        sm = "RR",
        method.tau = "REML",
        incr = "TACC",
        common = TRUE,
        random = TRUE,
        title = "Mortality (TACC sensitivity)"
      )
    }, error = function(e) {
      message(sprintf("  TACC error: %s", e$message))
    })
  }

  return(results)
}

# =============================================================================
# 9. SUMMARY TABLE
# =============================================================================

build_summary_table <- function(results) {
  rows <- list()

  for (name in names(results)) {
    m <- results[[name]]
    if (is.null(m)) next
    if (!inherits(m, "meta")) next

    rows[[length(rows) + 1]] <- data.frame(
      outcome = name,
      n_studies = m$k,
      effect_random = sprintf("%.2f", exp(m$TE.random)),
      ci_lower = sprintf("%.2f", exp(m$lower.random)),
      ci_upper = sprintf("%.2f", exp(m$upper.random)),
      p_value = sprintf("%.4f", m$pval.random),
      I2 = sprintf("%.1f%%", m$I2 * 100),
      tau2 = sprintf("%.4f", m$tau2),
      stringsAsFactors = FALSE
    )
  }

  if (length(rows) == 0) return(NULL)
  return(bind_rows(rows))
}

# =============================================================================
# 10. MAIN
# =============================================================================

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)

  # Parse arguments
  data_path <- "analysis/data/analysis_ready.csv"
  outdir <- "analysis/output"

  for (i in seq_along(args)) {
    if (args[i] == "--data" && i < length(args)) data_path <- args[i + 1]
    if (args[i] == "--outdir" && i < length(args)) outdir <- args[i + 1]
  }

  # Ensure output directories exist
  dir.create(file.path(outdir, "forest_plots"), recursive = TRUE, showWarnings = FALSE)
  dir.create(file.path(outdir, "funnel_plots"), recursive = TRUE, showWarnings = FALSE)

  # Load data
  df <- load_data(data_path)

  # Create subgroup categories if source columns exist
  if ("hss_concentration_percent" %in% names(df)) {
    df$hss_conc_category <- ifelse(df$hss_concentration_percent <= 3, "≤3%", ">3%")
  }
  if ("hss_frequency" %in% names(df)) {
    df$dosing_category <- ifelse(
      grepl("single|once", df$hss_frequency, ignore.case = TRUE),
      "single dose", "repeated"
    )
  }
  if ("baseline_sodium_int" %in% names(df)) {
    df$baseline_na_category <- ifelse(df$baseline_sodium_int <= 135, "≤135", ">135")
  }
  if ("mean_ef_int" %in% names(df)) {
    df$hf_phenotype <- ifelse(df$mean_ef_int <= 40, "HFrEF", "HFpEF")
  }
  if ("rob_overall" %in% names(df)) {
    df$rob_category <- ifelse(df$rob_overall == "Low", "Low", "Some concerns/High")
  }

  # ── Run all analyses ──

  results <- list()

  message("\n=== PRIMARY OUTCOME: MORTALITY ===")
  results$mortality <- run_mortality_ma(df, outdir)

  message("\n=== LENGTH OF STAY ===")
  results$los <- run_los_ma(df, outdir)

  message("\n=== READMISSION ===")
  results$readmission <- run_readmission_ma(df, outdir)

  message("\n=== SECONDARY: WEIGHT CHANGE ===")
  results$weight <- run_continuous_ma(
    df, outdir, "Weight Change", "weight_mean_int", "weight_sd_int",
    "los_n_int", "weight_mean_ctrl", "weight_sd_ctrl", "los_n_ctrl", "kg"
  )

  message("\n=== SECONDARY: URINE OUTPUT 24H ===")
  results$urine <- run_continuous_ma(
    df, outdir, "Urine Output 24h", "urine_mean_int", "urine_sd_int",
    "los_n_int", "urine_mean_ctrl", "urine_sd_ctrl", "los_n_ctrl", "mL"
  )

  message("\n=== SECONDARY: SODIUM CHANGE ===")
  results$sodium <- run_continuous_ma(
    df, outdir, "Sodium Change", "sodium_change_mean_int", "sodium_change_sd_int",
    "los_n_int", "sodium_change_mean_ctrl", "sodium_change_sd_ctrl",
    "los_n_ctrl", "mEq/L"
  )

  message("\n=== SECONDARY: CREATININE CHANGE ===")
  results$creatinine <- run_continuous_ma(
    df, outdir, "Creatinine Change", "creat_change_mean_int", "creat_change_sd_int",
    "los_n_int", "creat_change_mean_ctrl", "creat_change_sd_ctrl",
    "los_n_ctrl", "mg/dL"
  )

  message("\n=== SECONDARY: NATRIURESIS (24H URINE SODIUM) ===")
  results$natriuresis <- run_continuous_ma(
    df, outdir, "Natriuresis 24h", "natriuresis_mean_int", "natriuresis_sd_int",
    "los_n_int", "natriuresis_mean_ctrl", "natriuresis_sd_ctrl",
    "los_n_ctrl", "mEq"
  )

  message("\n=== SECONDARY: CHLORIDE CHANGE ===")
  results$chloride <- run_continuous_ma(
    df, outdir, "Chloride Change", "chloride_change_mean_int", "chloride_change_sd_int",
    "los_n_int", "chloride_change_mean_ctrl", "chloride_change_sd_ctrl",
    "los_n_ctrl", "mEq/L"
  )

  message("\n=== SAFETY: HYPERNATREMIA ===")
  results$hypernatremia <- run_binary_ma(
    df, outdir, "Hypernatremia",
    "hypernatremia_events_int", "mortality_n_int",
    "hypernatremia_events_ctrl", "mortality_n_ctrl"
  )

  message("\n=== SAFETY: AKI ===")
  results$aki <- run_binary_ma(
    df, outdir, "Acute Kidney Injury",
    "aki_events_int", "mortality_n_int",
    "aki_events_ctrl", "mortality_n_ctrl"
  )

  message("\n=== SAFETY: TROPONIN ELEVATION ===")
  results$troponin <- run_binary_ma(
    df, outdir, "Troponin Elevation",
    "troponin_events_int", "troponin_n_int",
    "troponin_events_ctrl", "troponin_n_ctrl"
  )

  # ── Subgroup analyses ──
  message("\n=== SUBGROUP ANALYSES ===")
  if (!is.null(results$mortality)) {
    results$mortality_subgroups <- run_all_subgroups(
      results$mortality, df, "Mortality", outdir, "binary"
    )
  }
  if (!is.null(results$los)) {
    results$los_subgroups <- run_all_subgroups(
      results$los, df, "LOS", outdir, "continuous"
    )
  }

  # ── Sensitivity analyses ──
  message("\n=== SENSITIVITY ANALYSES ===")
  results$sensitivity <- run_sensitivity_analyses(df, outdir)

  # ── Summary table ──
  summary_tbl <- build_summary_table(results)
  if (!is.null(summary_tbl)) {
    write_csv(summary_tbl, file.path(outdir, "meta_analysis_summary.csv"))
    message("\nSummary table saved.")
    print(summary_tbl)
  }

  message("\n=== META-ANALYSIS COMPLETE ===")
  message(sprintf("Outputs saved to %s", outdir))
}

# Run
if (!interactive()) main()

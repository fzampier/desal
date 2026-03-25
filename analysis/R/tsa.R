#!/usr/bin/env Rscript
# =============================================================================
# DESAL Systematic Review — Trial Sequential Analysis v1.0
#
# Custom R implementation of TSA with O'Brien-Fleming alpha spending.
# NOT using Copenhagen TSA software — intentionally built from scratch for
# transparency and reproducibility.
#
# Per pipeline doc Section 4.2:
#   - O'Brien-Fleming alpha spending boundaries
#   - Two-sided alpha = 0.05, beta = 0.20 (power = 80%)
#   - RRR and control event rate derived from pooled estimates
#   - Heterogeneity adjustment via D-squared
#
# Usage:
#   Rscript tsa.R --data analysis/data/analysis_ready.csv
#   Rscript tsa.R --data analysis/data/analysis_ready.csv --outcome mortality
#   Rscript tsa.R --data analysis/data/analysis_ready.csv --outdir analysis/output/tsa_plots/
# =============================================================================

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(ggplot2)
  library(metafor)
})

# =============================================================================
# 1. ALPHA SPENDING FUNCTIONS
# =============================================================================

#' O'Brien-Fleming alpha spending function
#'
#' @param t Information fraction (0 to 1)
#' @param alpha Overall significance level
#' @return Cumulative alpha spent at information fraction t
obrien_fleming_spending <- function(t, alpha = 0.05) {
  if (t <= 0) return(0)
  if (t >= 1) return(alpha)
  # Lan-DeMets approximation of O'Brien-Fleming:
  # alpha(t) = 2 - 2 * Phi(z_{alpha/2} / sqrt(t))
  z_alpha2 <- qnorm(1 - alpha / 2)
  spent <- 2 * (1 - pnorm(z_alpha2 / sqrt(t)))
  return(spent)
}

#' Compute sequential monitoring boundaries at each analysis
#'
#' @param info_fractions Vector of cumulative information fractions
#' @param alpha Overall two-sided alpha
#' @param spending_fn Alpha spending function
#' @return Data frame with boundaries at each look
compute_boundaries <- function(info_fractions, alpha = 0.05,
                                spending_fn = obrien_fleming_spending) {
  n_looks <- length(info_fractions)
  boundaries <- numeric(n_looks)
  cum_alpha_prev <- 0

  for (i in seq_along(info_fractions)) {
    t <- info_fractions[i]
    cum_alpha <- spending_fn(t, alpha)
    incr_alpha <- cum_alpha - cum_alpha_prev

    # Incremental alpha for this look → z-boundary
    # Two-sided: each side gets incr_alpha / 2
    if (incr_alpha > 0) {
      boundaries[i] <- qnorm(1 - incr_alpha / 2)
    } else {
      boundaries[i] <- Inf  # no spending at this look
    }
    cum_alpha_prev <- cum_alpha
  }

  return(data.frame(
    look = seq_along(info_fractions),
    info_fraction = info_fractions,
    cum_alpha = sapply(info_fractions, spending_fn, alpha = alpha),
    z_boundary = boundaries
  ))
}

# =============================================================================
# 2. REQUIRED INFORMATION SIZE (RIS)
# =============================================================================

#' Calculate Required Information Size for a binary outcome
#'
#' @param pc Control event rate
#' @param RRR Relative risk reduction (e.g., 0.45 for 45% RRR)
#' @param alpha Two-sided alpha
#' @param beta Type II error rate
#' @param D2 Diversity (heterogeneity adjustment), 0-1
#' @return Required total sample size (both arms combined)
ris_binary <- function(pc, RRR, alpha = 0.05, beta = 0.20, D2 = 0) {
  pe <- pc * (1 - RRR)
  p_bar <- (pc + pe) / 2

  z_alpha <- qnorm(1 - alpha / 2)
  z_beta <- qnorm(1 - beta)

  # Sample size per arm (standard formula for RR)
  n_per_arm <- ((z_alpha + z_beta)^2 * (pc * (1 - pc) + pe * (1 - pe))) /
    (pc - pe)^2

  total_n <- 2 * n_per_arm

  # Heterogeneity adjustment
  if (D2 > 0 && D2 < 1) {
    total_n <- total_n / (1 - D2)
  }

  return(ceiling(total_n))
}

#' Calculate Required Information Size for a continuous outcome
#'
#' @param delta Minimal clinically important difference (mean difference)
#' @param sd Pooled standard deviation
#' @param alpha Two-sided alpha
#' @param beta Type II error rate
#' @param D2 Diversity (heterogeneity adjustment), 0-1
#' @return Required total sample size (both arms combined)
ris_continuous <- function(delta, sd, alpha = 0.05, beta = 0.20, D2 = 0) {
  z_alpha <- qnorm(1 - alpha / 2)
  z_beta <- qnorm(1 - beta)

  n_per_arm <- (2 * sd^2 * (z_alpha + z_beta)^2) / delta^2
  total_n <- 2 * n_per_arm

  if (D2 > 0 && D2 < 1) {
    total_n <- total_n / (1 - D2)
  }

  return(ceiling(total_n))
}

# =============================================================================
# 3. DIVERSITY (D-SQUARED) FROM META-ANALYSIS
# =============================================================================

#' Calculate D-squared from I-squared and number of studies
#'
#' D² = (I² * Q - (k-1)) / (Q - (k-1) + sum(n_i))
#' Simplified: D² ≈ I² for most practical purposes, but the proper
#' calculation uses the model variance approach.
#'
#' For TSA purposes, we use the model-variance-based D² as recommended
#' by Wetterslev et al. (2008):
#'   D² = (Q - df) / Q  when Q > df, else 0
#' This is equivalent to I² when using the DL estimator.
#'
#' @param I2 I-squared from meta-analysis
#' @param Q Cochran's Q statistic
#' @param k Number of studies
#' @return D-squared value
calculate_D2 <- function(I2, Q, k) {
  df <- k - 1
  if (Q <= df) return(0)
  D2 <- (Q - df) / Q
  return(min(D2, 0.99))  # cap at 0.99 to avoid division by zero in RIS
}

# =============================================================================
# 4. CUMULATIVE META-ANALYSIS
# =============================================================================

#' Run cumulative meta-analysis ordered by publication year
#'
#' @param df Data frame with study-level data
#' @param outcome "mortality", "los", or "readmission"
#' @return List with cumulative results, Z-values, and sample sizes
cumulative_ma <- function(df, outcome = "mortality") {
  # Sort by year
  df <- df %>% arrange(year)

  if (outcome == "mortality") {
    required <- c("mortality_events_int", "mortality_n_int",
                   "mortality_events_ctrl", "mortality_n_ctrl")
    d <- df %>% filter(!is.na(mortality_events_int), !is.na(mortality_events_ctrl))
  } else if (outcome == "los") {
    required <- c("los_mean_int", "los_sd_int", "los_n_int",
                   "los_mean_ctrl", "los_sd_ctrl", "los_n_ctrl")
    d <- df %>% filter(!is.na(los_mean_int), !is.na(los_mean_ctrl))
  } else if (outcome == "readmission") {
    required <- c("readmission_events_int", "readmission_n_int",
                   "readmission_events_ctrl", "readmission_n_ctrl")
    d <- df %>% filter(!is.na(readmission_events_int), !is.na(readmission_events_ctrl))
  } else {
    stop(sprintf("Unknown outcome: %s", outcome))
  }

  if (nrow(d) < 2) {
    message(sprintf("Fewer than 2 studies for %s TSA.", outcome))
    return(NULL)
  }

  # Cumulative analysis: at each step k, pool studies 1:k
  results <- list()
  for (k in 2:nrow(d)) {
    subset_d <- d[1:k, ]

    tryCatch({
      if (outcome == "mortality" || outcome == "readmission") {
        # Binary outcome: log-RR
        if (outcome == "mortality") {
          ai <- subset_d$mortality_events_int
          n1i <- subset_d$mortality_n_int
          ci <- subset_d$mortality_events_ctrl
          n2i <- subset_d$mortality_n_ctrl
        } else {
          ai <- subset_d$readmission_events_int
          n1i <- subset_d$readmission_n_int
          ci <- subset_d$readmission_events_ctrl
          n2i <- subset_d$readmission_n_ctrl
        }

        m <- rma(
          measure = "RR",
          ai = ai, n1i = n1i,
          ci = ci, n2i = n2i,
          method = "REML",
          data = subset_d
        )

        cum_n <- sum(n1i + n2i)
      } else {
        # Continuous outcome: MD
        m <- rma(
          measure = "MD",
          m1i = subset_d$los_mean_int,
          sd1i = subset_d$los_sd_int,
          n1i = subset_d$los_n_int,
          m2i = subset_d$los_mean_ctrl,
          sd2i = subset_d$los_sd_ctrl,
          n2i = subset_d$los_n_ctrl,
          method = "REML",
          data = subset_d
        )
        cum_n <- sum(subset_d$los_n_int + subset_d$los_n_ctrl)
      }

      results[[length(results) + 1]] <- list(
        k = k,
        study_id = subset_d$study_id[k],
        year = subset_d$year[k],
        estimate = m$beta[1],
        se = m$se,
        z_value = m$zval,
        p_value = m$pval,
        ci_lower = m$ci.lb,
        ci_upper = m$ci.ub,
        tau2 = m$tau2,
        I2 = m$I2,
        Q = m$QE,
        cum_n = cum_n
      )
    }, error = function(e) {
      message(sprintf("  Cumulative MA error at k=%d: %s", k, e$message))
    })
  }

  if (length(results) == 0) return(NULL)

  # Convert to data frame
  cum_df <- bind_rows(lapply(results, as.data.frame))
  return(cum_df)
}

# =============================================================================
# 5. TSA PLOT
# =============================================================================

#' Generate TSA plot
#'
#' @param cum_df Cumulative MA results from cumulative_ma()
#' @param ris Required information size
#' @param alpha Two-sided alpha
#' @param outcome Outcome name for title
#' @param outdir Output directory for plot
#' @return ggplot object
plot_tsa <- function(cum_df, ris, alpha = 0.05, outcome = "Mortality",
                      outdir = "analysis/output/tsa_plots/") {

  # Calculate information fractions
  cum_df$info_fraction <- cum_df$cum_n / ris

  # Compute boundaries
  info_fracs <- seq(0.01, max(1.2, max(cum_df$info_fraction) + 0.1),
                    length.out = 200)
  boundary_df <- data.frame(
    info_fraction = info_fracs,
    z_upper = sapply(info_fracs, function(t) {
      b <- compute_boundaries(t, alpha)
      b$z_boundary[1]
    }),
    z_lower = sapply(info_fracs, function(t) {
      b <- compute_boundaries(t, alpha)
      -b$z_boundary[1]
    })
  )

  # Conventional significance line
  z_conv <- qnorm(1 - alpha / 2)

  # Build plot
  p <- ggplot() +
    # TSA monitoring boundaries (O'Brien-Fleming)
    geom_line(data = boundary_df,
              aes(x = info_fraction, y = z_upper),
              color = "red", linewidth = 1, linetype = "solid") +
    geom_line(data = boundary_df,
              aes(x = info_fraction, y = z_lower),
              color = "red", linewidth = 1, linetype = "solid") +

    # Conventional significance lines
    geom_hline(yintercept = c(z_conv, -z_conv),
               linetype = "dashed", color = "gray50") +

    # Futility boundary (optional: inner boundary)
    geom_hline(yintercept = 0, linetype = "dotted", color = "gray70") +

    # Required information size line
    geom_vline(xintercept = 1.0, linetype = "dashed", color = "blue",
               linewidth = 0.5) +

    # Cumulative Z-curve
    geom_line(data = cum_df,
              aes(x = info_fraction, y = z_value),
              color = "black", linewidth = 1.2) +
    geom_point(data = cum_df,
               aes(x = info_fraction, y = z_value),
               color = "black", size = 2.5) +

    # Study labels
    geom_text(data = cum_df,
              aes(x = info_fraction, y = z_value,
                  label = paste0(study_id, "\n(", year, ")")),
              vjust = -1, size = 2.5, check_overlap = TRUE) +

    # Axis labels and theme
    scale_x_continuous(
      name = "Proportion of Required Information Size",
      labels = scales::percent_format(),
      limits = c(0, max(1.2, max(cum_df$info_fraction) + 0.1))
    ) +
    scale_y_continuous(name = "Cumulative Z-score") +
    labs(
      title = sprintf("Trial Sequential Analysis: %s", outcome),
      subtitle = sprintf(
        "RIS = %s patients | O'Brien-Fleming boundaries | α = %.2f, β = %.2f",
        format(ris, big.mark = ","), alpha, 1 - 0.80
      ),
      caption = paste0(
        "Red lines: TSA monitoring boundaries. ",
        "Dashed gray: conventional significance (z = ±",
        sprintf("%.2f", z_conv), "). ",
        "Blue dashed: required information size."
      )
    ) +
    theme_minimal(base_size = 12) +
    theme(
      plot.title = element_text(face = "bold"),
      panel.grid.minor = element_blank()
    )

  # Annotate whether Z-curve crosses boundary
  max_info <- max(cum_df$info_fraction)
  last_z <- tail(cum_df$z_value, 1)
  boundary_at_max <- compute_boundaries(max_info, alpha)$z_boundary[1]

  if (abs(last_z) >= boundary_at_max) {
    conclusion <- "Z-curve CROSSES monitoring boundary → Evidence is CONCLUSIVE"
    p <- p + annotate("text", x = 0.05, y = min(cum_df$z_value) - 1,
                       label = conclusion, hjust = 0, color = "darkgreen",
                       fontface = "bold", size = 3.5)
  } else {
    pct_ris <- max_info * 100
    conclusion <- sprintf(
      "Z-curve does not cross boundary → Evidence is INCONCLUSIVE (%.0f%% of RIS)",
      pct_ris
    )
    p <- p + annotate("text", x = 0.05, y = min(cum_df$z_value) - 1,
                       label = conclusion, hjust = 0, color = "darkred",
                       fontface = "bold", size = 3.5)
  }

  # Save
  safe_name <- gsub("[^a-zA-Z0-9]", "_", tolower(outcome))
  dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
  ggsave(file.path(outdir, paste0("tsa_", safe_name, ".pdf")),
         plot = p, width = 12, height = 8)
  ggsave(file.path(outdir, paste0("tsa_", safe_name, ".png")),
         plot = p, width = 12, height = 8, dpi = 300)

  return(p)
}

# =============================================================================
# 6. MAIN TSA RUNNER
# =============================================================================

run_tsa <- function(df, outcome, outdir, alpha = 0.05, beta = 0.20) {
  message(sprintf("\n=== TSA: %s ===", toupper(outcome)))

  # Step 1: Cumulative meta-analysis
  cum_df <- cumulative_ma(df, outcome)
  if (is.null(cum_df)) return(NULL)

  # Step 2: Compute RIS
  # Get pooled estimates from the final (all-studies) meta-analysis
  final <- tail(cum_df, 1)
  I2 <- final$I2 / 100  # metafor reports as percentage
  Q <- final$Q
  k <- final$k
  D2 <- calculate_D2(I2, Q, k)

  message(sprintf("  Final pooled estimate: %.3f (Z = %.2f, p = %.4f)",
                  final$estimate, final$z_value, final$p_value))
  message(sprintf("  I² = %.1f%%, D² = %.3f", I2 * 100, D2))

  if (outcome == "mortality" || outcome == "readmission") {
    # Derive control event rate and RRR from pooled estimate
    if (outcome == "mortality") {
      d <- df %>% filter(!is.na(mortality_events_ctrl))
      pc <- sum(d$mortality_events_ctrl) / sum(d$mortality_n_ctrl)
    } else {
      d <- df %>% filter(!is.na(readmission_events_ctrl))
      pc <- sum(d$readmission_events_ctrl) / sum(d$readmission_n_ctrl)
    }
    RRR <- 1 - exp(final$estimate)  # from log-RR
    RRR <- max(0.01, min(RRR, 0.99))  # bound

    ris <- ris_binary(pc, RRR, alpha, beta, D2)
    message(sprintf("  Control event rate: %.3f, RRR: %.3f", pc, RRR))

  } else if (outcome == "los") {
    # Continuous outcome: use pooled MD and estimated pooled SD
    delta <- abs(final$estimate)
    if (delta < 0.01) {
      message("  Pooled MD near zero. Cannot compute RIS.")
      return(NULL)
    }
    # Estimate pooled SD from the studies
    d <- df %>% filter(!is.na(los_sd_int), !is.na(los_sd_ctrl))
    pooled_sd <- sqrt(mean(c(d$los_sd_int^2, d$los_sd_ctrl^2)))

    ris <- ris_continuous(delta, pooled_sd, alpha, beta, D2)
    message(sprintf("  Pooled MD: %.2f days, Pooled SD: %.2f", delta, pooled_sd))
  }

  message(sprintf("  Required Information Size (RIS): %s patients",
                  format(ris, big.mark = ",")))
  message(sprintf("  Current information: %s patients (%.1f%% of RIS)",
                  format(tail(cum_df$cum_n, 1), big.mark = ","),
                  tail(cum_df$cum_n, 1) / ris * 100))

  # Step 3: Generate TSA plot
  p <- plot_tsa(cum_df, ris, alpha, outcome, outdir)

  # Step 4: Determine conclusion
  max_info_frac <- max(cum_df$cum_n) / ris
  last_z <- tail(cum_df$z_value, 1)
  boundary_at_max <- compute_boundaries(max_info_frac, alpha)$z_boundary[1]
  conclusive <- abs(last_z) >= boundary_at_max

  result <- list(
    outcome = outcome,
    n_studies = nrow(cum_df),
    ris = ris,
    current_n = tail(cum_df$cum_n, 1),
    info_fraction = max_info_frac,
    final_z = last_z,
    boundary_at_final = boundary_at_max,
    conclusive = conclusive,
    D2 = D2,
    I2 = I2,
    pooled_estimate = final$estimate,
    cum_results = cum_df
  )

  return(result)
}

# =============================================================================
# 7. MAIN
# =============================================================================

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)

  data_path <- "analysis/data/analysis_ready.csv"
  outdir <- "analysis/output/tsa_plots"
  outcomes <- c("mortality", "los", "readmission")

  for (i in seq_along(args)) {
    if (args[i] == "--data" && i < length(args)) data_path <- args[i + 1]
    if (args[i] == "--outdir" && i < length(args)) outdir <- args[i + 1]
    if (args[i] == "--outcome" && i < length(args)) outcomes <- args[i + 1]
  }

  df <- read_csv(data_path, show_col_types = FALSE)
  message(sprintf("Loaded %d studies", nrow(df)))

  results <- list()
  for (outcome in outcomes) {
    results[[outcome]] <- run_tsa(df, outcome, outdir)
  }

  # Print summary
  message("\n=== TSA SUMMARY ===")
  for (name in names(results)) {
    r <- results[[name]]
    if (is.null(r)) next
    message(sprintf(
      "  %s: %s | RIS=%s, Current=%s (%.0f%%), Z=%.2f vs boundary=%.2f",
      toupper(name),
      ifelse(r$conclusive, "CONCLUSIVE", "INCONCLUSIVE"),
      format(r$ris, big.mark = ","),
      format(r$current_n, big.mark = ","),
      r$info_fraction * 100,
      r$final_z,
      r$boundary_at_final
    ))
    if (!r$conclusive) {
      deficit <- r$ris - r$current_n
      message(sprintf("    → %s additional patients needed (informs DESAL sample size)",
                      format(deficit, big.mark = ",")))
    }
  }

  # Save TSA summary
  summary_rows <- lapply(results, function(r) {
    if (is.null(r)) return(NULL)
    data.frame(
      outcome = r$outcome,
      n_studies = r$n_studies,
      ris = r$ris,
      current_n = r$current_n,
      info_fraction_pct = round(r$info_fraction * 100, 1),
      final_z = round(r$final_z, 3),
      boundary = round(r$boundary_at_final, 3),
      conclusive = r$conclusive,
      D2 = round(r$D2, 3),
      I2_pct = round(r$I2 * 100, 1),
      stringsAsFactors = FALSE
    )
  })
  summary_df <- bind_rows(summary_rows)
  write_csv(summary_df, file.path(outdir, "tsa_summary.csv"))
  message(sprintf("\nTSA summary saved to %s/tsa_summary.csv", outdir))
}

if (!interactive()) main()

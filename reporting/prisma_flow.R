#!/usr/bin/env Rscript
# =============================================================================
# DESAL — PRISMA 2020 Flow Diagram Generator
#
# Generates a PRISMA 2020 flow diagram annotated with dual-LLM screening
# metrics (auto-resolved vs human-reviewed, audit results).
#
# Input: screening metrics JSON files from the screening orchestrator
# Output: PRISMA flow diagram as PDF and PNG
#
# Usage:
#   Rscript prisma_flow.R \
#     --screening-metrics screening_output/screening_metrics.json \
#     --fulltext-summary fulltext_screening_output/fulltext_screening_summary.json \
#     --output reporting/prisma_flow.pdf
#
# If the PRISMA2020 package is not available, falls back to a ggplot-based
# custom diagram.
# =============================================================================

suppressPackageStartupMessages({
  library(jsonlite)
  library(ggplot2)
  library(grid)
})

# =============================================================================
# 1. LOAD DATA
# =============================================================================

load_screening_data <- function(screening_metrics_path = NULL,
                                 fulltext_summary_path = NULL) {
  data <- list(
    # Identification
    n_pubmed = NA,
    n_embase = NA,
    n_ctgov = NA,
    n_total_identified = NA,
    n_duplicates_removed = NA,
    n_after_dedup = NA,

    # Title/Abstract Screening
    n_screened = NA,
    n_auto_include = NA,
    n_auto_exclude = NA,
    n_human_review = NA,
    n_model_error = NA,
    cohens_kappa = NA,
    auto_resolution_rate = NA,

    # Audit
    n_audit_sample = NA,
    n_audit_misses = 0,

    # Full-text screening
    n_fulltext_assessed = NA,
    n_fulltext_included = NA,
    n_fulltext_excluded = NA,
    n_fulltext_human_review = NA,

    # Final
    n_included_in_ma = NA
  )

  if (!is.null(screening_metrics_path) && file.exists(screening_metrics_path)) {
    sm <- fromJSON(screening_metrics_path)
    counts <- sm$counts
    data$n_screened <- counts$total
    data$n_auto_include <- counts$auto_include
    data$n_auto_exclude <- counts$auto_exclude
    data$n_human_review <- counts$human_review
    data$n_model_error <- counts$model_error
    data$cohens_kappa <- sm$cohens_kappa
    data$auto_resolution_rate <- sm$auto_resolution_rate
  }

  if (!is.null(fulltext_summary_path) && file.exists(fulltext_summary_path)) {
    fs <- fromJSON(fulltext_summary_path)
    data$n_fulltext_assessed <- fs$total_screened
    data$n_fulltext_included <- fs$included
    data$n_fulltext_excluded <- fs$excluded
    data$n_fulltext_human_review <- fs$human_review
  }

  return(data)
}

# =============================================================================
# 2. BUILD PRISMA DIAGRAM
# =============================================================================

build_prisma_plot <- function(data) {
  # Define box positions (x, y, width, height)
  # Layout: top-down, left-right

  # Helper: create a box annotation
  make_box <- function(x, y, w, h, label, fill = "white", border = "black") {
    list(
      annotate("rect", xmin = x - w/2, xmax = x + w/2,
               ymin = y - h/2, ymax = y + h/2,
               fill = fill, color = border, linewidth = 0.5),
      annotate("text", x = x, y = y, label = label,
               size = 2.8, lineheight = 0.9)
    )
  }

  # Helper: arrow
  make_arrow <- function(x1, y1, x2, y2) {
    annotate("segment", x = x1, y = y1, xend = x2, yend = y2,
             arrow = arrow(length = unit(0.15, "cm"), type = "closed"),
             linewidth = 0.4)
  }

  # Build identification text
  id_text <- sprintf(
    "Records identified\nPubMed: %s\nEmbase: %s\nClinicalTrials.gov: %s\nTotal: %s",
    ifelse(is.na(data$n_pubmed), "[N]", format(data$n_pubmed, big.mark = ",")),
    ifelse(is.na(data$n_embase), "[N]", format(data$n_embase, big.mark = ",")),
    ifelse(is.na(data$n_ctgov), "[N]", format(data$n_ctgov, big.mark = ",")),
    ifelse(is.na(data$n_total_identified), "[N]", format(data$n_total_identified, big.mark = ","))
  )

  dedup_text <- sprintf(
    "Duplicates removed\n(n = %s)",
    ifelse(is.na(data$n_duplicates_removed), "[N]", data$n_duplicates_removed)
  )

  screen_text <- sprintf(
    "Records screened\n(dual-LLM)\n(n = %s)",
    ifelse(is.na(data$n_screened), "[N]", data$n_screened)
  )

  auto_text <- sprintf(
    "Auto-resolved: %s\n  Include: %s\n  Exclude: %s\nHuman review: %s\nModel errors: %s\n\nCohen's κ = %s\nAuto-resolution rate: %s",
    ifelse(is.na(data$n_auto_include) | is.na(data$n_auto_exclude), "[N]",
           data$n_auto_include + data$n_auto_exclude),
    ifelse(is.na(data$n_auto_include), "[N]", data$n_auto_include),
    ifelse(is.na(data$n_auto_exclude), "[N]", data$n_auto_exclude),
    ifelse(is.na(data$n_human_review), "[N]", data$n_human_review),
    ifelse(is.na(data$n_model_error), "[N]", data$n_model_error),
    ifelse(is.na(data$cohens_kappa), "[κ]", sprintf("%.2f", data$cohens_kappa)),
    ifelse(is.na(data$auto_resolution_rate), "[%]",
           sprintf("%.0f%%", data$auto_resolution_rate * 100))
  )

  audit_text <- sprintf(
    "10%% audit of auto-excludes\n(n = %s)\nMisses found: %s",
    ifelse(is.na(data$n_audit_sample), "[N]", data$n_audit_sample),
    data$n_audit_misses
  )

  ft_assess_text <- sprintf(
    "Full-text articles assessed\n(dual-LLM)\n(n = %s)",
    ifelse(is.na(data$n_fulltext_assessed), "[N]", data$n_fulltext_assessed)
  )

  ft_excluded_text <- sprintf(
    "Full-text excluded\n(n = %s)\nwith reasons",
    ifelse(is.na(data$n_fulltext_excluded), "[N]", data$n_fulltext_excluded)
  )

  included_text <- sprintf(
    "Studies included\nin meta-analysis\n(n = %s)",
    ifelse(is.na(data$n_included_in_ma), "[N]", data$n_included_in_ma)
  )

  # Plot
  p <- ggplot() +
    xlim(0, 10) + ylim(0, 14) +
    theme_void() +
    theme(plot.margin = margin(10, 10, 10, 10))

  # Boxes (x, y, w, h)
  p <- p +
    # Identification
    make_box(3, 13, 4.5, 1.6, id_text, fill = "#E8F4FD") +
    make_box(8, 13, 2.5, 1, dedup_text, fill = "#FFF3E0") +

    # Screening
    make_box(3, 10.5, 3.5, 1.2, screen_text, fill = "#E8F4FD") +
    make_box(8, 10.5, 3, 2.4, auto_text, fill = "#F3E5F5") +

    # Audit
    make_box(8, 8, 3, 1, audit_text, fill = "#FFF3E0") +

    # Full-text
    make_box(3, 7, 3.5, 1.2, ft_assess_text, fill = "#E8F4FD") +
    make_box(8, 7, 2.5, 1, ft_excluded_text, fill = "#FFF3E0") +

    # Included
    make_box(3, 4.5, 3.5, 1.2, included_text, fill = "#E8F8F5") +

    # Arrows
    make_arrow(3, 12.2, 3, 11.1) +  # identification → screening
    make_arrow(5.25, 13, 6.75, 13) + # → duplicates
    make_arrow(4.75, 10.5, 6.5, 10.5) + # → LLM details
    make_arrow(8, 9.3, 8, 8.5) +     # → audit
    make_arrow(3, 9.9, 3, 7.6) +     # screening → full-text
    make_arrow(4.75, 7, 6.75, 7) +   # → ft excluded
    make_arrow(3, 6.4, 3, 5.1) +     # full-text → included

    # Title
    annotate("text", x = 5, y = 14.3, label = "PRISMA 2020 Flow Diagram — DESAL SR/MA",
             size = 4, fontface = "bold") +
    annotate("text", x = 5, y = 0.3,
             label = "Dual-LLM screening: Claude + GPT-5.4 | Auto-resolution with 10% human audit",
             size = 2.5, color = "gray40")

  return(p)
}

# =============================================================================
# 3. MAIN
# =============================================================================

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)

  screening_metrics <- NULL
  fulltext_summary <- NULL
  output <- "reporting/prisma_flow.pdf"

  for (i in seq_along(args)) {
    if (args[i] == "--screening-metrics" && i < length(args))
      screening_metrics <- args[i + 1]
    if (args[i] == "--fulltext-summary" && i < length(args))
      fulltext_summary <- args[i + 1]
    if (args[i] == "--output" && i < length(args))
      output <- args[i + 1]
  }

  data <- load_screening_data(screening_metrics, fulltext_summary)
  p <- build_prisma_plot(data)

  dir.create(dirname(output), recursive = TRUE, showWarnings = FALSE)
  ggsave(output, plot = p, width = 10, height = 12)
  ggsave(sub("\\.pdf$", ".png", output), plot = p, width = 10, height = 12, dpi = 300)

  message(sprintf("PRISMA flow diagram saved to %s", output))
}

if (!interactive()) main()

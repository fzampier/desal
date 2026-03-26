# DESAL Project — Agents Record

All agents working on this project MUST log their edits here. One line per action, chronological order.

Format: `Agent Name — Date: Brief description of what was done`

---

## Log

- **Claude Dispatch (Cowork)** — March 24, 2026: Created initial project folder and trial synopsis (MD + PDF) with power curves
- **Claude Dispatch (Cowork)** — March 24, 2026: Ran power simulations for D14 win ratio (Python, 2000 iterations per scenario)
- **Claude Dispatch (Cowork)** — March 24, 2026: Created formula-based sample size calculators (R + Python)
- **Claude Dispatch (Cowork)** — March 24, 2026: Conducted PubMed literature search and wrote HTS_AHF_Literature_Review.md
- **Claude Dispatch (Cowork)** — March 24, 2026: Created SR/MA protocol for PROSPERO (MD + PDF)
- **Claude Dispatch (Cowork)** — March 24, 2026: Designed dual-LLM screening pipeline specification
- **Claude Dispatch (Cowork)** — March 24, 2026: Created screening prompt template v1.0 (pre-specified before data)
- **Claude Dispatch (Cowork)** — March 24, 2026: Created screening resolution logic (confidence threshold 0.70, 10% audit with escalation)
- **Claude Dispatch (Cowork)** — March 24, 2026: Built screening orchestration script (screening_orchestrator.py)
- **Claude Dispatch (Cowork)** — March 24, 2026: Updated SR/MA protocol — added diuretic resistance subgroup, aligned study design criteria with prompt
- **Claude Dispatch (Cowork)** — March 24, 2026: Appended LLM pipeline as Appendix C to SR/MA protocol
- **Claude Dispatch (Cowork)** — March 24, 2026: Reorganized folder into trial/, srma/, pipeline/, clinical-data-extractor/ subdirectories
- **Claude Code** — March 24, 2026: Built full extraction pipeline (study_extraction.py, orchestrate_extraction.py, compare_extractions.py, llm_auditor.py)
- **Claude Code** — March 24, 2026: Built fulltext_screening.py for full-text PDF screening
- **Claude Code** — March 24, 2026: Built analysis R scripts (prepare_data.R, meta_analysis.R, tsa.R)
- **Claude Code** — March 24, 2026: Built reporting scripts (prisma_flow.R, grade_sof.R)
- **Claude Code** — March 24, 2026: Created AGENTS.md for Codex
- **Claude Dispatch (Cowork)** — March 25, 2026: Fixed hash() bug in screening_orchestrator.py (resume reliability)
- **Claude Dispatch (Cowork)** — March 25, 2026: Fixed RIS list field handling in screening_orchestrator.py
- **Claude Dispatch (Cowork)** — March 25, 2026: Fixed .data[[col]] bug in meta_analysis.R generic wrapper functions
- **Claude Dispatch (Cowork)** — March 25, 2026: Updated pipeline doc Section 3.2 to reflect actual nested Pydantic schema architecture
- **Claude Dispatch (Cowork)** — March 25, 2026: Updated build status table across all documents
- **Fernando G. Zampieri** — March 25, 2026: Manual edits to SR/MA protocol (funding: Canadian VIGOUR Centre, author table, rationale refinements)
- **Claude Dispatch (Cowork)** — March 25, 2026: Created agents_record.md audit trail; added Agents Record section to AGENTS.md and CLAUDE.md
- **Claude Code** — March 25, 2026: Added methodological decision rules to protocol (overlapping cohorts, zero-event handling, crossover trials, ambulatory population, outcome timepoint hierarchy)
- **Claude Code** — March 25, 2026: Expanded sensitivity analyses from 4 to 8 (broadened population, crossover exclusion, TACC, alternative timepoints)
- **Claude Code** — March 25, 2026: Added fuzzy title deduplication (Levenshtein ≤3) to screening_orchestrator.py
- **Claude Code** — March 25, 2026: Added natriuresis, serum chloride change, and troponin elevation as outcomes across protocol, extraction schema, prepare_data.R, meta_analysis.R, and GRADE template
- **Claude Code** — March 25, 2026: Added is_ambulatory, is_crossover, first_period_data_available, overlapping_cohort_flag, companion_publications fields to extraction schema
- **Claude Code** — March 25, 2026: Created README.md with outcomes, methodological decisions, pipeline components, requirements, and usage instructions
- **Claude Code** — March 25, 2026: Added CC BY 4.0 license
- **Claude Code** — March 25, 2026: Initialized git repo, committed all files (excluding trial/), pushed to github.com:fzampier/desal.git
- **Claude Code** — March 25, 2026: Assisted with PROSPERO registration form answers

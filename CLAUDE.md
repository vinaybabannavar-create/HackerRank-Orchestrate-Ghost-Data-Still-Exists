# CLAUDE.md

This file configures Claude Code for the HackerRank Orchestrate (October 2026) repo.

## Primary Instructions

**Read `AGENTS.md` in full before taking any action.** It is the single source of truth for this repo.  
All rules in `AGENTS.md` — logging, dataset contract, output schema, submission link — apply to Claude exactly as written.

## Quick Reference

- **Log file:** `log.txt` in the repo root. Append only. Never rewrite old entries.
- **Entry point:** `py code/main.py` — processes all 518 cases, writes `output.csv` at repo root.
- **Eval:** `py code/evaluation/generate_reports.py` — regenerates `evaluation_report.md` and `usage_report.md`.
- **Submission URL:** https://wwww.hackerrank.com/contests/hackerrank-orchestrate-october26/challenges/ghost-data-still-exists

## Tool / Model Identity (for log entries)

- `tool=` → `Claude Code`
- `model=` → exact Claude model identifier from the runtime (e.g. `claude-sonnet-4-5`). Never use `unknown`.

## What NOT to Do

- Do not use files outside `dataset/` for predictions.
- Do not hardcode case IDs, emails, resource IDs, or golden labels.
- Do not log secrets, credentials, or real personal data.
- Do not modify `dataset/` files.

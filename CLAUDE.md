# CLAUDE.md

Context for Claude Code when working in this repo.

## Purpose
Portfolio demo for freelance work: a reconciliation checker aimed at small wealth managers, family offices and bookkeepers. It should look polished and be easy to try in under a minute. All data must stay fictional.

## Architecture
- `recon/engine.py` holds all logic: `detect_columns` → `normalise` → `_match` (cash → ISIN → ticker → fuzzy name) → classify → `_explain`. It is UI-free and fully testable.
- `recon/report.py` builds the Excel report with openpyxl.
- `app.py` is a thin Streamlit layer. Keep business logic out of it.

## Conventions
- Run `python -m pytest -q` after any change to the engine. Add a test for each new break type or heuristic.
- If you change `generate_sample_data.py`, regenerate `sample_data/` and update the break counts in the tests and the app's sample toggle label.
- Use `width="stretch"` in Streamlit, not the deprecated `use_container_width`.

## Next ideas (see README roadmap)
Claude API break explanations, multi-account support, FX base-currency totals, trade-blotter matching, PDF ingestion.

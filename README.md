# Portfolio Reconciliation Checker

Compare a custodian or broker position statement against internal holdings, find every break, and get a likely cause for each one, plus an Excel exception report.

Built as a demo for small wealth managers, family offices and bookkeepers who still reconcile in spreadsheets.

## What it does

- **Reads messy files.** CSV or Excel, any column order. Headers are auto-detected (Symbol/Ticker, Shares/Qty/Units, MarketPrice/Px…) and can be remapped in the UI.
- **Matches in four passes:** cash by currency → ISIN → normalised ticker (`BRK/B` = `BRK-B` = `BRK.B`) → fuzzy security name. Name-only matches are flagged for review.
- **Classifies breaks:** quantity break, missing at custodian, missing internally, cash break, price break.
- **Suggests a cause:** for example, it detects unprocessed stock splits (exact 2:1, 3:1… quantity ratios with inverse prices), DRIP or corporate-action entitlements, stale prices and unbooked dividends.
- **Configurable tolerances** for quantity, price %, cash and name-match confidence.
- **Excel exception report** with Summary, Breaks and All Positions sheets, colour-coded with filters and frozen headers.
- Files are processed in memory and never stored.

## Run it

```bash
pip install -r requirements.txt
python generate_sample_data.py   # optional: regenerates the fictional sample files
streamlit run app.py
```

The app opens with sample data switched on: a fictional family-office account with six planted breaks, plus three traps that should *not* break (rounding inside tolerance, `BRK/B` vs `BRK.B`, a missing ISIN).

## Tests

```bash
python -m pytest -q
```

## Project layout

```
app.py                     Streamlit UI
recon/engine.py            column detection, normalisation, matching, break classification
recon/report.py            Excel report writer
generate_sample_data.py    synthetic data with planted breaks
sample_data/               generated CSVs (fictional)
tests/                     pytest suite
```

## Roadmap

- [ ] Optional Claude API "explain this break" with free-text reasoning
- [ ] Multi-account files (reconcile per account)
- [ ] FX conversion to a base currency for totals
- [ ] Trade-blotter input to auto-clear timing breaks
- [ ] PDF statement ingestion

*All sample data is fictional.*

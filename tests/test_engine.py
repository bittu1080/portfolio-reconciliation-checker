"""Run:  python -m pytest -q"""
from pathlib import Path

import pandas as pd

from recon.engine import Tolerances, detect_columns, normalise_ticker, reconcile

DATA = Path(__file__).parent.parent / "sample_data"


def run_sample(**tol):
    i = pd.read_csv(DATA / "internal_holdings.csv")
    c = pd.read_csv(DATA / "custodian_statement.csv")
    return reconcile(i, c, detect_columns(i), detect_columns(c), Tolerances(**tol))


def status_of(result, ticker):
    d = result.detail
    return d.loc[d["Ticker"] == ticker, "Status"].iloc[0]


def test_sample_finds_all_planted_breaks():
    r = run_sample()
    assert r.summary["breaks"] == 6
    assert status_of(r, "NVDA") == "Quantity break"
    assert status_of(r, "SHOP") == "Quantity break"
    assert status_of(r, "PG") == "Missing at custodian"
    assert status_of(r, "FTS") == "Missing internally"
    assert status_of(r, "ENB") == "Price break"
    assert (r.detail["Status"] == "Cash break").sum() == 1


def test_split_detected():
    r = run_sample()
    cause = r.detail.loc[r.detail["Ticker"] == "SHOP", "Suggested Cause"].iloc[0]
    assert "2-for-1" in cause


def test_tolerance_and_identifier_fallbacks():
    r = run_sample()
    assert status_of(r, "KO") == "Matched"        # 0.0004 sh rounding within tolerance
    assert status_of(r, "BRK.B") == "Matched"     # BRK/B vs BRK.B, no ISIN at custodian
    assert status_of(r, "TD") == "Matched"        # no ISIN internally -> ticker fallback


def test_loosening_price_tolerance_clears_price_break():
    assert status_of(run_sample(price_pct=10), "ENB") == "Matched"


def test_ticker_normalisation():
    assert normalise_ticker("BRK/B") == normalise_ticker("brk-b") == normalise_ticker("BRK B") == "BRK.B"
    assert normalise_ticker("AAPL US") == "AAPL"


def test_messy_headers_and_fuzzy_name_match():
    intl = pd.DataFrame({"Security Name": ["Apple Inc.", "Microsoft Corporation"],
                         "Qty": ["1,000", "250"], "Px": [228.4, 431.15]})
    cust = pd.DataFrame({"Description": ["MICROSOFT CORP COM", "APPLE INC"],
                         "Units": [250, 1000], "Market Price": [431.15, 228.4]})
    r = reconcile(intl, cust, detect_columns(intl), detect_columns(cust))
    assert set(r.detail["Status"]) == {"Matched – review ID"}

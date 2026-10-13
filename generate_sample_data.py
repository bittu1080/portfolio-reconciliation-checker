"""Generate synthetic custodian vs. internal holdings files with planted breaks.

All data is fictional. Tickers/ISINs are real public identifiers for well-known
listed companies, used only as realistic labels; quantities and prices are invented.

Run:  python generate_sample_data.py
"""
from pathlib import Path
import random

import pandas as pd

random.seed(42)
OUT = Path(__file__).parent / "sample_data"
OUT.mkdir(exist_ok=True)

AS_OF = "2026-10-09"
ACCOUNT = "ACCT-10045 (Demo Family Office)"

# ticker, isin, custodian security name, internal security name, currency, price
SECURITIES = [
    ("AAPL", "US0378331005", "APPLE INC COM", "Apple Inc.", "USD", 228.40),
    ("MSFT", "US5949181045", "MICROSOFT CORP COM", "Microsoft Corp", "USD", 431.15),
    ("NVDA", "US67066G1040", "NVIDIA CORPORATION", "NVIDIA Corp", "USD", 134.80),
    ("JPM", "US46625H1005", "JPMORGAN CHASE & CO", "JPMorgan Chase", "USD", 212.60),
    ("JNJ", "US4781601046", "JOHNSON & JOHNSON COM", "Johnson & Johnson", "USD", 161.25),
    ("RY", "CA7800871021", "ROYAL BANK OF CANADA", "Royal Bank of Canada", "CAD", 168.90),
    ("TD", "CA8911605092", "TORONTO-DOMINION BANK", "TD Bank", "CAD", 81.35),
    ("ENB", "CA29250N1050", "ENBRIDGE INC", "Enbridge Inc.", "CAD", 57.40),
    ("SHOP", "CA82509L1076", "SHOPIFY INC CL A", "Shopify Inc", "CAD", 109.70),
    ("CNR", "CA1363751027", "CANADIAN NATL RAILWAY CO", "CN Rail", "CAD", 158.20),
    ("BNS", "CA0641491075", "BANK OF NOVA SCOTIA", "Scotiabank", "CAD", 74.85),
    ("XIU", "CA46428D1087", "ISHARES S&P/TSX 60 INDEX ETF", "iShares S&P/TSX 60 ETF", "CAD", 36.10),
    ("VFV", "CA92205Y1007", "VANGUARD S&P 500 INDEX ETF", "Vanguard S&P 500 ETF", "CAD", 142.55),
    ("KO", "US1912161007", "COCA-COLA CO COM", "Coca-Cola Co", "USD", 69.90),
    ("PG", "US7427181091", "PROCTER & GAMBLE CO", "Procter & Gamble", "USD", 168.30),
    ("BRK.B", "US0846707026", "BERKSHIRE HATHAWAY INC CL B", "Berkshire Hathaway B", "USD", 461.75),
]

internal_rows, custodian_rows = [], []
for ticker, isin, cust_name, int_name, ccy, px in SECURITIES:
    qty = random.choice([100, 150, 200, 250, 300, 400, 500, 750, 1000, 1200])
    internal_rows.append(dict(Ticker=ticker, ISIN=isin, Security=int_name,
                              Quantity=qty, Price=px, Currency=ccy))
    custodian_rows.append(dict(Symbol=ticker, ISIN=isin, Description=cust_name,
                               Shares=qty, MarketPrice=px, Ccy=ccy))

internal = pd.DataFrame(internal_rows)
custodian = pd.DataFrame(custodian_rows).astype({"Shares": float})

# ---- Plant realistic breaks -------------------------------------------------
# 1. Quantity break: unbooked trade (custodian shows 50 more NVDA)
custodian.loc[custodian.Symbol == "NVDA", "Shares"] += 50
# 2. Quantity break: stock split not processed internally (SHOP 2-for-1 in custodian)
custodian.loc[custodian.Symbol == "SHOP", "Shares"] *= 2
custodian.loc[custodian.Symbol == "SHOP", "MarketPrice"] = round(109.70 / 2, 2)
# 3. Tiny rounding difference (should be within tolerance -> matched)
custodian.loc[custodian.Symbol == "KO", "Shares"] += 0.0004
# 4. Price break: stale internal price for ENB
internal.loc[internal.Ticker == "ENB", "Price"] = 54.10
# 5. Missing at custodian: position sold but still in internal books (PG)
custodian = custodian[custodian.Symbol != "PG"]
# 6. Missing internally: dividend-reinvestment position never booked
custodian = pd.concat([custodian, pd.DataFrame([dict(
    Symbol="FTS", ISIN="CA3495531079", Description="FORTIS INC", Shares=85,
    MarketPrice=61.20, Ccy="CAD")])], ignore_index=True)
# 7. Identifier mismatch: custodian uses a different symbol format for BRK.B, no ISIN
custodian.loc[custodian.Symbol == "BRK.B", ["Symbol", "ISIN"]] = ["BRK/B", ""]
# 8. Internal file missing ISIN for TD -> must fall back to ticker
internal.loc[internal.Ticker == "TD", "ISIN"] = ""

# ---- Cash lines -------------------------------------------------------------
internal_cash = pd.DataFrame([
    dict(Ticker="CASH", ISIN="", Security="Cash - CAD", Quantity=48_250.00, Price=1.0, Currency="CAD"),
    dict(Ticker="CASH", ISIN="", Security="Cash - USD", Quantity=12_400.00, Price=1.0, Currency="USD"),
])
custodian_cash = pd.DataFrame([
    dict(Symbol="CAD", ISIN="", Description="CASH CAD", Shares=48_250.00, MarketPrice=1.0, Ccy="CAD"),
    # 9. Cash break: USD dividend credited at custodian, not booked internally
    dict(Symbol="USD", ISIN="", Description="CASH USD", Shares=12_587.35, MarketPrice=1.0, Ccy="USD"),
])

internal = pd.concat([internal, internal_cash], ignore_index=True)
custodian = pd.concat([custodian, custodian_cash], ignore_index=True)
custodian = custodian.sample(frac=1, random_state=7).reset_index(drop=True)  # custodians never sort nicely

internal.insert(0, "AsOfDate", AS_OF)
internal.insert(1, "Account", ACCOUNT)
custodian.insert(0, "StatementDate", AS_OF)
custodian.insert(1, "AccountNo", "10045")

internal.to_csv(OUT / "internal_holdings.csv", index=False)
custodian.to_csv(OUT / "custodian_statement.csv", index=False)
print(f"Wrote {len(internal)} internal rows and {len(custodian)} custodian rows to {OUT}")

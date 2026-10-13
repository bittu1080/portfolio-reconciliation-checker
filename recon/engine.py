"""Core reconciliation engine: normalise two holdings files, match positions, classify breaks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
from rapidfuzz import fuzz, process

# --------------------------------------------------------------------------- #
# Column auto-detection
# --------------------------------------------------------------------------- #
FIELD_SYNONYMS = {
    "isin": ["isin", "isin code", "security isin"],
    "ticker": ["ticker", "symbol", "sym", "ticker symbol", "security id", "cusip"],
    "name": ["security", "description", "security name", "name", "security description", "asset"],
    "quantity": ["quantity", "qty", "shares", "units", "position", "holding", "par", "nominal"],
    "price": ["price", "market price", "marketprice", "px", "close price", "last price", "unit price"],
    "currency": ["currency", "ccy", "curr", "cur", "currency code"],
}
STANDARD_FIELDS = list(FIELD_SYNONYMS)
REQUIRED_FIELDS = ["quantity"]

CASH_TOKENS = {"CASH", "CAD", "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "MMF", "$CASH"}


def _clean_header(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(h).lower().replace("_", " ")).strip()


def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Guess which column in df holds each standard field."""
    cleaned = {_clean_header(c): c for c in df.columns}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for fld, synonyms in FIELD_SYNONYMS.items():
        hit = None
        for syn in synonyms:  # exact synonym first
            if syn in cleaned and cleaned[syn] not in used:
                hit = cleaned[syn]
                break
        if hit is None:  # then substring (e.g. "MarketPrice USD")
            for ch, orig in cleaned.items():
                if orig not in used and any(syn.replace(" ", "") in ch.replace(" ", "") for syn in synonyms):
                    hit = orig
                    break
        mapping[fld] = hit
        if hit:
            used.add(hit)
    return mapping


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def normalise_ticker(t) -> str:
    if pd.isna(t):
        return ""
    t = str(t).strip().upper()
    t = re.sub(r"\s+(US|CN|CT|LN|EQUITY)$", "", t)  # Bloomberg-style suffixes
    t = re.sub(r"[/\-\s]", ".", t)  # BRK/B, BRK-B, BRK B -> BRK.B
    return t


def _to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(r"[,$\s]", "", regex=True).str.replace(r"^\((.*)\)$", r"-\1", regex=True),
        errors="coerce",
    )


def normalise(df: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    missing = [f for f in REQUIRED_FIELDS if not mapping.get(f)]
    if missing:
        raise ValueError(f"Could not find a column for: {', '.join(missing)}")
    if not (mapping.get("isin") or mapping.get("ticker") or mapping.get("name")):
        raise ValueError("Need at least one identifier column (ISIN, ticker/symbol or security name).")

    out = pd.DataFrame(index=df.index)
    for fld in STANDARD_FIELDS:
        col = mapping.get(fld)
        out[fld] = df[col] if col else None
    out["row"] = df.index + 2  # spreadsheet row number (header = row 1)
    out["isin"] = out["isin"].fillna("").astype(str).str.strip().str.upper()
    out.loc[~out["isin"].str.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]"), "isin"] = ""
    out["ticker_raw"] = out["ticker"].fillna("").astype(str).str.strip()
    out["ticker"] = out["ticker"].map(normalise_ticker)
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    out["currency"] = out["currency"].fillna("").astype(str).str.strip().str.upper()
    out["quantity"] = _to_number(out["quantity"])
    out["price"] = _to_number(out["price"]) if mapping.get("price") else float("nan")

    is_cash = out["ticker"].isin(CASH_TOKENS) | out["name"].str.contains(r"\bcash\b", case=False, regex=True)
    out["is_cash"] = is_cash
    # Cash rows: currency may live in the ticker column ("USD") rather than currency column
    cash_ccy = out["currency"].where(out["currency"] != "", out["ticker"])
    out.loc[is_cash, "currency"] = cash_ccy[is_cash]
    out.loc[is_cash, "price"] = out.loc[is_cash, "price"].fillna(1.0)
    out["market_value"] = out["quantity"] * out["price"]
    out = out[out["quantity"].notna()].copy()
    return out


# --------------------------------------------------------------------------- #
# Matching & classification
# --------------------------------------------------------------------------- #
@dataclass
class Tolerances:
    qty_abs: float = 0.001          # shares
    price_pct: float = 0.5          # percent
    cash_abs: float = 1.00          # currency units
    fuzzy_score: int = 85           # 0-100, for name matching


@dataclass
class ReconResult:
    detail: pd.DataFrame
    summary: dict = field(default_factory=dict)


def _match(intl: pd.DataFrame, cust: pd.DataFrame, tol: Tolerances) -> list[tuple]:
    """Return list of (internal_idx|None, custodian_idx|None, method)."""
    pairs: list[tuple] = []
    free_i, free_c = set(intl.index), set(cust.index)

    def take(i, c, method):
        pairs.append((i, c, method))
        free_i.discard(i)
        free_c.discard(c)

    # Pass 0: cash by currency
    for i in [i for i in free_i if intl.at[i, "is_cash"]]:
        ccy = intl.at[i, "currency"]
        cand = [c for c in free_c if cust.at[c, "is_cash"] and cust.at[c, "currency"] == ccy]
        if cand:
            take(i, cand[0], "Cash currency")

    # Pass 1: ISIN, Pass 2: normalised ticker
    for key, label in (("isin", "ISIN"), ("ticker", "Ticker")):
        lookup: dict[str, list] = {}
        for c in free_c:
            k = cust.at[c, key]
            if k and not cust.at[c, "is_cash"]:
                lookup.setdefault(k, []).append(c)
        for i in sorted(free_i):
            k = intl.at[i, key]
            if k and not intl.at[i, "is_cash"] and lookup.get(k):
                c = lookup[k].pop(0)
                if c in free_c:
                    take(i, c, label)

    # Pass 3: fuzzy name within the same currency (flagged for review)
    for i in sorted(free_i):
        if intl.at[i, "is_cash"] or not intl.at[i, "name"]:
            continue
        cand = {c: cust.at[c, "name"] for c in free_c
                if not cust.at[c, "is_cash"] and cust.at[c, "name"]
                and (not intl.at[i, "currency"] or cust.at[c, "currency"] in ("", intl.at[i, "currency"]))}
        if not cand:
            continue
        best = process.extractOne(intl.at[i, "name"], cand, scorer=fuzz.token_set_ratio,
                                  processor=lambda s: re.sub(r"\b(inc|corp|co|com|ltd|cl|class|the)\b|[^a-z0-9 ]",
                                                             " ", s.lower()))
        if best and best[1] >= tol.fuzzy_score:
            take(i, best[2], f"Name ({best[1]:.0f}%)")

    pairs += [(i, None, "") for i in sorted(free_i)]
    pairs += [(None, c, "") for c in sorted(free_c)]
    return pairs


def _split_ratio(qi: float, qc: float) -> float | None:
    """Detect an unprocessed split/consolidation: quantities differ by a clean ratio."""
    if not qi or not qc:
        return None
    r = qc / qi
    for cand in (2, 3, 4, 5, 10, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10, 1.5):
        if abs(r - cand) < 1e-6:
            return cand
    return None


def _explain(row: dict) -> str:
    s, qd, pd_pct = row["Status"], row["Qty Diff"], row["Price Diff %"]
    name = row["Security"]
    if s == "Missing at custodian":
        return (f"{name} is on the internal books but not at the custodian. Check for a sale or transfer-out "
                "that settled but was not booked, or a position held at a different custodian.")
    if s == "Missing internally":
        return (f"Custodian holds {name} but it is not on the internal books. Common causes: dividend "
                "reinvestment (DRIP), corporate-action entitlement, or an unbooked purchase.")
    if s == "Cash break":
        return (f"Cash differs by {qd:+,.2f} {row['Currency']}. Look for dividends, interest, fees or FX "
                "conversions credited/debited at the custodian but not yet booked.")
    if s == "Quantity break":
        ratio = row.get("_split_ratio")
        if ratio:
            word = "split" if ratio > 1 else "consolidation"
            r_txt = f"{ratio:g}-for-1" if ratio > 1 else f"1-for-{1/ratio:g}"
            px = ""
            if pd.notna(pd_pct) and abs(pd_pct) > 0:
                px = " Prices also differ inversely, which supports this."
            return (f"Custodian quantity is exactly {ratio:g}x internal — looks like a {r_txt} stock {word} "
                    f"not yet processed internally.{px}")
        return (f"Quantity differs by {qd:+,.4g} shares. Check for an unbooked or failed trade, partial fill, "
                "or a trade-date vs settlement-date timing difference.")
    if s == "Price break":
        return (f"Quantities agree but prices differ by {pd_pct:+.2f}%. Likely a stale or differently-sourced "
                "price (close vs. last, different pricing vendor, or FX).")
    if s == "Matched – review ID":
        return "Quantities agree, but this pair was matched on security name only. Confirm it is the same security."
    return ""


def reconcile(internal_df: pd.DataFrame, custodian_df: pd.DataFrame,
              internal_map: dict, custodian_map: dict, tol: Tolerances | None = None) -> ReconResult:
    tol = tol or Tolerances()
    intl = normalise(internal_df, internal_map)
    cust = normalise(custodian_df, custodian_map)

    rows = []
    for i, c, method in _match(intl, cust, tol):
        ri = intl.loc[i] if i is not None else None
        rc = cust.loc[c] if c is not None else None
        ref = ri if ri is not None else rc
        qi = float(ri["quantity"]) if ri is not None else 0.0
        qc = float(rc["quantity"]) if rc is not None else 0.0
        pi = float(ri["price"]) if ri is not None else float("nan")
        pc = float(rc["price"]) if rc is not None else float("nan")
        mvi = qi * pi if ri is not None else 0.0
        mvc = qc * pc if rc is not None else 0.0
        qd = qc - qi
        price_pct = (pc / pi - 1) * 100 if (ri is not None and rc is not None and pi) else float("nan")
        is_cash = bool(ref["is_cash"])
        split = None

        if ri is None:
            status = "Missing internally"
        elif rc is None:
            status = "Missing at custodian"
        elif is_cash:
            status = "Cash break" if abs(qd) > tol.cash_abs else "Matched"
        elif abs(qd) > tol.qty_abs:
            status = "Quantity break"
            split = _split_ratio(qi, qc)
        elif pd.notna(price_pct) and abs(price_pct) > tol.price_pct:
            status = "Price break"
        elif method.startswith("Name"):
            status = "Matched – review ID"
        else:
            status = "Matched"

        security = (ri["name"] if ri is not None and ri["name"] else rc["name"] if rc is not None else "")
        row = {
            "Status": status,
            "Security": security,
            "Ticker": (ri["ticker_raw"] if ri is not None else "") or (rc["ticker_raw"] if rc is not None else ""),
            "ISIN": (ri["isin"] if ri is not None else "") or (rc["isin"] if rc is not None else ""),
            "Currency": ref["currency"],
            "Match Method": method or "—",
            "Internal Qty": qi if ri is not None else None,
            "Custodian Qty": qc if rc is not None else None,
            "Qty Diff": qd,
            "Internal Price": pi if ri is not None else None,
            "Custodian Price": pc if rc is not None else None,
            "Price Diff %": price_pct,
            "Internal MV": mvi,
            "Custodian MV": mvc,
            "MV Diff": mvc - mvi,
            "Internal Row": int(ri["row"]) if ri is not None else None,
            "Custodian Row": int(rc["row"]) if rc is not None else None,
            "_split_ratio": split,
        }
        row["Suggested Cause"] = _explain(row)
        rows.append(row)

    detail = pd.DataFrame(rows).drop(columns="_split_ratio")
    order = ["Quantity break", "Missing internally", "Missing at custodian", "Cash break",
             "Price break", "Matched – review ID", "Matched"]
    detail["_o"] = detail["Status"].map({s: n for n, s in enumerate(order)})
    detail["_abs"] = -detail["MV Diff"].abs()
    detail = detail.sort_values(["_o", "_abs"]).drop(columns=["_o", "_abs"]).reset_index(drop=True)

    breaks = detail[~detail["Status"].isin(["Matched"])]
    summary = {
        "positions_internal": int(len(intl)),
        "positions_custodian": int(len(cust)),
        "matched": int((detail["Status"] == "Matched").sum()),
        "breaks": int(len(breaks)),
        "by_status": detail["Status"].value_counts().reindex(order, fill_value=0).to_dict(),
        "mv_by_ccy": detail.groupby("Currency")[["Internal MV", "Custodian MV", "MV Diff"]].sum().round(2),
        "abs_break_mv_by_ccy": breaks.groupby("Currency")["MV Diff"].apply(lambda s: s.abs().sum()).round(2).to_dict(),
        "tolerances": tol,
    }
    return ReconResult(detail=detail, summary=summary)

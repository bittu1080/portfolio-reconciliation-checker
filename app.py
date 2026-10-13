"""Portfolio Reconciliation Checker — Streamlit app.

Run locally:  streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from recon.engine import STANDARD_FIELDS, Tolerances, detect_columns, reconcile
from recon.report import STATUS_FILL, build_excel

SAMPLE_DIR = Path(__file__).parent / "sample_data"
FIELD_LABELS = {"isin": "ISIN", "ticker": "Ticker / Symbol", "name": "Security name",
                "quantity": "Quantity *", "price": "Price", "currency": "Currency"}

st.set_page_config(page_title="Portfolio Reconciliation Checker", page_icon="⚖️", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1300px;}
  div[data-testid="stMetricValue"] {font-size: 1.9rem;}
  .subtle {color: #667085; font-size: 0.95rem;}
</style>""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
def read_any(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded)
    return pd.read_csv(uploaded)


def mapping_editor(label: str, df: pd.DataFrame, key: str) -> dict:
    guess = detect_columns(df)
    options = ["— none —"] + list(df.columns)
    with st.expander(f"Column mapping · {label}", expanded=not guess.get("quantity")):
        cols = st.columns(3)
        mapping = {}
        for n, fld in enumerate(STANDARD_FIELDS):
            default = options.index(guess[fld]) if guess.get(fld) in options else 0
            choice = cols[n % 3].selectbox(FIELD_LABELS[fld], options, index=default, key=f"{key}_{fld}")
            mapping[fld] = None if choice == "— none —" else choice
        st.caption("Auto-detected from your headers. Adjust if anything looks wrong.")
    return mapping


ACCENT = {"Quantity break": "D92D20", "Missing internally": "D92D20", "Missing at custodian": "D92D20",
          "Cash break": "E8590C", "Price break": "D4A20B", "Matched – review ID": "2E6FD8", "Matched": "2F9E44"}


def style_status(s: pd.Series):
    return [f"background-color: #{STATUS_FILL.get(v, 'FFFFFF')}; color:#1f2937; font-weight:600" for v in s]


# --------------------------------------------------------------------------- #
st.title("⚖️ Portfolio Reconciliation Checker")
st.markdown('<p class="subtle">Compare a custodian / broker statement against your internal holdings. '
            'Every break is classified with a likely cause, and you can download an Excel exception report. '
            'Files are processed in memory and never stored.</p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Tolerances")
    qty_tol = st.number_input("Quantity (± shares)", 0.0, 1000.0, 0.001, step=0.001, format="%.4f")
    px_tol = st.number_input("Price (± %)", 0.0, 100.0, 0.5, step=0.1)
    cash_tol = st.number_input("Cash (± currency units)", 0.0, 1e6, 1.0, step=1.0)
    fuzzy = st.slider("Name-match confidence (%)", 60, 100, 85,
                      help="Used only when neither ISIN nor ticker match. Name matches are flagged for review.")
    st.divider()
    st.caption("Matching order: cash by currency → ISIN → normalised ticker (BRK/B = BRK.B) → fuzzy name.")

c1, c2 = st.columns(2)
with c1:
    st.subheader("1 · Internal holdings")
    up_int = st.file_uploader("Your books / portfolio system export", type=["csv", "xlsx", "xls"], key="int")
with c2:
    st.subheader("2 · Custodian statement")
    up_cust = st.file_uploader("Broker / custodian position file", type=["csv", "xlsx", "xls"], key="cust")

use_sample = st.toggle("Use sample data (fictional family-office account with 6 planted breaks)",
                       value=not (up_int and up_cust))

try:
    if use_sample:
        df_int = pd.read_csv(SAMPLE_DIR / "internal_holdings.csv")
        df_cust = pd.read_csv(SAMPLE_DIR / "custodian_statement.csv")
        name_int, name_cust = "internal_holdings.csv (sample)", "custodian_statement.csv (sample)"
    elif up_int and up_cust:
        df_int, df_cust = read_any(up_int), read_any(up_cust)
        name_int, name_cust = up_int.name, up_cust.name
    else:
        st.info("Upload both files, or switch on sample data to try it.")
        st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"Could not read a file: {e}")
    st.stop()

m1, m2 = st.columns(2)
with m1:
    map_int = mapping_editor("internal", df_int, "mi")
    with st.expander(f"Preview · {name_int} ({len(df_int)} rows)"):
        st.dataframe(df_int.head(25), width="stretch", hide_index=True)
with m2:
    map_cust = mapping_editor("custodian", df_cust, "mc")
    with st.expander(f"Preview · {name_cust} ({len(df_cust)} rows)"):
        st.dataframe(df_cust.head(25), width="stretch", hide_index=True)

tol = Tolerances(qty_abs=qty_tol, price_pct=px_tol, cash_abs=cash_tol, fuzzy_score=fuzzy)
try:
    result = reconcile(df_int, df_cust, map_int, map_cust, tol)
except ValueError as e:
    st.error(str(e))
    st.stop()

detail, summ = result.detail, result.summary
st.divider()
st.subheader("Results")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Positions compared", len(detail))
k2.metric("Matched", summ["matched"])
k3.metric("Breaks to review", summ["breaks"])
brk = detail[detail["Status"] != "Matched"]
if len(brk):
    top = brk.loc[brk["MV Diff"].abs().idxmax()]
    k4.metric("Largest break", f"{top['Currency']} {abs(top['MV Diff']):,.0f}", help=f"{top['Security']} — {top['Status']}")
    st.caption(f"Largest break: **{top['Security']}** ({top['Status'].lower()})")
else:
    k4.metric("Largest break", "—")
    st.success("Fully reconciled — no breaks outside tolerance. 🎉")

chips = " ".join(
    f'<span style="background:#{STATUS_FILL[s]};color:#1f2937;padding:4px 10px;border-radius:999px;'
    f'margin:0 6px 6px 0;display:inline-block;font-size:0.85rem;font-weight:600">{s}: {n}</span>'
    for s, n in summ["by_status"].items() if n)
st.markdown(chips, unsafe_allow_html=True)

with st.expander("Market value by currency"):
    mv = summ["mv_by_ccy"].copy()
    mv["Gross Break MV"] = mv.index.map(summ["abs_break_mv_by_ccy"]).fillna(0)
    st.dataframe(mv.style.format("{:,.2f}"), width="stretch")

show_all = st.toggle("Show matched positions too", value=False)
view = detail if show_all else detail[detail["Status"] != "Matched"]
statuses = st.multiselect("Filter by status", list(summ["by_status"]),
                          default=[s for s in summ["by_status"] if s in set(view["Status"])])
view = view[view["Status"].isin(statuses)]

def fmt_qty(v, sign=False):
    if v is None or pd.isna(v):
        return "—"
    s = f"{v:+,.4f}" if sign else f"{v:,.4f}"
    return s.rstrip("0").rstrip(".")


cols = ["Status", "Security", "Ticker", "Currency", "Internal Qty", "Custodian Qty", "Qty Diff",
        "Price Diff %", "MV Diff", "Match Method"]
table = view[cols].copy()
num = lambda c: pd.to_numeric(table[c], errors="coerce")
table["Internal Qty"] = num("Internal Qty").map(fmt_qty)
table["Custodian Qty"] = num("Custodian Qty").map(fmt_qty)
table["Qty Diff"] = num("Qty Diff").map(lambda v: fmt_qty(v, True))
table["Price Diff %"] = num("Price Diff %").map(lambda v: "—" if pd.isna(v) else f"{v:+.2f}")
table["MV Diff"] = num("MV Diff").map(lambda v: f"{v:+,.2f}")
st.dataframe(table.style.apply(style_status, subset=["Status"]),
             width="stretch", hide_index=True, height=min(600, 36 * (len(view) + 1) + 4))

notes = view[view["Suggested Cause"] != ""]
if len(notes):
    st.markdown("#### Investigation notes")
    for _, r in notes.iterrows():
        st.markdown(
            f'<div style="border-left:4px solid #{ACCENT[r["Status"]]};padding:6px 12px;margin-bottom:8px">'
            f'<b>{r["Security"]}</b> <span class="subtle">· {r["Status"]}</span><br>{r["Suggested Cause"]}</div>',
            unsafe_allow_html=True)

as_of = None
for df, col in ((df_int, "AsOfDate"), (df_cust, "StatementDate")):
    if col in df.columns:
        as_of = str(df[col].iloc[0])
        break

d1, d2, _ = st.columns([1, 1, 3])
d1.download_button("⬇️ Excel exception report", build_excel(result, name_int, name_cust, as_of),
                   file_name="reconciliation_report.xlsx", type="primary",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
d2.download_button("⬇️ Breaks (CSV)", detail[detail["Status"] != "Matched"].to_csv(index=False),
                   file_name="breaks.csv", mime="text/csv")

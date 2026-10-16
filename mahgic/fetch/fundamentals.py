"""Stage 3a — statements from Yahoo (T3): up to 8 quarters and 5 fiscal years.

Fixes from v1:
- every B3 row is pulled (OCF, receivables, CWIP, shares, equity, capex), not five;
- missing stays None (v1 filled 0, so a real zero and a gap looked the same);
- no FX conversion: figures stay in `financialCurrency`, which is recorded.
  v1 applied today's spot rate to every quarter, which bent historical trends.
"""
from __future__ import annotations

import logging
import math

import pandas as pd

log = logging.getLogger("mahgic")

ROWS = {
    "income": {
        "revenue": ["Total Revenue", "Operating Revenue"],
        "gross_profit": ["Gross Profit"],
        "operating_income": ["Operating Income", "EBIT"],
        "net_income": ["Net Income Common Stockholders", "Net Income"],
        "eps_diluted": ["Diluted EPS"],
        "ebitda": ["EBITDA", "Normalized EBITDA"],
        "tax_rate": ["Tax Rate For Calcs"],
        "diluted_shares": ["Diluted Average Shares"],
    },
    "balance": {
        "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
        "total_debt": ["Total Debt"],
        "receivables": ["Accounts Receivable", "Receivables"],
        "equity": ["Stockholders Equity", "Common Stock Equity"],
        "shares_out": ["Ordinary Shares Number", "Share Issued"],
        "cwip": ["Construction In Progress"],
        "total_assets": ["Total Assets"],
    },
    "cashflow": {
        "ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
                "Cash Flowsfromusedin Operating Activities Direct"],  # direct method, common on ASX
        "capex": ["Capital Expenditure"],
        "fcf": ["Free Cash Flow"],
        "buybacks": ["Repurchase Of Capital Stock"],
        "issuance": ["Issuance Of Capital Stock", "Common Stock Issuance"],
        "sbc": ["Stock Based Compensation"],
    },
}


def _series(df: pd.DataFrame | None, names: list[str], n: int) -> list[float | None]:
    if df is None or df.empty:
        return []
    for name in names:
        if name in df.index:
            vals = df.loc[name].head(n).tolist()
            return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in vals]
    return []


def _dates(df: pd.DataFrame | None, n: int) -> list[str]:
    if df is None or df.empty:
        return []
    return [c.strftime("%Y-%m-%d") for c in df.columns[:n]]


def fetch(ticker: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(ticker)
    out: dict = {"ticker": ticker, "source": "yahoo", "tier": "T3"}
    frames = {
        "quarterly": {"income": t.quarterly_income_stmt, "balance": t.quarterly_balance_sheet,
                      "cashflow": t.quarterly_cashflow},
        "annual": {"income": t.income_stmt, "balance": t.balance_sheet, "cashflow": t.cashflow},
    }
    for period, n in (("quarterly", 8), ("annual", 5)):
        block: dict = {"dates": {}}
        for kind, rows in ROWS.items():
            df = frames[period][kind]
            block["dates"][kind] = _dates(df, n)
            for key, names in rows.items():
                block[key] = _series(df, names, n)
        out[period] = block
    try:
        info = t.info or {}
    except Exception:
        info = {}
    out["currency"] = info.get("financialCurrency") or info.get("currency")
    out["quote_currency"] = info.get("currency")
    out["has_quarterly"] = bool(out["quarterly"]["revenue"])
    if not out["has_quarterly"]:
        # ASX and many small caps report half-yearly: B3 says use halves + 5 years, mark (est.)
        out["note"] = "No quarterly data from Yahoo; use annual series and filings (half-yearly reporter?)"
    return out

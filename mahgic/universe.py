"""Stage 1 — Universe: the list of tickers a run covers.

Sources: a CSV in config/universes/ (column `ticker`), or a Yahoo screener
query (needs query1/query2.finance.yahoo.com reachable). No Wikipedia scraping.
"""
from __future__ import annotations

import logging

import pandas as pd

from .config import CONFIG_DIR, RunContext

log = logging.getLogger("mahgic")


def from_csv(name: str) -> pd.DataFrame:
    df = pd.read_csv(CONFIG_DIR / "universes" / name)
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df.drop_duplicates("ticker").reset_index(drop=True)


def from_yahoo_screener(q: dict, page: int = 250, max_rows: int = 5000) -> pd.DataFrame:
    import yfinance as yf
    from yfinance import EquityQuery as Q

    parts = [
        Q("eq", ["region", q.get("region", "us")]),
        Q("is-in", ["exchange", *q["exchanges"]]),
        Q("btwn", ["intradaymarketcap", *q["market_cap"]]),
    ]
    if q.get("min_price"):
        parts.append(Q("gt", ["intradayprice", q["min_price"]]))
    if q.get("positive_fcf"):
        parts.append(Q("gt", ["leveredfreecashflow.lasttwelvemonths", 0]))
    if q.get("positive_ocf"):
        parts.append(Q("gt", ["cashfromoperations.lasttwelvemonths", 0]))
    if q.get("min_insider_pct"):
        parts.append(Q("gte", ["pctheldinsider", q["min_insider_pct"]]))
    query = Q("and", parts)

    rows, offset = [], 0
    while offset < max_rows:
        r = yf.screen(query, offset=offset, size=page, sortField="intradaymarketcap", sortAsc=False)
        quotes = r.get("quotes", [])
        rows += [{"ticker": x["symbol"], "name": x.get("shortName"), "sector": x.get("sector")} for x in quotes]
        if len(quotes) < page:
            break
        offset += page
    log.info("Yahoo screener returned %d tickers", len(rows))
    return pd.DataFrame(rows).drop_duplicates("ticker").reset_index(drop=True)


def load(ctx: RunContext) -> pd.DataFrame:
    cfg = ctx.universe_cfg
    if "csv" in cfg:
        df = from_csv(cfg["csv"])
    elif "yahoo_screener" in cfg:
        df = from_yahoo_screener(cfg["yahoo_screener"])
    else:
        raise ValueError(f"Universe {ctx.universe} has no csv or yahoo_screener source")
    df.to_csv(ctx.dir / "universe.csv", index=False)
    return df

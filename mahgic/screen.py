"""Stage 2 — Phase 0 screen (base_layer.md A7, playbook Phase 0).

Six tests, one point each. Missing data is "unknown", never a pass or a fail
by default: a test with no data scores None and the row is marked incomplete.
Banks and insurers are flagged and not scored. The screen labels tracks
(hidden_gem / fallen_quality); it never cuts a company for being large.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .config import RunContext, scoring
from .store import Store

log = logging.getLogger("mahgic")

HIDDEN_GEM_MAX_CAP = {"USD": 5e9, "AUD": 2e9, "INR": 2e11}


def fetch_info(ticker: str, tries: int = 3) -> dict:
    import yfinance as yf

    for attempt in range(tries):
        try:
            info = yf.Ticker(ticker).info
            if info and info.get("marketCap"):
                return info
        except Exception as e:  # yfinance raises many types on rate limits
            log.debug("%s info attempt %d: %s", ticker, attempt + 1, e)
        time.sleep(2 * (attempt + 1))
    return {}


def _ok(v) -> bool:
    return v is not None


def phase0(info: dict, fcf_prev: float | None = None, cfg: dict | None = None) -> dict:
    """Score one company. `fcf_prev` is last fiscal year's FCF, for the >50% fall test."""
    c = (cfg or scoring())["phase0"]
    g = info.get
    cash, debt, ebitda = g("totalCash"), g("totalDebt"), g("ebitda")
    ocf, fcf, ni = g("operatingCashflow"), g("freeCashflow"), g("netIncomeToCommon")
    price = g("currentPrice") or g("regularMarketPrice")
    high = g("fiftyTwoWeekHigh")
    insiders = g("heldPercentInsiders")
    fpe = g("forwardPE")
    industry = (g("industry") or "").lower()
    sector = g("sector") or ""

    drawdown = (1 - price / high) if _ok(price) and high else None
    is_fin = any(k in industry for k in c["financial_industries"])

    def survival():
        if not _ok(cash) or not _ok(debt):
            return None
        if cash >= debt:
            return True
        if _ok(ebitda) and ebitda > 0:
            return (debt - cash) < c["survival_net_debt_ebitda_max"] * ebitda
        return False

    def cash_real():
        if not _ok(ocf):
            return None
        return ocf > 0 and (not _ok(ni) or ocf >= ni)

    # Yahoo's info FCF is levered FCF and can exceed operating cash flow (84 of 433 US
    # small caps in Oct 2026). Treat that as unknown rather than a pass.
    fcf_suspect = _ok(fcf) and _ok(ocf) and fcf > ocf > 0

    def fcf_ok():
        if not _ok(fcf) or fcf_suspect:
            return None
        if fcf <= 0:
            return False
        if _ok(fcf_prev) and fcf_prev > 0:
            return fcf >= (1 - c["fcf_max_yoy_fall"]) * fcf_prev
        return True

    lo, hi = c["forward_pe"]
    tests = {
        "t1_survival": survival(),
        "t2_cash_real": cash_real(),
        "t3_fcf": fcf_ok(),
        "t4_curable_dip": None if drawdown is None else drawdown >= c["curable_dip_min_drawdown"],
        # Yahoo's insider % includes corporate parents and PE; B5 re-checks it from filings.
        "t5_skin_in_game": None if not _ok(insiders) else insiders * 100 >= c["insider_min_pct"],
        "t6_not_pricey": None if not _ok(fpe) else lo < fpe <= hi,
    }
    known = [v for v in tests.values() if v is not None]
    currency = g("currency") or "USD"
    mcap = g("marketCap")
    return {
        "ticker": info.get("symbol"),
        "name": g("shortName") or g("longName"),
        "sector": sector,
        "industry": g("industry"),
        "currency": currency,
        "market_cap": mcap,
        "price": price,
        "drawdown_from_high": None if drawdown is None else round(drawdown, 3),
        "forward_pe": None if fpe is None else round(fpe, 1),
        "insider_pct": None if insiders is None else round(insiders * 100, 1),
        "cash": cash, "debt": debt, "ocf": ocf, "fcf": fcf, "net_income": ni,
        **tests,
        "score": None if is_fin else sum(bool(v) for v in known),
        "tests_missing": 6 - len(known),
        "flag_financial": is_fin,
        "flag_cyclical": sector in c["cyclical_sectors"],  # judge on mid-cycle EPS
        "flag_deep_drawdown": drawdown is not None and drawdown > c["deep_drawdown_checklist"],
        # Yahoo counts parents/governments/PE as insiders (REA: News Corp). Large stakes need a B5 look.
        "flag_fcf_suspect": bool(fcf_suspect),
        # Statements in another currency than the quote (e.g. CHA reports in CNY): $ ratios unreliable
        "flag_currency_mismatch": bool(g("financialCurrency") and g("currency") and g("financialCurrency") != g("currency")),
        "flag_insider_check": insiders is not None and insiders >= 0.20,
        # Coverage, not size, is the better "hidden" test (Oct 2026 run: ASX gems had 7-9 brokers)
        "analyst_count": g("numberOfAnalystOpinions"),
        "track": "hidden_gem" if mcap and mcap < HIDDEN_GEM_MAX_CAP.get(currency, 5e9) else "fallen_quality",
    }


def assign_tracks(df: pd.DataFrame, ctx: RunContext, cfg: dict | None = None) -> pd.DataFrame:
    """Playbook B1 v1.2 tracks. Oct 2026: the screen used size alone (A$2b), so only 26 of 196
    ASX names were Hidden gems; by the playbook's tests it is 88."""
    t = (cfg or scoring()).get("tracks") or {}
    mkt, uni = ctx.market, ctx.universe
    size_max = float((t.get("size_max") or {}).get(df["currency"].mode()[0] if not df.empty else "USD", 5e9))
    analysts_max = (t.get("analysts_max") or {}).get(mkt, 5)
    if uni in (t.get("index_member_universes") or []):
        in_index = pd.Series(True, index=df.index)
    elif (t.get("index_top_n") or {}).get(mkt):
        n = t["index_top_n"][mkt]
        in_index = df["market_cap"].rank(ascending=False, method="first") <= n
    else:
        in_index = pd.Series(False, index=df.index)
    small = df["market_cap"].fillna(0) <= size_max
    few = df["analyst_count"].apply(lambda a: a is not None and not pd.isna(a) and a <= analysts_max)
    passed = small.astype(int) + (~in_index).astype(int) + few.astype(int)
    fallen = df["drawdown_from_high"].fillna(0) >= t.get("fallen_min_drawdown", 0.30)
    df = df.copy()
    df["less_known_tests_passed"] = passed
    df["track"] = ["hidden_gem" if p >= 2 else ("fallen_quality" if f else "large")
                   for p, f in zip(passed, fallen)]
    return df


def _prev_year_fcf(fund: dict | None) -> float | None:
    """Annual series are newest first; index 1 is the prior fiscal year."""
    series = ((fund or {}).get("annual") or {}).get("fcf") or []
    return series[1] if len(series) > 1 else None


def run(ctx: RunContext, universe: pd.DataFrame, workers: int = 3, force: bool = False) -> pd.DataFrame:
    store = Store(ctx)
    todo = [t for t in universe["ticker"] if force or not store.has(t, "info")]
    log.info("Screen: %d to fetch, %d cached", len(todo), len(universe) - len(todo))

    def work(t):
        info = fetch_info(t)
        if info:
            info.setdefault("symbol", t)
            store.save(t, "info", info)
        return t, bool(info)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, ok in ex.map(work, todo):
            if not ok:
                log.warning("No Yahoo data for %s", t)

    rows = []
    for t in universe["ticker"]:
        info = store.load(t, "info")
        if info:
            rows.append(phase0(info, fcf_prev=_prev_year_fcf(store.load(t, "fundamentals"))))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    excl = [x.lower() for x in (scoring().get("exclude_industries") or [])]
    if excl:
        drop = df["industry"].fillna("").str.lower().apply(lambda s: any(x in s for x in excl))
        if drop.any():
            log.info("Screen: excluded %d (%s): %s", int(drop.sum()), ", ".join(excl),
                     ", ".join(df.loc[drop, "ticker"]))
        df = df[~drop]
    df = df.sort_values(["score", "drawdown_from_high"], ascending=[False, False], na_position="last")

    top_n = ctx.universe_cfg.get("top_n_by_market_cap")
    if top_n:
        df = df.sort_values("market_cap", ascending=False).head(top_n)
        df = df.sort_values(["score", "drawdown_from_high"], ascending=[False, False], na_position="last")

    df = assign_tracks(df, ctx)
    df.to_csv(ctx.dir / "screen.csv", index=False)
    missing = sorted(set(universe["ticker"]) - set(df["ticker"])) if not top_n else []
    log.info("Screen: %d scored, %d financials, %d no data", df["score"].notna().sum(),
             int(df["flag_financial"].sum()), len(missing))
    return df

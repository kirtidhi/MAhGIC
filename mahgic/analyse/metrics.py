"""Stage 4a — B3 metrics, computed in Python so the LLM never does arithmetic.

All inputs are newest-first series that may contain None. Every metric returns
None when its inputs are missing; the thesis prints "n/a (missing)" for those.
"""
from __future__ import annotations


def _first(xs, n=1):
    vals = [x for x in (xs or []) if x is not None]
    return vals[:n] if n > 1 else (vals[0] if vals else None)


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def cagr(series: list, years: int | None = None) -> float | None:
    vals = [v for v in (series or []) if v is not None]
    if len(vals) < 2:
        return None
    n = (len(vals) - 1) if years is None else min(years, len(vals) - 1)
    new, old = vals[0], vals[n]
    if old is None or old <= 0 or new is None or new <= 0 or n == 0:
        return None
    return (new / old) ** (1 / n) - 1


def trend(series: list) -> str | None:
    """'up' / 'down' / 'flat' / 'mixed' over a newest-first series."""
    vals = [v for v in (series or []) if v is not None][::-1]
    if len(vals) < 3:
        return None
    ups = sum(b > a for a, b in zip(vals, vals[1:]))
    downs = sum(b < a for a, b in zip(vals, vals[1:]))
    steps = len(vals) - 1
    if ups >= 0.7 * steps:
        return "up"
    if downs >= 0.7 * steps:
        return "down"
    if abs(vals[-1] - vals[0]) <= 0.05 * abs(vals[0] or 1):
        return "flat"
    return "mixed"


def margins(num: list, den: list) -> list:
    return [_div(a, b) for a, b in zip(num or [], den or [])]


def compute(info: dict, fund: dict, cfg: dict) -> dict:
    a = (fund or {}).get("annual", {})
    q = (fund or {}).get("quarterly", {})
    g = info.get

    rev, ni, ocf, fcf = a.get("revenue"), a.get("net_income"), a.get("ocf"), a.get("fcf")
    recv, cash, debt = a.get("receivables"), a.get("cash"), a.get("total_debt")
    equity, shares = a.get("equity"), a.get("shares_out")
    ebit, tax = a.get("operating_income"), a.get("tax_rate")

    rev0, ni0, ocf0, fcf0 = _first(rev), _first(ni), _first(ocf), _first(fcf)
    recv0, cash0, debt0, eq0 = _first(recv), _first(cash), _first(debt), _first(equity)
    ebitda0 = g("ebitda") or _first(a.get("ebitda"))

    receivable_days = _div(recv0 * 365 if recv0 is not None else None, rev0)
    recv_growth = cagr(recv, 1)
    rev_growth_1y = cagr(rev, 1)

    tax0 = _first(tax)
    nopat = None if _first(ebit) is None else _first(ebit) * (1 - (tax0 if tax0 is not None else 0.25))
    invested = None if None in (debt0, eq0, cash0) else debt0 + eq0 - cash0
    roic = _div(nopat, invested) if invested and invested > 0 else None

    sh = [s for s in (shares or []) if s is not None]
    dilution = None if len(sh) < 2 else (sh[0] / sh[1] - 1) * 100

    fcf_yoy = None
    if fcf and len(fcf) > 1 and fcf[0] is not None and fcf[1] not in (None, 0):
        fcf_yoy = (fcf[0] - fcf[1]) / abs(fcf[1])

    mcap = g("marketCap")
    out = {
        "currency": (fund or {}).get("currency"),
        "revenue_latest": rev0,
        "revenue_cagr_5y": cagr(rev),
        "revenue_growth_1y": rev_growth_1y,
        "revenue_trend_8q": trend(q.get("revenue")),
        "eps_trend_5y": trend(a.get("eps_diluted")),
        "eps_trend_8q": trend(q.get("eps_diluted")),
        "gross_margin": margins(a.get("gross_profit"), rev),
        "operating_margin": margins(ebit, rev),
        "operating_margin_trend": trend(margins(ebit, rev)),
        "ocf_to_ni": _div(ocf0, ni0) if ni0 and ni0 > 0 else None,
        "cash_is_real": None if ocf0 is None else (ocf0 > 0 and (ni0 is None or ocf0 >= ni0)),
        "fcf_latest": fcf0,
        "fcf_yoy_change": fcf_yoy,
        "fcf_fell_over_50pct": None if fcf_yoy is None else fcf_yoy < -cfg["phase0"]["fcf_max_yoy_fall"],
        "net_debt": None if None in (debt0, cash0) else debt0 - cash0,
        "net_debt_to_ebitda": None if None in (debt0, cash0) or not ebitda0 or ebitda0 <= 0 else (debt0 - cash0) / ebitda0,
        "net_cash": None if None in (debt0, cash0) else cash0 >= debt0,
        "receivable_days": receivable_days,
        "receivables_outgrowing_revenue": None if None in (recv_growth, rev_growth_1y) else recv_growth > rev_growth_1y + 0.05,
        "roic": roic,
        "roic_below_min": None if roic is None else roic < cfg["flags"]["roic_min"],
        "share_change_pct_1y": dilution,
        "cwip_latest": _first(a.get("cwip")),
        "cwip_trend": trend(a.get("cwip")),
        "sbc_to_revenue": _div(_first(a.get("sbc")), rev0),
        # statement FCF over market cap, only when both are in the same currency
        "fcf_yield": _div(fcf0, mcap) if (fund or {}).get("currency") == (fund or {}).get("quote_currency") else None,
        "earnings_yield": _div(1, g("forwardPE")) if g("forwardPE") and g("forwardPE") > 0 else None,
        "forward_pe": g("forwardPE"),
        "trailing_pe": g("trailingPE"),
        "ev_to_ebitda": g("enterpriseToEbitda"),
        "pe_5y_median_proxy": None,  # needs price history x EPS; filled by valuation.py when added
        "analyst_count": g("numberOfAnalystOpinions"),
        "data_gaps": [],
    }
    for k in ("revenue_latest", "ocf_to_ni", "receivable_days", "roic", "share_change_pct_1y", "net_debt_to_ebitda"):
        if out[k] is None:
            out["data_gaps"].append(k)
    if not (fund or {}).get("has_quarterly"):
        out["data_gaps"].append("quarterly series (half-yearly reporter: use 4D/4E, mark est.)")
    return out

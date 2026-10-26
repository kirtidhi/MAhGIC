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


def _median(xs):
    v = sorted(x for x in (xs or []) if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def valuation_test(m: dict, cfg: dict) -> dict:
    """A6 part 2 (price), decided in code: <=15x mid-cycle earnings or FCF yield above the
    local 10y. SBC-heavy companies are judged on FCF after SBC (MNDY Oct 2026: 8.1% pre-SBC,
    ~3.5% after), cyclicals on mid-cycle (median 5-year) EPS (VLO at peak refining margins)."""
    h = cfg["hypothetical_8"]
    bond = m.get("bond_10y")
    if m.get("is_financial"):
        rp = m.get("return_on_price")
        if rp is None or bond is None:
            return {"passes": None, "basis": "bank/insurer: ROE or price-to-book unavailable"}
        hurdle = bond + cfg["flags"].get("financial_equity_premium_pct", 2.0)
        return {"passes": rp * 100 > hurdle, "basis": f"bank/insurer: ROE {m['roe']:.1%} / P/B {m['price_to_book']:.2f} "
                f"= {rp:.1%} return on price vs hurdle {hurdle:.2f}% (10y + premium)"}
    if m.get("is_cyclical") and m.get("mid_cycle_pe") is not None:
        ok = 0 < m["mid_cycle_pe"] <= h["max_mid_cycle_pe"]
        return {"passes": ok, "basis": f"cyclical: price / median 5y EPS = {m['mid_cycle_pe']:.1f}x"
                + (" (latest EPS at peak)" if m.get("eps_at_peak") else "")}
    if m.get("sbc_material"):
        y = m.get("fcf_yield_after_sbc")
        if y is None or bond is None:
            return {"passes": None, "basis": "SBC material but FCF after SBC or 10y unavailable"}
        return {"passes": y * 100 > bond, "basis": f"SBC {m['sbc_to_revenue']:.0%} of revenue: FCF yield after SBC "
                f"{y:.1%} vs 10y {bond}%"}
    fpe, y = m.get("forward_pe"), m.get("fcf_yield")
    checks = []
    if fpe is not None:
        checks.append((0 < fpe <= h["max_mid_cycle_pe"], f"forward P/E {fpe:.1f}x"))
    if y is not None and bond is not None:
        checks.append((y * 100 > bond, f"FCF yield {y:.1%} vs 10y {bond}%"))
    if not checks:
        return {"passes": None, "basis": "no valuation data"}
    return {"passes": any(c for c, _ in checks), "basis": "; ".join(b for _, b in checks)}


def compute(info: dict, fund: dict, cfg: dict, bond_10y: float | None = None) -> dict:
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
    same_ccy = (fund or {}).get("currency") == (fund or {}).get("quote_currency")
    sbc0 = _first(a.get("sbc"))
    sbc_ratio = _div(sbc0, rev0)
    fcf_after_sbc = None if fcf0 is None else fcf0 - (sbc0 or 0)
    price = g("currentPrice") or g("regularMarketPrice")
    eps = a.get("eps_diluted")
    eps0, eps_med = _first(eps), _median(eps)
    industry = (g("industry") or "").lower()
    is_cyc = ((g("sector") or "") in cfg["phase0"]["cyclical_sectors"]
              or any(k in industry for k in cfg["phase0"].get("cyclical_industries", [])))
    is_fin = any(k in industry for k in cfg["phase0"]["financial_industries"])
    pb, roe = g("priceToBook"), g("returnOnEquity")
    out = {
        # Banks and insurers are judged on capital returns, not industrial cash-flow tests
        "is_financial": is_fin,
        "roe": roe if is_fin else None,
        "price_to_book": pb if is_fin else None,
        "return_on_price": (roe / pb) if is_fin and roe is not None and pb and pb > 0 else None,
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
        "sbc_to_revenue": sbc_ratio,
        "sbc_material": None if sbc_ratio is None else sbc_ratio > cfg["flags"].get("sbc_material_pct", 0.05),
        # statement FCF over market cap, only when both are in the same currency
        "fcf_yield": _div(fcf0, mcap) if same_ccy else None,
        "fcf_after_sbc": fcf_after_sbc,
        "fcf_yield_after_sbc": _div(fcf_after_sbc, mcap) if same_ccy and sbc0 is not None else None,
        "bond_10y": bond_10y,
        "is_cyclical": is_cyc,
        "eps_latest": eps0,
        "eps_median_5y": eps_med,
        "eps_at_peak": None if not (eps0 and eps_med and eps_med > 0) else eps0 >= cfg["flags"].get("peak_eps_ratio", 1.5) * eps_med,
        "mid_cycle_pe": _div(price, eps_med) if same_ccy and price and eps_med and eps_med > 0 else None,
        "earnings_yield": _div(1, g("forwardPE")) if g("forwardPE") and g("forwardPE") > 0 else None,
        "forward_pe": g("forwardPE"),
        "trailing_pe": g("trailingPE"),
        "ev_to_ebitda": g("enterpriseToEbitda"),
        "pe_5y_median_proxy": None,  # needs price history x EPS; filled by valuation.py when added
        "analyst_count": g("numberOfAnalystOpinions"),
        "data_gaps": [],
    }
    out["valuation_test"] = valuation_test(out, cfg)
    for k in ("revenue_latest", "ocf_to_ni", "receivable_days", "roic", "share_change_pct_1y", "net_debt_to_ebitda"):
        if out[k] is None:
            out["data_gaps"].append(k)
    if not (fund or {}).get("has_quarterly"):
        out["data_gaps"].append("quarterly series (half-yearly reporter: use 4D/4E, mark est.)")
    return out

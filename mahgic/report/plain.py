"""Plain-English rendering for the thesis files (Nov 2026).

The local drafts cite their evidence as machine lines ("revenue_growth_1y:-0.0383",
"ROIC 0.006031211615203917", "cash:11704000512.0, debt:63480000512.0 (SCREEN)"). Kirti read the
combined report and compared it with the June Gemini write-ups, which a non-investor can follow.
This module turns evidence lines into short sentences, with no model call: known keys get a
template, other lines get their numbers rounded and percentages shown as percentages.
It also renders the leadership block (Yahoo officer list + insider and leadership flags) and the
"What it does / Why it matters now" block written by `python -m mahgic describe`.
"""
from __future__ import annotations

import json
import re

SOURCE_TAG = re.compile(r"\s*\((?:METRICS|SCREEN|FILINGS|HIRING|RED FLAGS|INSIDER TRADES|GUIDANCE HISTORY|FACTS)\)\s*$")
KV = re.compile(r"^([a-z][a-z0-9_]*)\s*[:=]\s*(.*)$", re.S)
PCT_WORDS = re.compile(r"(?i)\b(roic|roe|yield|growth|margin|cagr|return|share|change|drawdown)\b")


def money(v: float, cur: str = "") -> str:
    a = abs(v)
    s = f"{v/1e12:.2f} trillion" if a >= 1e12 else f"{v/1e9:.2f}bn" if a >= 1e9 else f"{v/1e6:.0f}m" if a >= 1e6 else f"{v:,.0f}"
    return f"{cur} {s}".strip()


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _num(s):
    try:
        return float(str(s).strip().strip('"').split()[0].rstrip(","))
    except (ValueError, IndexError):
        return None


def _boolish(s: str):
    s = str(s).strip().strip('"').lower()
    return True if s == "true" else False if s == "false" else None


# key -> function(value_text, cur) -> sentence (None = drop the line)
def _t(fmt_true, fmt_false=None):
    return lambda v, c: fmt_true if _boolish(v) else (fmt_false if _boolish(v) is False else None)


TEMPLATES = {
    "forward_pe": lambda v, c: f"Priced at {_num(v):.1f} times next year's expected earnings" if _num(v) else None,
    "trailing_pe": lambda v, c: f"Priced at {_num(v):.1f} times last year's earnings" if _num(v) else None,
    "mid_cycle_pe": lambda v, c: f"Priced at {_num(v):.1f} times its average (mid-cycle) earnings" if _num(v) else None,
    "insider_pct": lambda v, c: f"Insiders own {_num(v):.1f}% of the shares (Yahoo figure)" if _num(v) is not None else None,
    "ocf_to_ni": lambda v, c: (f"Operating cash flow is {_num(v):.2f} times reported profit"
                               + (" (cash backs up the profit)" if _num(v) >= 1 else " (less cash than profit)")) if _num(v) is not None else None,
    "revenue_growth_1y": lambda v, c: f"Revenue {'grew' if _num(v) >= 0 else 'fell'} {abs(_num(v))*100:.1f}% last year" if _num(v) is not None else None,
    "revenue_cagr_5y": lambda v, c: f"Revenue grew {_num(v)*100:.1f}% a year over five years" if _num(v) is not None else None,
    "fcf_yield": lambda v, c: f"Free cash flow is {_num(v)*100:.1f}% of the market value (free cash flow yield)" if _num(v) is not None else None,
    "net_debt_to_ebitda": lambda v, c: f"Net debt is {_num(v):.1f} times yearly operating earnings (EBITDA)" if _num(v) is not None else None,
    "net_debt": lambda v, c: (f"Net debt {money(_num(v), c)}" if _num(v) > 0 else f"Net cash {money(-_num(v), c)}") if _num(v) is not None else None,
    "debt": lambda v, c: f"Total debt {money(_num(v), c)}" if _num(v) is not None else None,
    "fcf": lambda v, c: f"Free cash flow {money(_num(v), c)} last year" if _num(v) is not None else None,
    "fcf_latest": lambda v, c: f"Free cash flow {money(_num(v), c)} last year" if _num(v) is not None else None,
    "net_income": lambda v, c: f"Net profit {money(_num(v), c)} last year" if _num(v) is not None else None,
    "revenue_latest": lambda v, c: f"Revenue {money(_num(v), c)} last year" if _num(v) is not None else None,
    "market_cap": lambda v, c: f"Market value {money(_num(v), c)}" if _num(v) is not None else None,
    "roic": lambda v, c: f"Return on invested capital {_num(v)*100:.1f}%" if _num(v) is not None else None,
    "roe": lambda v, c: f"Return on equity {_num(v)*100:.1f}%" if _num(v) is not None else None,
    "price_to_book": lambda v, c: f"Priced at {_num(v):.2f} times book value" if _num(v) is not None else None,
    "gross_margin": lambda v, c: f"Gross margin {_num(v)*100:.1f}%" if _num(v) is not None else None,
    "earnings_yield": lambda v, c: f"Earnings yield {_num(v)*100:.1f}%" if _num(v) is not None else None,
    "receivable_days": lambda v, c: f"Customers take about {_num(v):.0f} days to pay" if _num(v) is not None else None,
    "share_change_pct_1y": lambda v, c: f"Share count {'up' if _num(v) >= 0 else 'down'} {abs(_num(v)):.1f}% in a year" if _num(v) is not None else None,
    "bond_10y": lambda v, c: f"Local 10-year government bond yield {_num(v):.2f}% (the hurdle)" if _num(v) is not None else None,
    "eps_latest": lambda v, c: f"Latest earnings per share {_num(v):.2f}" if _num(v) is not None else None,
    "director_interest": lambda v, c: f"{_num(v):.0f} director share-dealing notices: check buys against sells" if _num(v) else None,
    "capital_raise": lambda v, c: f"{_num(v):.0f} capital-raising announcements in the window" if _num(v) else None,
    "open_market_sales": lambda v, c: f"{_num(v):.0f} insider share sales on market" if _num(v) else None,
    "eps_trend_5y": lambda v, c: f"Earnings per share over five years: {v.strip()}",
    "eps_trend_8q": lambda v, c: f"Earnings per share over eight quarters: {v.strip()}",
    "revenue_trend_8q": lambda v, c: f"Revenue over eight quarters: {v.strip()}",
    "operating_margin_trend": lambda v, c: f"Operating margin trend: {v.strip()}",
    "sector": lambda v, c: f"Sector: {v.strip()}",
    "industry": lambda v, c: f"Industry: {v.strip()}",
    "currency": lambda v, c: None,
    "track": lambda v, c: None,
    "is_cyclical": _t("A cyclical business: earnings rise and fall with the economy or commodity prices", "Not a cyclical business"),
    "flag_cyclical": _t("A cyclical business: earnings rise and fall with the economy or commodity prices", None),
    "cash_is_real": _t("Reported cash looks real (backed by operating cash flow)", "Reported cash may not be real: check it"),
    "t2_cash_real": _t("Reported cash looks real (backed by operating cash flow)", "Reported cash may not be real: check it"),
    "net_cash": _t("More cash than debt (net cash)", "More debt than cash"),
    "t1_survival": _t("Passes the survival test (can ride out a bad year)", "Fails the survival test"),
    "t5_skin_in_game": _t("Insiders have meaningful money in the shares", "Insiders own little of the company"),
    "skin_in_game": _t("Insiders have meaningful money in the shares", "Insiders own little of the company"),
    "t6_not_pricey": _t("Not expensive on the price test", "Expensive on the price test"),
    "roic_below_min": _t("Return on capital is below 10%", None),
    "fcf_fell_over_50pct": _t("Free cash flow fell by more than half last year", None),
    "receivables_outgrowing_revenue": _t("Money owed by customers is growing faster than sales", None),
    "is_financial": _t("A bank, insurer or other financial: judged on returns on equity, not cash flow", None),
    "flag_financial": _t("A bank, insurer or other financial: judged on returns on equity, not cash flow", None),
    "flag_insider_check": _t("Insider figure needs checking (may be a parent company or fund)", None),
    "flag_deep_drawdown": _t("Share price is far below its high", None),
    "flag_currency_mismatch": _t("Accounts are reported in a different currency from the share price: check the numbers", None),
    "going_concern": lambda v, c: None if v.strip() in ("[]", "") else f"Going-concern wording in the filings: {v.strip()[:160]}",
    "material_weakness": lambda v, c: None if v.strip() in ("[]", "") else f"Material weakness in controls: {v.strip()[:160]}",
    "status": lambda v, c: "No job-board feed found, so hiring is not judged" if "no_ats" in v else f"Status: {v.strip()}",
    "latest_buy": lambda v, c: None if v.strip() in ("null", "None", "") else f"Latest insider buy: {v.strip()}",
}

NO_DATA = {"no_ats_feed": "No job-board feed found, so hiring is not judged"}


def _tidy_numbers(s: str, cur: str = "") -> str:
    """Round long decimals and shorten big numbers inside free text."""
    def big(m):
        v = float(m.group(0))
        return money(v) if abs(v) >= 1e6 else m.group(0)

    s = re.sub(r"(?<![\w.])\d{7,}(?:\.\d+)?(?![\w.])", big, s)

    def small(m):
        label, v = m.group(1), float(m.group(2))
        if abs(v) < 1.5 and PCT_WORDS.search(label):
            return f"{label}{pct(v)}"
        return f"{label}{v:.2f}"

    s = re.sub(r"([A-Za-z/ ()_-]{0,40}?[\s:=])(-?\d+\.\d{3,})", small, s)
    return s


def evidence(e, cur: str = "") -> str | None:
    """One evidence line, in plain English. None = drop it (a false flag, an empty list)."""
    if isinstance(e, (dict, list)):
        e = json.dumps(e)
    e = SOURCE_TAG.sub("", str(e)).strip()
    if re.match(r'^"[A-Za-z]', e):  # a JSON fragment the model wrote: "revenue_growth_1y":-0.03
        e = e[1:]
        if e.endswith('"') and not re.search(r':\s*"[^"]*"$', e):
            e = e[:-1]
    if e.startswith("RED FLAGS") and "{" in e:  # the model pasted the red-flag JSON back
        try:
            rf = json.loads(e[e.index("{"):])
            items = [c.get("why") for c in rf.get("hard_caps", [])] + list(rf.get("notes", []))
            return "; ".join(x for x in (evidence(i, cur) for i in items if i) if x) or None
        except Exception:
            pass
    e = re.sub(r'""(?=[a-z_]+")', ', "', e)  # "cash":4.0e8""debt":2.2e8
    brace = e.find("{")
    head, tail = (e, "") if brace < 0 else (e[:brace], e[brace:])
    e = (re.sub(r'(^|,\s*)"?([a-z][a-z0-9_]*)"\s*:', r"\1\2:", head) + tail).strip()
    if e in NO_DATA:
        return NO_DATA[e]
    m = KV.match(e)
    if m:
        k, v = m.group(1), m.group(2).strip()
        if len(v) > 1 and v[0] == v[-1] == '"':
            v = v[1:-1]
        if v.startswith("[") and v.endswith("]"):
            try:
                lst = json.loads(v)
                if not lst:
                    return None
                if all(isinstance(x, str) for x in lst):
                    v = "; ".join(lst)
                elif all(isinstance(x, dict) for x in lst):
                    v = "; ".join(f"{x.get('date', '')} {x.get('headline') or x.get('why') or ''}".strip() for x in lst)
            except Exception:
                pass
        if "," in v and re.match(r"^[\d.\-e+]+,\s*[a-z_]+\s*:", v.strip()):  # "cash:1.2e10, debt:6.3e10"
            parts = [evidence(p.strip(), cur) for p in re.split(r",\s*(?=[a-z_]+\s*:)", f"{k}:{v}")]
            return "; ".join(p for p in parts if p) or None
        if k == "cash" and _num(v) is not None:
            return f"Cash {money(_num(v), cur)}"
        if k == "ocf" and _num(v) is not None:
            return f"Operating cash flow {money(_num(v), cur)} last year"
        if k == "valuation_test":
            try:
                vt = json.loads(v)
                return ("Passes the price test" if vt.get("passes") else "Fails the price test") + \
                       (f": {vt['basis']}" if vt.get("basis") else "")
            except Exception:
                pass
        if k == "count_negative" or "count_negative" in e:
            n = _num(v)
            return None if n is None else ("No guidance cuts found in the results releases read" if n == 0
                                           else f"{n:.0f} guidance cuts or misses found in the results releases")
        if k in TEMPLATES:
            try:
                return TEMPLATES[k](v, cur)
            except Exception:
                return _tidy_numbers(f"{k.replace('_', ' ').capitalize()}: {v}", cur)
        if _boolish(v) is False or v.strip() in ("[]", "{}", "null", "None", "0"):
            return None
        return _tidy_numbers(f"{k.replace('_', ' ').capitalize()}: {v.strip()}", cur)
    return _tidy_numbers(e, cur)


def evidence_list(items, cur: str = "") -> list[str]:
    out = []
    for e in items or []:
        s = evidence(e, cur)
        if s and s not in out:
            out.append(s[0].upper() + s[1:] if s else s)
    return out


def gap(g: str) -> str:
    g = str(g)
    if "no_ats_feed" in g or "job-board" in g:
        return "no job-board feed, so hiring is not judged"
    if "half-yearly" in g:
        return "reports half-yearly, so quarterly trends are estimated"
    return g


# ---------- leadership ----------
def leadership(info: dict, redflags: dict | None = None, filings: dict | None = None, limit: int = 5) -> list[str]:
    off = (info or {}).get("companyOfficers") or []
    L = []
    for o in off[:limit]:
        name = re.sub(r"\s+", " ", (o.get("name") or "").strip())
        name = re.sub(r"\s+(B\.?\s?bus|CA|CPA|J\.D\.|Ph\.?D\.?|M\.?B\.?A\.?)[\w.,\s]*$", "", name).strip(" ,")
        if not name:
            continue
        age = o.get("age")
        L.append(f"- **{name}**, {o.get('title') or 'officer'}" + (f", age {age}" if age else ""))
    ins = (info or {}).get("heldPercentInsiders")
    if ins is not None:
        note = " (likely a parent company or strategic holder, not founder skin)" if ins >= 0.5 else ""
        L.append(f"- Insiders own {ins:.1%} of the shares (Yahoo){note}")
    founders = [o.get("name") for o in off if "founder" in (o.get("title") or "").lower()]
    if founders:
        names = ", ".join(re.sub(r"\s+", " ", f or "") for f in founders[:2])
        L.append(f"- Founder still involved: {names}")
    fl = ((filings or {}).get("flags") or {}) if isinstance((filings or {}).get("flags"), dict) else {}
    for h in (fl.get("leadership_change") or [])[:3]:
        L.append(f"- {h['date']}: {h['headline']}")
    sec_changes = sorted({n.split()[0] for n in (redflags or {}).get("notes", []) if "5.02" in n}, reverse=True)
    if sec_changes:
        L.append(f"- {len(sec_changes)} director or officer change{'s' if len(sec_changes) > 1 else ''} "
                 f"filed with the SEC (8-K item 5.02), latest {sec_changes[0]}")
    return L or ["- No officer list available from Yahoo"]


# ---------- describe ----------
def describe_block(desc: dict | None, info: dict | None) -> list[str]:
    L = ["## What it does"]
    if desc and desc.get("what_it_does"):
        L.append(desc["what_it_does"])
    elif (info or {}).get("longBusinessSummary"):
        s = info["longBusinessSummary"]
        L.append(" ".join(re.split(r"(?<=\.)\s+", s)[:2]))
    else:
        L.append("No description available.")
    L += ["", "## Why it matters now"]
    if desc and desc.get("why_now"):
        L.append(desc["why_now"])
        if desc.get("quote_verified"):
            L.append(f"> {desc['quote']}")
            L.append(f"*Source: {desc.get('source') or 'latest results release'}*")
        elif desc.get("quote"):
            L.append("*The supporting quote was not found in the document: treat this paragraph as unverified.*")
    else:
        L.append("Not written yet (run `python -m mahgic describe`).")
    return L

"""Stage 3b — SEC EDGAR (T1) for US companies.

- company_tickers.json  -> CIK
- submissions/CIK.json  -> filing list: 8-K items (4.01 auditor change, 4.02
                           non-reliance, 5.02 officer exit), NT 10-K/10-Q, Form 4, DEF 14A
- companyfacts/CIK.json -> XBRL annual figures to cross-check Yahoo (T3 vs T1)
- latest 10-K           -> full text, split into Items. v1 cut at 60k characters,
                           which dropped most of Item 1A and MD&A; 2.0 keeps every
                           Item and the draft stage reads them in chunks.

SEC asks for <=10 requests a second and a User-Agent with a contact email.
"""
from __future__ import annotations

import logging
import re
import time
from functools import lru_cache

import requests

from ..config import contact_email

log = logging.getLogger("mahgic")

_last_call = [0.0]


def _get(url: str, **kw) -> requests.Response:
    wait = 0.15 - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    headers = {"User-Agent": f"MAhGIC research {contact_email()}", "Accept-Encoding": "gzip, deflate"}
    for attempt in range(3):
        r = requests.get(url, headers=headers, timeout=30, **kw)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


@lru_cache
def ticker_map() -> dict[str, int]:
    data = _get("https://www.sec.gov/files/company_tickers.json").json()
    return {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in data.values()}


def cik_for(ticker: str) -> int | None:
    return ticker_map().get(ticker.upper().replace(".", "-"))


def submissions(cik: int) -> dict:
    return _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()


def company_facts(cik: int) -> dict:
    return _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()


def recent_filings(sub: dict) -> list[dict]:
    r = sub.get("filings", {}).get("recent", {})
    keys = ["accessionNumber", "filingDate", "form", "primaryDocument", "items"]
    n = len(r.get("form", []))
    return [{k: (r.get(k) or [None] * n)[i] for k in keys} for i in range(n)]


RED_FLAG_ITEMS = {
    "4.01": "auditor change",
    "4.02": "non-reliance on prior financials (restatement)",
    "5.02": "director/officer departure or appointment",
    "2.06": "material impairment",
    "3.01": "delisting notice",
}


def filing_flags(filings: list[dict], since: str) -> dict:
    """Red-flag events in the filing list since an ISO date (B4 / B5)."""
    events = []
    for f in filings:
        if (f["filingDate"] or "") < since:
            continue
        form = f["form"] or ""
        if form.startswith("NT "):
            events.append({"date": f["filingDate"], "flag": f"late filing ({form})"})
        if form == "8-K" and f.get("items"):
            for item in str(f["items"]).split(","):
                item = item.strip()
                if item in RED_FLAG_ITEMS:
                    events.append({"date": f["filingDate"], "flag": f"8-K {item}: {RED_FLAG_ITEMS[item]}",
                                   "accession": f["accessionNumber"]})
    counts = {}
    for f in filings:
        if (f["filingDate"] or "") >= since:
            counts[f["form"]] = counts.get(f["form"], 0) + 1
    return {"since": since, "events": events, "form_counts": counts}


def doc_url(cik: int, f: dict) -> str:
    acc = f["accessionNumber"].replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{f['primaryDocument']}"


def latest(filings: list[dict], forms: tuple[str, ...]) -> dict | None:
    return next((f for f in filings if f["form"] in forms), None)


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml") if _has_lxml() else BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "ix:header"]):
        t.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\xa0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


ITEM_RE = re.compile(r"^\s*item\s+(1a|1b|1c|1|2|3|4|5|6|7a|7|8|9a|9b|9|10|11|12|13|14|15|16)\s*[\.:\-—–]",
                     re.IGNORECASE | re.MULTILINE)


def split_items(text: str) -> dict[str, str]:
    """Split a 10-K into Items. The table of contents also matches, so for each
    Item keep the longest span (the real section, not the TOC line)."""
    marks = [(m.start(), m.group(1).upper()) for m in ITEM_RE.finditer(text)]
    sections: dict[str, str] = {}
    for i, (pos, item) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end].strip()
        if len(body) > len(sections.get(item, "")):
            sections[item] = body
    return sections


KEY_PHRASES = {
    "going_concern": r"substantial doubt (?:about|regarding) (?:the company'?s|our) ability to continue as a going concern",
    "material_weakness": r"material weakness(?:es)? in (?:our )?internal control",
    "customer_concentration": r"(?:one|two|three|single) customers? (?:accounted|represented) for (?:approximately )?\d+%",
    "atm_program": r"at[- ]the[- ]market (?:offering|program|equity)",
}


def scan_phrases(text: str) -> dict[str, list[str]]:
    hits = {}
    for key, pat in KEY_PHRASES.items():
        found = []
        for m in re.finditer(pat, text, re.IGNORECASE):
            s = max(0, m.start() - 200)
            found.append(text[s:m.end() + 200].replace("\n", " "))
            if len(found) >= 3:
                break
        hits[key] = found
    return hits


XBRL_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "shares_out": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
    "cwip": ["ConstructionInProgressGross"],
}


def annual_facts(facts: dict, years: int = 5) -> dict:
    """Latest `years` fiscal-year (10-K, FY) values per tag, newest first."""
    out = {}
    pools = {**facts.get("facts", {}).get("us-gaap", {}), **facts.get("facts", {}).get("dei", {})}
    for key, tags in XBRL_TAGS.items():
        for tag in tags:
            units = pools.get(tag, {}).get("units", {})
            vals = units.get("USD") or units.get("shares") or []
            fy = [v for v in vals if v.get("form") == "10-K" and v.get("fp") == "FY"]
            if not fy:
                continue
            by_end = {}
            for v in sorted(fy, key=lambda v: v.get("filed", "")):
                by_end[v["end"]] = v["val"]  # later filings restate earlier ones
            ends = sorted(by_end, reverse=True)[:years]
            out[key] = {"tag": tag, "ends": ends, "values": [by_end[e] for e in ends]}
            break
    return out


def fetch(ticker: str, since: str, with_10k: bool = True) -> dict:
    cik = cik_for(ticker)
    if not cik:
        return {"ticker": ticker, "error": "no CIK (not an SEC filer?)"}
    sub = submissions(cik)
    filings = recent_filings(sub)
    out = {
        "ticker": ticker, "cik": cik, "name": sub.get("name"), "tier": "T1",
        "flags": filing_flags(filings, since),
        "form4_count_since": sum(1 for f in filings if f["form"] == "4" and f["filingDate"] >= since),
        "latest": {k: latest(filings, forms) for k, forms in {
            "10-K": ("10-K", "10-K/A"), "10-Q": ("10-Q",), "DEF 14A": ("DEF 14A",), "20-F": ("20-F",)}.items()},
    }
    try:
        out["xbrl_annual"] = annual_facts(company_facts(cik))
    except requests.HTTPError as e:
        out["xbrl_annual"] = {"error": str(e)}
    tenk = out["latest"]["10-K"] or out["latest"]["20-F"]
    if with_10k and tenk:
        url = doc_url(cik, tenk)
        text = html_to_text(_get(url).text)
        items = split_items(text)
        out["10k"] = {"url": url, "filed": tenk["filingDate"], "chars": len(text),
                      "items": {k: len(v) for k, v in items.items()}, "phrases": scan_phrases(text)}
        out["_10k_items"] = items  # stored separately by the pipeline
    return out

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
    "1.05": "material cybersecurity incident",
    "2.05": "restructuring / layoffs (exit or disposal costs)",
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
# Some filers' HTML breaks the word across a line ("Ite\nm 1A."), so the real headings were
# missed and only the table of contents matched (CPRT FY26: every Item ~30 chars, Item 16
# holding the whole 318k-char filing). Re-join the word before splitting.
_BROKEN_ITEM = re.compile(r"(?im)^(\s*)i\s?t\s?e\s?m(?=\s*\n?\s*\d{1,2}[a-c]?\s*[\.:\-—–])")
_ITEM_NEWLINE = re.compile(r"(?im)^(\s*item)\s*\n\s*(\d{1,2}[a-c]?\s*[\.:\-—–])")

# 20-F Items differ from 10-K: 3 = key information incl. 3.D risk factors, 4 = the business,
# 5 = operating and financial review (MD&A), 8 = financial information incl. legal proceedings.
READ_ORDER = {"10-K": ("1A", "7", "3", "1"), "20-F": ("3", "5", "8", "4")}
# (a 20-F's "D. Risk factors" sits inside Item 3; the title fallback can also file it as "1A")

TITLES = {  # fallback when the Item headings cannot be found
    "1A": r"(?:d\.\s*)?risk factors",
    "7": r"management[’']s discussion and analysis of financial condition",
    "3": r"legal proceedings",
    "5": r"operating and financial review and prospects",  # 20-F
}


def _normalise(text: str) -> str:
    text = _BROKEN_ITEM.sub(lambda m: m.group(1) + "Item", text)
    return _ITEM_NEWLINE.sub(lambda m: m.group(1) + " " + m.group(2), text)


def split_items(text: str) -> dict[str, str]:
    """Split a 10-K / 20-F into Items. The table of contents also matches, so for each
    Item keep the longest span (the real section, not the TOC line)."""
    text = _normalise(text)
    marks = [(m.start(), m.group(1).upper()) for m in ITEM_RE.finditer(text)]
    sections: dict[str, str] = {}
    for i, (pos, item) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end].strip()
        if len(body) > len(sections.get(item, "")):
            sections[item] = body
    if len(text) > 50_000:
        small = [k for k in TITLES if len(sections.get(k, "")) < 3_000]
        if small:
            found = _split_by_titles(text, sections)
            sections.update({k: v for k, v in found.items() if k in small and len(v) >= 3_000})
    return sections


def _split_by_titles(text: str, found: dict[str, str]) -> dict[str, str]:
    """Last resort: find each section by its title on its own line (skip the TOC by taking
    the occurrence followed by the most text before the next title)."""
    out = {}
    hits = []
    for key, pat in TITLES.items():
        for m in re.finditer(rf"(?im)^\s*(?:item\s*\d+[a-c]?\s*[\.:\-—–]?\s*)?{pat}\s*$", text):
            hits.append((m.start(), key))
    hits.sort()
    for i, (pos, key) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else min(len(text), pos + 200_000)
        body = text[pos:end].strip()
        if len(body) > len(out.get(key, found.get(key, ""))):
            out[key] = body
    return out


KEY_PHRASES = {
    "going_concern": r"substantial doubt (?:about|regarding) (?:the company'?s|our) ability to continue as a going concern",
    "material_weakness": r"material weakness(?:es)? in (?:our )?internal control",
    "customer_concentration": r"(?:one|two|three|single) customers? (?:accounted|represented) for (?:approximately )?\d+%",
    "atm_program": r"at[- ]the[- ]market (?:offering|program|equity)",
    # Negative events Claude found by searching in Oct 2026 (CPRT DOJ probe, MNDY class action)
    "investigation": r"(?:department of justice|\bDOJ\b|grand jury|subpoena|civil investigative demand|"
                     r"wells notice|(?:SEC|FTC|ACCC|ASIC)\s+(?:investigation|inquiry|enforcement))",
    "class_action": r"(?:securities|shareholder|putative) class action",
}
# Risk-factor boilerplate ("if we identify a material weakness...") is not a disclosure of one.
_HYPOTHETICAL = re.compile(r"\b(?:if|could|may|might|any|no|not|future|whether|were to|would)\b[^.]{0,80}$", re.I)


def scan_phrases(text: str) -> dict[str, list[str]]:
    hits = {}
    for key, pat in KEY_PHRASES.items():
        found, last = [], -1000
        for m in re.finditer(pat, text, re.IGNORECASE):
            before = text[max(0, m.start() - 120):m.start()]
            if key in ("material_weakness", "going_concern") and _HYPOTHETICAL.search(before):
                continue
            if found and m.start() - last < 300:  # same sentence, already quoted
                continue
            last = m.start()
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


def slice_longest(text: str, start: str, ends: list[str], max_chars: int = 80_000) -> str:
    """Longest span from a heading matching `start` to the next heading matching any of `ends`
    (the longest skips the table of contents)."""
    best = ""
    for m in re.finditer(rf"(?im)^\s*(?:item\s*\d+[a-c]?\s*[\.:\-—–]?\s*)?{start}", text):
        line = text[m.start():text.find("\n", m.end()) if text.find("\n", m.end()) > 0 else len(text)]
        if re.search(r"\s\d{1,3}\s*$", line):  # table-of-contents line ("Legal Proceedings 20")
            continue
        tail = text[m.start():m.start() + max_chars]
        cut = min((e.start() for pat in [start, *ends] for e in re.finditer(rf"(?im)^\s*(?:item\s*\d+[a-c]?\s*[\.:\-—–]?\s*)?{pat}", tail)
                   if e.start() > 200), default=len(tail))
        if cut > len(best):
            best = tail[:cut].strip()
    return best


def tenq_items(text: str) -> dict[str, str]:
    """The parts of a 10-Q that change between annual reports: MD&A, legal proceedings,
    risk-factor updates (read after each earnings release)."""
    text = _normalise(text)
    out = {
        "Q_MDA": slice_longest(text, r"management[’']s discussion and analysis",
                               [r"quantitative and qualitative disclosures", r"controls and procedures"]),
        "Q_LEGAL": slice_longest(text, r"legal proceedings", [r"risk factors", r"unregistered sales"], 30_000),
        "Q_RISK": slice_longest(text, r"risk factors", [r"unregistered sales", r"defaults upon senior",
                                                         r"other information", r"exhibits"], 40_000),
    }
    return {k: v for k, v in out.items() if len(v) > 400}


def _form4_xml_url(cik: int, f: dict) -> str:
    acc = f["accessionNumber"].replace("-", "")
    doc = re.sub(r"^xsl[^/]+/", "", f["primaryDocument"] or "")  # raw XML, not the XSL-rendered view
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"


def parse_form4(xml: str) -> list[dict]:
    """Open-market buys (P) and sales (S) from one Form 4 (B5 insider trades)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xml, "xml") if _has_lxml() else BeautifulSoup(xml, "html.parser")
    def val(node, tag):
        x = node.find(tag) if node else None
        v = x.find("value") if x and x.find("value") else x
        return v.get_text(strip=True) if v else None
    name = val(soup, "rptOwnerName")
    rel = soup.find("reportingOwnerRelationship")
    role = []
    if rel:
        if val(rel, "isDirector") in ("1", "true"):
            role.append("director")
        if val(rel, "isOfficer") in ("1", "true"):
            role.append(val(rel, "officerTitle") or "officer")
        if val(rel, "isTenPercentOwner") in ("1", "true"):
            role.append("10% owner")
    plan = val(soup, "aff10b5One") in ("1", "true")
    out = []
    for t in soup.find_all("nonDerivativeTransaction"):
        code = val(t, "transactionCode")
        if code not in ("P", "S"):
            continue
        try:
            sh = float(val(t, "transactionShares") or 0)
            px = float(val(t, "transactionPricePerShare") or 0)
        except ValueError:
            sh, px = 0.0, 0.0
        out.append({"date": val(t, "transactionDate"), "who": name, "role": ", ".join(role) or "other",
                    "type": "buy" if code == "P" else "sell", "shares": sh, "value": round(sh * px),
                    "rule_10b5_1": plan})
    return out


def insider_trades(cik: int, filings: list[dict], since: str, limit: int = 25) -> dict:
    forms = [f for f in filings if f["form"] == "4" and (f["filingDate"] or "") >= since][:limit]
    trades, errors = [], 0
    for f in forms:
        try:
            trades += parse_form4(_get(_form4_xml_url(cik, f)).text)
        except Exception:
            errors += 1
    buys = [t for t in trades if t["type"] == "buy"]
    sells = [t for t in trades if t["type"] == "sell"]
    by_person: dict = {}
    for t in trades:
        k = (t["who"], t["role"])
        d = by_person.setdefault(k, {"who": t["who"], "role": t["role"], "bought": 0, "sold": 0, "planned_sales": 0})
        d["bought" if t["type"] == "buy" else "sold"] += t["value"]
        if t["type"] == "sell" and t["rule_10b5_1"]:
            d["planned_sales"] += t["value"]
    top = sorted(by_person.values(), key=lambda d: -(d["bought"] + d["sold"]))[:6]
    return {"tier": "T1", "forms_read": len(forms), "errors": errors,
            "open_market_buys": len(buys), "buy_value": sum(t["value"] for t in buys),
            "open_market_sales": len(sells), "sell_value": sum(t["value"] for t in sells),
            "by_person": top, "latest_buy": max((t["date"] for t in buys), default=None)}


RESALE_FORMS = ("S-3", "S-3ASR", "F-3", "F-3ASR", "S-1", "F-1")


def resale_and_planned_sales(filings: list[dict], since: str) -> dict:
    """Registered shelves (may cover a founder or VC stake: ITRN F-3ASR May 2026) and
    Form 144 notices of planned insider sales."""
    shelves = [{"date": f["filingDate"], "form": f["form"]} for f in filings
               if f["form"] in RESALE_FORMS and (f["filingDate"] or "") >= since]
    f144 = [f["filingDate"] for f in filings if f["form"] == "144" and (f["filingDate"] or "") >= since]
    return {"shelf_registrations": shelves, "form_144_count": len(f144), "latest_form_144": max(f144, default=None)}


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
        "resale": resale_and_planned_sales(filings, since),
    }
    try:
        out["insider_trades"] = insider_trades(cik, filings, since)
    except Exception as e:
        out["insider_trades"] = {"error": str(e)[:200]}
    try:
        out["xbrl_annual"] = annual_facts(company_facts(cik))
    except requests.HTTPError as e:
        out["xbrl_annual"] = {"error": str(e)}
    form = "10-K" if out["latest"]["10-K"] else "20-F"
    tenk = out["latest"]["10-K"] or out["latest"]["20-F"]
    if with_10k and tenk:
        url = doc_url(cik, tenk)
        text = html_to_text(_get(url).text)
        items = split_items(text)
        items["_form"] = form
        out["10k"] = {"url": url, "form": form, "filed": tenk["filingDate"], "chars": len(text),
                      "items": {k: len(v) for k, v in items.items() if k != "_form"}, "phrases": scan_phrases(text)}
        out["_10k_items"] = items  # stored separately by the pipeline
    tenq = out["latest"]["10-Q"]
    if with_10k and tenq and (not tenk or tenq["filingDate"] > tenk["filingDate"]):
        try:
            qtext = html_to_text(_get(doc_url(cik, tenq)).text)
            q = tenq_items(qtext)
            out["10q"] = {"filed": tenq["filingDate"], "items": {k: len(v) for k, v in q.items()},
                          "phrases": scan_phrases(qtext)}
            out["_10q_items"] = q
        except Exception as e:
            out["10q"] = {"error": str(e)[:200]}
    out["_filings"] = filings  # for the guidance fetcher; not stored
    return out

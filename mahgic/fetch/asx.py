"""Stage 3b — ASX announcements (T1) for Australian companies.

Uses the JSON feed behind the asx.com.au announcements page (asx.api.cmfyapp.com).
It is not a documented API: if the shape changes, `fetch` falls back to the older
markitdigital feed, and failing that returns an error record so the thesis marks B4
as Low confidence rather than failing the batch.

Oct 2026 fix: the old feed (`companies/{code}/announcements`) returns only the last
5 announcements whatever `count` says, so FLT showed five buy-back notices and none
of its three guidance amendments. The new feed pages back as far as needed.

Flags (playbook B4, ASX):
- capital raisings: placement, SPP, entitlement offer, Appendix 2A/3B
- trading halts, ASX price/aware queries
- substantial holder notices (603/604/605), director interest (3Y)
- Appendix 4C (quarterly cash flow) present -> runway check needed
- guidance changes in headlines (amended / downgraded / withdrawn guidance)
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import requests

log = logging.getLogger("mahgic")
API = "https://asx.api.cmfyapp.com/asx-research/1.0/"
OLD_FEED = "https://asx.api.markitdigital.com/asx-research/1.0/companies/{code}/announcements"
FILE = API + "file/{key}"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) MAhGIC/2.0"}

PATTERNS = {
    "capital_raise": r"placement|share purchase plan|\bSPP\b|entitlement offer|capital raising|appendix (2A|3B)|cleansing notice",
    "trading_halt": r"trading halt|suspension from (official )?quotation|voluntary suspension",
    "asx_query": r"price query|aware (letter|query)|response to asx query",
    "substantial_holder": r"(becoming|change in|ceasing to be a) substantial hold|form 60[345]",
    "director_interest": r"appendix 3Y|change of director'?s interest",
    "cash_flow_report": r"appendix 4C|appendix 5B|quarterly (activities|cash ?flow)",
    "results": r"appendix 4[DE]|half[- ]year(ly)? (report|results|accounts)|full[- ]year (report|results)|annual report|results (announcement|release|presentation)",
    "leadership_change": r"(ceo|cfo|managing director|chief executive|chief financial).{0,40}(resign|depart|retire|appoint|step|transition)",
    "guidance": r"guidance|outlook|trading update",
    # A headline that itself says guidance went the wrong way (FLT 16 Jun 2026: "Amends FY26 Profit Guidance")
    "guidance_change": r"(amend\w*|downgrad\w*|revis\w*|lower\w*|withdraw\w*|cut\w*)\s.{0,40}guidance|guidance.{0,30}(amend|downgrad|revis|lower|withdraw|cut)",
}


def _entity_xid(code: str) -> str | None:
    r = requests.get(API + "search/predictive", params={"searchText": code}, headers=UA, timeout=20)
    r.raise_for_status()
    for it in r.json().get("data", {}).get("items", []):
        if (it.get("symbol") or "").upper() == code:
            return str(it.get("xidEntity") or "") or None
    return None


def list_announcements(code: str, since: str, max_pages: int = 8) -> list[dict]:
    xid = _entity_xid(code)
    if not xid:
        raise RuntimeError(f"no ASX entity id for {code}")
    out = []
    for page in range(max_pages):
        r = requests.get(API + "markets/announcements", headers=UA, timeout=25,
                         params={"entityXids": xid, "page": page, "itemsPerPage": 100})
        r.raise_for_status()
        items = r.json().get("data", {}).get("items", [])
        if not items:
            break
        out += items
        if (items[-1].get("date") or "")[:10] < since:
            break
    return out


def _old_feed(code: str) -> list[dict]:
    r = requests.get(OLD_FEED.format(code=code), params={"count": 100}, headers=UA, timeout=25)
    r.raise_for_status()
    return r.json().get("data", {}).get("items", [])


def fetch(ticker: str, since: str | None = None) -> dict:
    code = ticker.split(".")[0].upper()
    since = since or (date.today() - timedelta(days=548)).isoformat()
    source = "asx.com.au announcements feed"
    try:
        items = list_announcements(code, since)
    except Exception as e:
        log.warning("%s: ASX announcements feed failed (%s); trying the old 5-item feed", ticker, str(e)[:120])
        try:
            items, source = _old_feed(code), "old feed (last 5 only)"
        except Exception as e2:
            return {"ticker": ticker, "error": f"ASX feed unavailable: {str(e2)[:200]}", "tier": "T1"}

    anns = [{"date": (i.get("date") or "")[:10], "headline": i.get("headline"),
             "price_sensitive": i.get("isPriceSensitive"), "types": i.get("announcementTypes"),
             "key": i.get("documentKey"), "size": i.get("fileSize")}
            for i in items if (i.get("date") or "")[:10] >= since]
    flags: dict[str, list] = {k: [] for k in PATTERNS}
    for a in anns:
        h = a["headline"] or ""
        for k, pat in PATTERNS.items():
            if re.search(pat, h, re.I):
                flags[k].append({"date": a["date"], "headline": h})
    return {"ticker": ticker, "tier": "T1", "source": source, "since": since,
            "n_announcements": len(anns), "announcements": anns,
            "flags": {k: v for k, v in flags.items() if v},
            "counts": {k: len(v) for k, v in flags.items()}}


def download(key: str, max_bytes: int = 8_000_000) -> bytes | None:
    """One announcement PDF; None if it is larger than max_bytes (results presentations
    can be 20 MB of slides; the release or speech carries the guidance)."""
    with requests.get(FILE.format(key=key), headers=UA, timeout=60, stream=True) as r:
        r.raise_for_status()
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > max_bytes:
                return None
        return bytes(buf)

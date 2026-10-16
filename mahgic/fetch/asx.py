"""Stage 3b — ASX announcements (T1) for Australian companies.

Uses the JSON feed behind asx.com.au company pages. It is not a documented
API: if the shape changes, `fetch` returns an error record and the thesis marks
B4 as Low confidence rather than failing the batch.

Flags (playbook B4, ASX):
- capital raisings: placement, SPP, entitlement offer, Appendix 2A/3B
- trading halts, ASX price/aware queries
- substantial holder notices (603/604/605), director interest (3Y)
- Appendix 4C (quarterly cash flow) present -> runway check needed
"""
from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger("mahgic")
FEED = "https://asx.api.markitdigital.com/asx-research/1.0/companies/{code}/announcements"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) MAhGIC/2.0"}

PATTERNS = {
    "capital_raise": r"placement|share purchase plan|\bSPP\b|entitlement offer|capital raising|appendix (2A|3B)|cleansing notice",
    "trading_halt": r"trading halt|suspension from (official )?quotation|voluntary suspension",
    "asx_query": r"price query|aware (letter|query)|response to asx query",
    "substantial_holder": r"(becoming|change in|ceasing to be a) substantial holder|form 60[345]",
    "director_interest": r"appendix 3Y|change of director'?s interest",
    "cash_flow_report": r"appendix 4C|appendix 5B|quarterly (activities|cash ?flow)",
    "results": r"appendix 4[DE]|half[- ]year(ly)? (report|results)|full[- ]year (report|results)|annual report",
    "leadership_change": r"(ceo|cfo|managing director|chief executive|chief financial).{0,40}(resign|depart|retire|appoint|step)",
    "guidance": r"guidance|outlook|trading update",
}


def fetch(ticker: str, count: int = 100) -> dict:
    code = ticker.split(".")[0].upper()
    try:
        r = requests.get(FEED.format(code=code), params={"count": count, "market_sensitive": "false"},
                         headers=UA, timeout=25)
        r.raise_for_status()
        items = r.json().get("data", {}).get("items", [])
    except Exception as e:
        return {"ticker": ticker, "error": f"ASX feed unavailable: {str(e)[:200]}", "tier": "T1"}

    anns = [{"date": (i.get("date") or "")[:10], "headline": i.get("headline"),
             "price_sensitive": i.get("isPriceSensitive"), "types": i.get("announcementTypes"),
             "key": i.get("documentKey")} for i in items]
    flags: dict[str, list] = {k: [] for k in PATTERNS}
    for a in anns:
        h = a["headline"] or ""
        for k, pat in PATTERNS.items():
            if re.search(pat, h, re.I):
                flags[k].append({"date": a["date"], "headline": h})
    return {"ticker": ticker, "tier": "T1", "announcements": anns,
            "flags": {k: v for k, v in flags.items() if v},
            "counts": {k: len(v) for k, v in flags.items()}}

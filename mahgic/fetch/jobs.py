"""Stage 3c — hiring signal (playbook B2) from the company's own job board.

Order of preference:
1. config/ats.yaml mapping (ticker -> platform + board id), confirmed by a human once;
2. detection: load the careers page from the company website and look for an
   ATS host (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Workable, PageUp);
3. otherwise record "no ATS feed" — the gap is shown, never filled with guesses.
   (v1 returned a canned LinkedIn line; that is gone.)

Each fetcher returns a list of {title, location, department, posted} dicts.
Snapshots are stored per run, so month-on-month change is the real signal.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from urllib.parse import urljoin

import requests

from ..config import ats_map

log = logging.getLogger("mahgic")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) MAhGIC/2.0"}
TIMEOUT = 25

ATS_PATTERNS = {
    "greenhouse": r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)",
    "lever": r"jobs\.lever\.co/([A-Za-z0-9_-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)",
    "smartrecruiters": r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)",
    "workday": r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)",
    "workable": r"apply\.workable\.com/([A-Za-z0-9_-]+)",
    "pageup": r"(https?://[a-z0-9.-]*pageuppeople\.com/[^\s\"'<>]+)",
}


# ---------- fetchers ----------

def greenhouse(board: str) -> list[dict]:
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", params={"content": "true"},
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": j["title"], "location": (j.get("location") or {}).get("name"),
             "department": ", ".join(d["name"] for d in j.get("departments", [])) or None,
             "posted": j.get("updated_at")} for j in r.json().get("jobs", [])]


def lever(company: str) -> list[dict]:
    r = requests.get(f"https://api.lever.co/v0/postings/{company}", params={"mode": "json"}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": j["text"], "location": j.get("categories", {}).get("location"),
             "department": j.get("categories", {}).get("team"), "posted": j.get("createdAt")} for j in r.json()]


def ashby(org: str) -> list[dict]:
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": j["title"], "location": j.get("location"), "department": j.get("department"),
             "posted": j.get("publishedAt")} for j in r.json().get("jobs", [])]


def smartrecruiters(company: str) -> list[dict]:
    out, offset = [], 0
    while True:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                         params={"limit": 100, "offset": offset}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for j in data.get("content", []):
            out.append({"title": j["name"], "location": (j.get("location") or {}).get("city"),
                        "department": (j.get("department") or {}).get("label"), "posted": j.get("releasedDate")})
        offset += 100
        if offset >= data.get("totalFound", 0) or offset > 2000:
            return out


def workday(tenant: str, wd: str, site: str, cap: int = 2000) -> list[dict]:
    url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    out, offset, total = [], 0, None
    while total is None or offset < min(total, cap):
        r = requests.post(url, json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
                          headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        total = data.get("total", 0) if total is None else total
        posts = data.get("jobPostings", [])
        if not posts:
            break
        out += [{"title": j.get("title"), "location": j.get("locationsText"), "department": None,
                 "posted": j.get("postedOn")} for j in posts]
        offset += 20
    return out


def workable(account: str) -> list[dict]:
    r = requests.get(f"https://apply.workable.com/api/v1/widget/accounts/{account}", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": j["title"], "location": ", ".join(filter(None, [j.get("city"), j.get("country")])),
             "department": j.get("department"), "posted": j.get("published_on")} for j in r.json().get("jobs", [])]


def pageup(url: str) -> list[dict]:
    from bs4 import BeautifulSoup

    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select("tr, li.job, div.job")
    out = []
    for row in rows:
        a = row.find("a", href=re.compile(r"/job|/cw/|jobDetails", re.I))
        if a and a.get_text(strip=True):
            out.append({"title": a.get_text(strip=True), "location": None, "department": None, "posted": None})
    return out


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
            "workable": workable, "pageup": pageup}


# ---------- detection ----------

CAREER_PATHS = ["/careers", "/careers/", "/jobs", "/about/careers", "/en/careers", "/join-us", "/work-with-us"]


def detect(website: str | None) -> dict | None:
    """Find the ATS behind a company's careers page. Returns {platform, ...ids} or None."""
    if not website:
        return None
    seen = set()
    for path in [""] + CAREER_PATHS:
        url = urljoin(website.rstrip("/") + "/", path.lstrip("/"))
        if url in seen:
            continue
        seen.add(url)
        try:
            r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        hit = match_ats(r.url + "\n" + r.text)
        if hit:
            hit["found_on"] = url
            return hit
        # follow one hop: a "careers"/"jobs" link on the home page
        if path == "":
            for m in re.finditer(r'href="([^"]*(?:career|jobs)[^"]*)"', r.text, re.I):
                link = urljoin(r.url, m.group(1))
                if link not in seen:
                    seen.add(link)
                    try:
                        r2 = requests.get(link, headers=UA, timeout=TIMEOUT)
                        hit = match_ats(r2.url + "\n" + r2.text)
                        if hit:
                            hit["found_on"] = link
                            return hit
                    except requests.RequestException:
                        pass
                break
    return None


def match_ats(text: str) -> dict | None:
    for platform, pat in ATS_PATTERNS.items():
        m = re.search(pat, text)
        if not m:
            continue
        if platform == "workday":
            return {"platform": "workday", "tenant": m.group(1), "wd": m.group(2), "site": m.group(3)}
        if platform == "pageup":
            return {"platform": "pageup", "url": m.group(1)}
        board = m.group(1)
        if board.lower() in {"embed", "api", "v1"}:
            continue
        return {"platform": platform, "board": board}
    return None


# ---------- summary ----------

THEMES = {
    "ai_data": r"\b(ai|machine learning|ml|data scien|llm|genai|artificial intelligence)\b",
    "sales_gtm": r"\b(sales|account executive|business development|partnerships?|customer success)\b",
    "engineering": r"\b(engineer|developer|software|platform|devops|sre)\b",
    "manufacturing_ops": r"\b(plant|production|manufactur|technician|operator|warehouse|supply chain|logistics)\b",
    "finance_legal": r"\b(finance|accountant|controller|tax|legal|counsel|compliance|audit)\b",
    "leadership": r"\b(chief|vp|vice president|head of|director|general manager)\b",
}


def summarise(jobs: list[dict]) -> dict:
    themes = Counter()
    for j in jobs:
        t = (j.get("title") or "").lower()
        for name, pat in THEMES.items():
            if re.search(pat, t):
                themes[name] += 1
    locs = Counter((j.get("location") or "unknown").split(",")[0].strip() for j in jobs)
    depts = Counter(j.get("department") or "unknown" for j in jobs)
    return {"total": len(jobs), "themes": dict(themes), "top_locations": locs.most_common(8),
            "top_departments": depts.most_common(8), "sample_titles": [j["title"] for j in jobs[:40]]}


def fetch(ticker: str, website: str | None) -> dict:
    cfg = ats_map().get(ticker)
    source = "config" if cfg else "detected"
    if not cfg:
        try:
            cfg = detect(website)
        except Exception as e:  # never let one careers site stop a batch
            log.debug("%s ATS detection failed: %s", ticker, e)
            cfg = None
    if not cfg:
        return {"ticker": ticker, "status": "no_ats_feed", "website": website,
                "note": "No public ATS feed found. B2 confidence Low; LinkedIn/Chrome fallback is a manual step."}
    try:
        p = cfg["platform"]
        if p == "workday":
            jobs = workday(cfg["tenant"], cfg["wd"], cfg["site"])
        elif p == "pageup":
            jobs = pageup(cfg["url"])
        else:
            jobs = FETCHERS[p](cfg["board"])
    except Exception as e:
        return {"ticker": ticker, "status": "fetch_failed", "ats": cfg, "error": str(e)[:300]}
    return {"ticker": ticker, "status": "ok", "ats": cfg, "ats_source": source, "tier": "T2",
            "summary": summarise(jobs), "jobs": jobs}

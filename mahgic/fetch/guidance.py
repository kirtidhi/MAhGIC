"""Stage 3c — guidance history (B5 "credibility", B6 cap: two or more guidance cuts or misses).

The Oct 2026 Claude-vs-local test showed this is the fact the local run most often lacked:
Claude found FLT's three guidance amendments, INTU's TurboTax cut and MNDY's withdrawn
2027 target by searching; the local model never saw them, so the cap never applied.

This module only collects the documents (Python, T1):
- US 10-K filers: the press release (EX-99) of each 8-K with Item 2.02 (results)
- US 20-F filers: 6-K exhibits that read like results releases
- ASX: price-sensitive results / guidance / trading-update / AGM announcements (PDF)

Reading them is a local-model step (`extract_guidance`, Gemma) in the draft stage; Python
then counts the dated negative events and applies the cap. The model's statements must
quote the document, and quotes that are not found in it are dropped.
"""
from __future__ import annotations

import io
import logging
import re

log = logging.getLogger("mahgic")

DOC_CHARS = 14_000  # per document sent to the model (~3.5k tokens)
KEY_WORDS = re.compile(r"(?i)\b(outlook|guidance|expects?|forecast|target|reaffirm\w*|rais\w+|lower\w*|withdr\w+)\b")
ASX_DOC = re.compile(r"(?i)results|guidance|trading update|outlook|agm|annual general meeting|investor day|"
                     r"appendix 4[de]|half[- ]year|full[- ]year|chair.{0,20}address|md.{0,10}address")
ASX_PREFER = re.compile(r"(?i)release|announcement|speech|address|update|guidance|4[de]")
ASX_SKIP = re.compile(r"(?i)presentation|webcast|teleconference|briefing|notification of buy-back|appendix 3")


def focus(text: str, chars: int = DOC_CHARS) -> str:
    """The opening of a release plus the paragraphs around outlook / guidance words."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= chars:
        return text
    head = text[: chars // 2]
    windows, budget = [], chars - len(head)
    for m in KEY_WORDS.finditer(text, len(head)):
        if budget <= 0:
            break
        s, e = max(len(head), m.start() - 600), min(len(text), m.start() + 1400)
        if windows and s <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], e))
        else:
            windows.append((s, e))
        budget = chars - len(head) - sum(b - a for a, b in windows)
    return head + "".join("\n[...]\n" + text[a:b] for a, b in windows)[: chars - len(head)]


def pdf_text(data: bytes, pages: int = 12) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:pages])


# ---------- US (SEC) ----------
def _exhibit(cik: int, acc: str) -> str | None:
    from . import sec

    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/"
    items = sec._get(base + "index.json").json().get("directory", {}).get("item", [])
    names = [i["name"] for i in items if i.get("name", "").lower().endswith((".htm", ".html", ".txt"))]
    ex = [n for n in names if re.search(r"(?i)ex[-_]?99|exhibit99|ex991|dex99", n)]
    return base + (ex[0] if ex else names[0]) if names else None


def us_docs(cik: int, filings: list[dict], since: str, foreign: bool, max_docs: int = 5) -> list[dict]:
    from . import sec

    if foreign:  # 20-F filers furnish results on 6-K
        cands = [f for f in filings if f["form"] == "6-K" and (f["filingDate"] or "") >= since][:15]
    else:
        cands = [f for f in filings if f["form"] == "8-K" and "2.02" in str(f.get("items") or "")
                 and (f["filingDate"] or "") >= since][:max_docs]
    docs = []
    for f in cands:
        if len(docs) >= max_docs:
            break
        try:
            url = _exhibit(cik, f["accessionNumber"])
            if not url:
                continue
            text = sec.html_to_text(sec._get(url).text)
        except Exception as e:
            log.warning("guidance doc %s failed: %s", f["accessionNumber"], str(e)[:120])
            continue
        if foreign and not re.search(r"(?i)(quarter|half[- ]year|full[- ]year|fiscal).{0,80}(results|revenue)", text[:6000]):
            continue  # most 6-Ks are not results releases
        docs.append({"date": f["filingDate"], "source": f"{f['form']} {f['accessionNumber']}",
                     "title": "results release (EX-99)", "url": url, "text": focus(text)})
    return docs


# ---------- ASX ----------
def asx_docs(announcements: list[dict], max_docs: int = 5) -> list[dict]:
    from . import asx

    cands = [a for a in announcements if a.get("price_sensitive") and ASX_DOC.search(a.get("headline") or "")
             and not ASX_SKIP.search(a.get("headline") or "")]
    # newest first; on a results day keep the release over the accounts or the 4D/4E
    cands.sort(key=lambda a: (a["date"], bool(ASX_PREFER.search(a["headline"] or ""))), reverse=True)
    docs, days = [], set()
    for a in cands:
        if len(docs) >= max_docs:
            break
        if a["date"] in days:
            continue
        try:
            data = asx.download(a["key"])
            if not data:
                continue
            text = pdf_text(data)
        except Exception as e:
            log.warning("ASX doc %s failed: %s", a.get("headline"), str(e)[:120])
            continue
        if len(text) < 500:
            continue  # scanned image PDF
        days.add(a["date"])
        docs.append({"date": a["date"], "source": "ASX announcement", "title": a["headline"],
                     "key": a["key"], "text": focus(text)})
    return docs


def fetch(market: str, filings: dict, since: str, max_docs: int = 5) -> dict:
    if market == "asx":
        anns = filings.get("announcements") or []
        docs = asx_docs(anns, max_docs)
        headline_events = (filings.get("flags") or {}).get("guidance_change", [])
    else:
        cik = filings.get("cik")
        if not cik:
            return {"status": "no_source", "docs": []}
        foreign = bool((filings.get("latest") or {}).get("20-F")) and not (filings.get("latest") or {}).get("10-K")
        docs = us_docs(cik, filings.get("_filings") or [], since, foreign, max_docs)
        headline_events = []
    return {"status": "ok" if docs else "no_docs", "docs": docs, "headline_events": headline_events}


# ---------- after the model has read the docs ----------
NEGATIVE = {"lowered", "withdrawn", "missed"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%$.]+", " ", (s or "").lower()).strip()


def verify(statements: list[dict], doc_text: str) -> tuple[list[dict], int]:
    """Keep statements whose quote appears in the document (first 60 normalised chars)."""
    hay = _norm(doc_text)
    kept, dropped = [], 0
    for st in statements or []:
        q = _norm(str(st.get("quote") or ""))[:60]
        if len(q) >= 12 and q in hay:
            kept.append(st)
        else:
            dropped += 1
    return kept, dropped


def summarise(per_doc: list[dict], headline_events: list[dict] | None = None) -> dict:
    """Count dated negative guidance events (one per document date). A cut or withdrawal of a
    formal guide or target counts; consensus that management only commented on does not
    (Claude-run proposal for playbook v1.3, Oct 2026)."""
    neg, pos = [], []
    for d in per_doc:
        for st in d.get("statements", []):
            change = (st.get("change") or "").lower()
            vs = (st.get("vs_prior_guidance") or "").lower()
            ev = {"date": d["date"], "doc": d.get("title"), "metric": st.get("metric"),
                  "what": change if change in NEGATIVE else vs, "quote": st.get("quote")}
            if change in ("lowered", "withdrawn") or vs == "missed":
                neg.append(ev)
            elif change == "raised" or vs == "beat":
                pos.append({**ev, "what": change if change == "raised" else vs})
    neg_dates = sorted({e["date"] for e in neg}, reverse=True)
    # A headline that says guidance was downgraded/withdrawn counts even if its PDF was not read
    for h in headline_events or []:
        if re.search(r"(?i)downgrad|lower|withdraw|\bcut", h.get("headline") or "") and h["date"] not in neg_dates:
            neg.append({"date": h["date"], "doc": h["headline"], "what": "headline", "quote": h["headline"]})
            neg_dates.append(h["date"])
    return {"negative_events": neg, "positive_events": pos[:8],
            "negative_event_dates": sorted(set(neg_dates), reverse=True),
            "count_negative": len(set(neg_dates))}

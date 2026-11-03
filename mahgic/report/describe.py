"""`python -m mahgic describe`: plain "What it does" and "Why it matters now" per company.

Nov 2026, after comparing the local write-ups with the June Gemini ones: Gemini's best feature
was a plain story a non-investor can follow; its worst were facts it made up to fit a theme and
rupee figures labelled as dollars. Here the fast local model (Gemma) writes both paragraphs from
two sources only: Yahoo's business description and the latest results release we already
downloaded. The "why now" paragraph must quote the release, and the quote is checked against it.
About 1-2 minutes a company, no paid calls. Saved as describe.json; the thesis files pick it up
the next time they are rendered (`python -m mahgic run --stages review`).
"""
from __future__ import annotations

import logging
import time

from ..fetch import guidance as guidance_mod
from ..llm import providers as llm

log = logging.getLogger("mahgic")

DESCRIBE_SYSTEM = """You write for a newsletter reader who is not an investor. Use ONLY the COMPANY
DESCRIPTION and the LATEST RESULTS RELEASE below; never outside knowledge, never invent numbers.
Reply with JSON only:
{"what_it_does": "1-2 plain sentences: what the company sells, to whom, and where. No jargon. No praise words such as leading, innovative, world-class.",
 "why_now": "2-3 plain sentences on what is happening in the business now, from the results release: growth or decline, the main problem or opportunity, any big change. Include one or two numbers exactly as the release gives them, with the currency and the period. If no release is given, say that the latest results were not read.",
 "quote": "one exact sentence copied from the results release that supports why_now, or empty if no release"}"""

DOC_CHARS = 6000


def latest_doc(gdocs: dict | None) -> dict | None:
    docs = sorted((gdocs or {}).get("docs", []), key=lambda d: d.get("date") or "", reverse=True)
    return docs[0] if docs else None


def describe_one(info: dict, gdocs: dict | None) -> dict:
    summary = (info or {}).get("longBusinessSummary") or "(no description)"
    doc = latest_doc(gdocs)
    doc_text = (doc or {}).get("text", "")[:DOC_CHARS]
    user = (f"COMPANY: {info.get('longName') or info.get('shortName')}\n\nCOMPANY DESCRIPTION:\n{summary[:2500]}\n\n"
            + (f"LATEST RESULTS RELEASE ({doc.get('date')}, {doc.get('title')}):\n{doc_text}" if doc
               else "LATEST RESULTS RELEASE: none available"))
    data, _ = llm.call_json("describe", DESCRIBE_SYSTEM, user)
    q = (data.get("quote") or "").strip()
    kept, _ = guidance_mod.verify([{"quote": q}], doc_text) if (q and doc_text) else ([], 0)
    return {"what_it_does": (data.get("what_it_does") or "").strip(),
            "why_now": (data.get("why_now") or "").strip(),
            "quote": q, "quote_verified": bool(kept),
            "source": f"{doc.get('date')} {doc.get('title')}" if doc else None}


def run(store, tickers: list[str], force: bool = False, time_up=None) -> int:
    done = 0
    for i, t in enumerate(tickers, 1):
        if time_up and time_up():
            log.info("describe: stopping at --until after %d companies", done)
            return 3
        if store.has(t, "describe") and not force:
            continue
        info = store.load(t, "info")
        if not info:
            continue
        t0 = time.time()
        try:
            store.save(t, "describe", describe_one(info, store.load(t, "guidance_docs")))
            done += 1
            log.info("[describe %d/%d] %s in %.0fs", i, len(tickers), t, time.time() - t0)
        except Exception as e:
            log.warning("describe %s failed: %s", t, str(e)[:160])
    return 0

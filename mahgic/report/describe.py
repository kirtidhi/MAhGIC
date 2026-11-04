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
import re
import time

from ..fetch import guidance as guidance_mod
from ..llm import providers as llm

log = logging.getLogger("mahgic")

DESCRIBE_SYSTEM = """You write for a newsletter reader who is not an investor. Use ONLY the COMPANY
DESCRIPTION and the LATEST RESULTS RELEASE below; never outside knowledge, never invent numbers.
Reply with JSON only:
{"what_it_does": "1-2 plain sentences: what the company sells, to whom, and where. No jargon. No praise words such as leading, innovative, world-class.",
 "why_now": "2-3 plain sentences on what is happening in the business now, from the results release: growth or decline, the main problem or opportunity, any big change. Include one or two numbers copied EXACTLY as the release writes them (same digits, same unit), with the currency and the period. In results tables, check whether a column is a dollar change or a % change before you call a number a percentage. If no release is given, say that the latest results were not read.",
 "quote": "one exact sentence copied from the results release that contains the main number you used in why_now, or empty if no release"}"""

NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(\s?%|\s?per ?cent)?")


def _nums(text: str) -> list[tuple[str, bool]]:
    """Numbers worth checking in a sentence: (normalised digits, is_percent). Skips years and 1-digit numbers."""
    out = []
    for m in NUM.finditer(text or ""):
        whole, frac, pct = m.group(1).replace(",", ""), m.group(2), bool(m.group(3))
        n = whole + (f".{frac}" if frac else "")
        if not pct and not frac and (len(whole) < 2 or (len(whole) == 4 and whole.startswith(("19", "20")))):
            continue
        out.append((n, pct))
    return out


def _matches(n: str, cands: set[str]) -> bool:
    """n appears in the release, allowing the model to round (5.9 from 5,902) or change units
    (billion from million, thousand)."""
    if n in cands:
        return True
    d = len(n.split(".")[1]) if "." in n else 0
    x = float(n)
    for c in cands:
        y = float(c)
        for scale in (1, 1e-3, 1e3, 1e-6):
            if y and abs(round(y * scale, d) - x) < 10 ** -d / 2 + 1e-9 and (d > 0 or y * scale >= 10):
                return True
    return False


def check_numbers(why_now: str, quote: str, doc_text: str) -> tuple[bool, list[str]]:
    """Every figure in why_now must appear in the release, a percentage as a percentage (rounding
    and unit changes allowed). Cochlear Nov 2026: a $12.4m fall in a results table read as
    "down 12.4%" (the release's percentage was <1%)."""
    doc = _nums(doc_text)
    pcts, plain_ = {n for n, p in doc if p}, {n for n, _ in doc}
    missing = [n + ("%" if p else "") for n, p in _nums(why_now)
               if not _matches(n, pcts if p else plain_)]
    return not missing, missing


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
    out = _finish(data, doc_text)
    if doc and not out["verified"]:  # one retry, telling the model what failed
        fix = (f"\n\nYOUR LAST ANSWER FAILED THE CHECK: "
               + (f"these figures are not in the release as written: {', '.join(out['missing_numbers'])}. "
                  if out["missing_numbers"] else "")
               + "Copy every figure exactly as the release writes it, and make the quote an exact sentence "
                 "from the release that contains the main figure.")
        try:
            data2, _ = llm.call_json("describe", DESCRIBE_SYSTEM, user + fix)
            out2 = _finish(data2, doc_text)
            if out2["verified"] or len(out2["missing_numbers"]) < len(out["missing_numbers"]):
                out = out2
        except Exception as e:
            log.warning("describe retry failed: %s", str(e)[:120])
    out["source"] = f"{doc.get('date')} {doc.get('title')}" if doc else None
    return out


def _finish(data: dict, doc_text: str) -> dict:
    why, q = (data.get("why_now") or "").strip(), (data.get("quote") or "").strip()
    kept, _ = guidance_mod.verify([{"quote": q}], doc_text) if (q and doc_text) else ([], 0)
    nums_ok, missing = check_numbers(why, q, doc_text) if doc_text else (False, [])
    return {"what_it_does": (data.get("what_it_does") or "").strip(), "why_now": why, "quote": q,
            "quote_verified": bool(kept), "missing_numbers": missing,
            "verified": bool(kept) and nums_ok}


def run(store, tickers: list[str], force: bool = False, time_up=None, redo_unverified: bool = False) -> int:
    done = 0
    for i, t in enumerate(tickers, 1):
        if time_up and time_up():
            log.info("describe: stopping at --until after %d companies", done)
            return 3
        if store.has(t, "describe") and not force:
            prev = store.load(t, "describe") or {}
            if not redo_unverified or not prev.get("source"):
                continue
            if "verified" not in prev:  # written before the figure check: re-check it without the model
                doc = latest_doc(store.load(t, "guidance_docs"))
                prev = {**_finish(prev, (doc or {}).get("text", "")[:DOC_CHARS]), "source": prev.get("source")}
                store.save(t, "describe", prev)
            if prev.get("verified"):
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

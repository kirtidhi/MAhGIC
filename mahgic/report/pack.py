"""Review packs: the local model prepares a 1-2 page brief per company for a Claude review.

Oct 2026: Claude's reviews of the ASX top picks found the same few problems again and again
(cash flow inflated by deposits or leases, private-equity or strategic holders counted as
founder skin, guidance cuts missed, earnings at a cyclical peak, stale annual figures). Most of
the cost of a review was finding the facts. Here the fast local model answers a fixed checklist,
one question at a time, from the documents already fetched; every answer must quote its source
and quotes not found in the documents are marked unverified. Python adds the computed numbers,
holder notices and the local thesis, and writes pack_<TICKER>.md. Claude then reads the pack and
looks up only what the pack leaves open.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from ..fetch import guidance as guidance_mod
from ..llm import providers as llm

log = logging.getLogger("mahgic")

PACK_SYSTEM = """You help an investment analyst check one company. Answer ONE question from the
DOCUMENTS only (company results releases and announcements). Quote the documents exactly; never
use outside knowledge, never invent numbers. If the documents do not answer it, say "not in the
documents". Reply with JSON only:
{"answer": "2-5 short sentences", "quotes": ["exact sentence from the documents", ...],
 "confidence": "High | Med | Low"}"""

QUESTIONS = [
    ("latest_result", "Latest result: for the most recent period reported, what were revenue, underlying "
                      "and statutory profit, operating cash flow, net cash or net debt, and the dividend? "
                      "What did management say about the outlook or guidance?"),
    ("cash_quality", "Cash flow quality: is operating cash flow boosted by items that are not earnings, such as "
                     "customer or resident deposits, prepayments, lease accounting (rent shown as financing), "
                     "working-capital release, asset sales or one-off tax? Give the amounts if stated."),
    ("guidance_record", "Guidance record: in these documents, did the company cut, lower, amend downward or "
                        "withdraw any guidance or target, or report a result below its own earlier guidance? "
                        "List each with its date."),
    ("cycle", "Cycle: are current earnings helped by unusually high prices, margins or demand (commodity "
              "prices, fares, rates, a boom) that could reverse? What does management say?"),
    ("leadership_holders", "People and owners: any CEO, CFO or chair changes, and any mention of major "
                           "shareholders (founder or family, private equity, a parent or strategic holder) or "
                           "large share sales or buy-backs?"),
    ("industry_adjustments", "Industry adjustments: does this business need special treatment an investor must "
                             "adjust for, such as regulated or government funding, deposits held for customers, "
                             "net tangible assets for an investment company, net asset value for a property "
                             "trust, insurance reserves, concession end dates, or a large stake in another listed "
                             "company?"),
]

HOLDER_RE = re.compile(r"(?i)(becoming a substantial holder|change in substantial holding|ceasing to be a "
                       r"substantial holder)\s*(?:from|for|-|:)?\s*(.+)$")


def _docs_text(gdocs: dict | None, max_docs: int = 2) -> tuple[str, str]:
    docs = sorted((gdocs or {}).get("docs", []), key=lambda d: d["date"], reverse=True)[:max_docs]
    text = "\n\n".join(f"### {d['date']} - {d.get('title')}\n{d['text']}" for d in docs)
    label = "; ".join(f"{d['date']} {d.get('title')}" for d in docs)
    return text, label


def holder_notices(filings: dict | None, limit: int = 12) -> list[str]:
    out = []
    for a in (filings or {}).get("announcements", []) or []:
        m = HOLDER_RE.search(a.get("headline") or "")
        if m:
            out.append(f"{a['date']}: {m.group(1).title()} - {m.group(2).strip()}")
    return out[:limit]


def _fmt_pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def build(t: str, store, cfg: dict, max_points: dict) -> str:
    info = store.load(t, "info") or {}
    a = store.load(t, "analysis") or {}
    m, rf = a.get("metrics", {}), a.get("redflags", {})
    d = store.load(t, "draft") or {}
    g = store.load(t, "guidance") or {}
    filings = store.load(t, "filings") or {}
    docs_text, docs_label = _docs_text(store.load(t, "guidance_docs"))

    answers = {}
    if docs_text:
        for key, q in QUESTIONS:
            try:
                data, _ = llm.call_json("review_pack", PACK_SYSTEM, f"QUESTION: {q}\n\nDOCUMENTS:\n{docs_text}")
            except Exception as e:
                log.warning("%s pack %s failed: %s", t, key, e)
                answers[key] = {"answer": f"(failed: {str(e)[:120]})", "quotes": [], "confidence": "Low"}
                continue
            kept, dropped = guidance_mod.verify([{"quote": q_} for q_ in data.get("quotes") or []], docs_text)
            data["quotes_verified"] = [k["quote"] for k in kept]
            data["quotes_unverified"] = dropped
            answers[key] = data

    vt = m.get("valuation_test") or {}
    name = info.get("longName") or info.get("shortName") or t
    L = [f"# Review pack: {name} ({t})",
         f"Prepared {date.today().isoformat()} by the local model for a Claude review. Documents read: "
         f"{docs_label or 'none'}.", "",
         "## Local result",
         f"- Track: {d.get('track')}; one line: {d.get('one_line')}",
         f"- Section points: " + ", ".join(f"{k} {((d.get('sections') or {}).get(k) or {}).get('points')}/{v}"
                                            for k, v in max_points.items()),
         f"- Profile claimed by the model: {d.get('profile')}; curable negative: {d.get('curable_negative')}",
         f"- Verdict: {d.get('verdict')}",
         f"- Bear case: {'; '.join(d.get('bear_case') or [])}", "",
         "## Computed (code)",
         f"- Industry {info.get('industry')}; market value {info.get('marketCap')}; price {info.get('currentPrice')}; "
         f"52-week high {info.get('fiftyTwoWeekHigh')}; analysts {info.get('numberOfAnalystOpinions')}",
         f"- Forward P/E {m.get('forward_pe')}; trailing P/E {m.get('trailing_pe')}; FCF yield {_fmt_pct(m.get('fcf_yield'))}"
         f" (after SBC {_fmt_pct(m.get('fcf_yield_after_sbc'))}); local 10y {m.get('bond_10y')}%",
         f"- A6 price test: {vt.get('passes')} ({vt.get('basis')})",
         f"- Revenue latest {m.get('revenue_latest')} (Yahoo; may lag the latest result); 1y growth "
         f"{_fmt_pct(m.get('revenue_growth_1y'))}; OCF/NI {m.get('ocf_to_ni')}; net debt {m.get('net_debt')}; "
         f"ND/EBITDA {m.get('net_debt_to_ebitda')}; ROIC {_fmt_pct(m.get('roic'))}",
         f"- Insiders (Yahoo) {info.get('heldPercentInsiders')}; institutions {info.get('heldPercentInstitutions')}",
         f"- Hard caps: {rf.get('hard_caps')}",
         "- Flags: " + " | ".join(rf.get("notes") or []), "",
         "## Guidance history (code count)",
         f"- {g.get('docs_read', 0)} releases read; {g.get('count_negative', 0)} negative events "
         f"{g.get('negative_event_dates') or ''}",
         *[f"  - {e.get('date')}: {e.get('metric')} {e.get('what')}" for e in (g.get('negative_events') or [])[:5]],
         "", "## Substantial-holder notices (ASX headlines)"]
    hn = holder_notices(filings)
    L += [f"- {h}" for h in hn] or ["- none in the window (or not an ASX company)"]
    L += ["", "## Checklist (local model, from the documents)"]
    if not answers:
        L.append("- No results documents were available; every item below is open.")
    for key, q in QUESTIONS:
        a_ = answers.get(key) or {}
        L += ["", f"**{key.replace('_', ' ').capitalize()}** ({a_.get('confidence', 'n/a')})",
              str(a_.get("answer", "not answered"))]
        L += [f"> {q_}" for q_ in (a_.get("quotes_verified") or [])[:3]]
        if a_.get("quotes_unverified"):
            L.append(f"*{a_['quotes_unverified']} quote(s) not found in the documents: treat this answer as unverified.*")
    open_items = [k for k in (x for x, _ in QUESTIONS)
                  if (answers.get(k) or {}).get("confidence") in (None, "Low")
                  or "not in the documents" in str((answers.get(k) or {}).get("answer", "")).lower()]
    L += ["", "## Open for the Claude review",
          f"- Checklist items with low confidence or no answer: {', '.join(open_items) or 'none'}",
          "- Always check: news since the run date, who the top holders are, and whether the price test holds "
          "after industry adjustments.", ""]
    return "\n".join(L)

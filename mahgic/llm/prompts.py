"""Prompts built from the knowledge files. The knowledge files are the spec:
the code only selects the sections each step needs, so a 14B local model gets
~8k tokens of rules rather than the whole 45k-character pair.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from ..config import knowledge


@lru_cache
def sections(name: str) -> dict[str, str]:
    """Split a knowledge file on '## X1.' headings -> {'A7': text, ...}."""
    text = knowledge(name)
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+([A-Z]\d+)\.", line)
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1), [line]
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def rules_pack(market: str) -> str:
    base, play = sections("base_layer.md"), sections("playbook.md")
    parts = [base.get(k, "") for k in ("A3", "A4", "A5", "A6", "A7")]
    parts += [play.get(k, "") for k in ("B2", "B5", "B6")]
    return f"MARKET: {market}\n\n" + "\n\n---\n\n".join(p for p in parts if p)


EXTRACT_SYSTEM = """You read one chunk of a company's annual report (10-K or equivalent) and pull out
facts an investor needs. Quote short phrases exactly; never invent numbers.
Reply with JSON only:
{"moat_evidence": [str], "competitive_threats": [str], "growth_drivers": [str],
 "capex_and_capacity": [str], "guidance_or_targets": [str], "customer_concentration": [str],
 "new_or_serious_risks": [str], "accounting_or_audit_issues": [str], "capital_allocation": [str],
 "management_tone": "operational specifics | mixed | buzzwords and macro excuses | n/a"}
Use [] when the chunk says nothing on a field."""


GUIDANCE_SYSTEM = """You read one company results release, trading update or AGM address and list every
statement about the company's OWN guidance, outlook or targets. Do not count analyst or
consensus expectations. Quote the document exactly; never invent numbers.
For each statement give:
- metric: e.g. "FY26 underlying profit before tax", "Q4 revenue", "2027 revenue target"
- period: the period the guidance is for
- guidance_text: the guidance as stated (range or number)
- change: "new" | "reaffirmed" | "raised" | "lowered" | "withdrawn" | "none"
  ("lowered" includes narrowing to a lower midpoint and "amended" guidance that is below the
  previous range; "withdrawn" includes a target the company no longer expects to meet).
  Compare with PREVIOUS GUIDANCE (from the company's earlier releases) when it is given: the same
  metric and period now guided lower = "lowered", higher = "raised", unchanged = "reaffirmed".
- vs_prior_guidance: for a reported result, did it "beat" | "met" | "missed" the company's own
  earlier guidance? Use "n/a" if the document does not say.
- quote: the exact sentence (at least 8 words) the statement comes from
Also list leadership changes, legal or regulatory matters and restructurings the document mentions.
Reply with JSON only:
{"document_date": str, "statements": [{"metric": str, "period": str, "guidance_text": str,
 "change": str, "vs_prior_guidance": str, "quote": str}], "other_events": [str]}
Use [] when there is no guidance."""


DRAFT_SYSTEM_HEAD = """You are the MA(h)GIC analyst. Apply the rules below exactly. Python has already
computed every number and red flag in the FACTS; do not recompute or contradict them.
Where data is missing say so and lower confidence; never fill a gap with a guess.
Score each section within its maximum (B6). Caps are applied by code afterwards, but you
must confirm or reject each CHECK item. To confirm one you must copy the exact text from the
FACTS that proves it into "quote"; a confirmation without a matching quote is discarded.
Do not infer a guidance cut from the track name or from a fallen share price.

RULES
=====
"""

DRAFT_SCHEMA = {
    "one_line": "str: the thesis in one sentence",
    "track": "hidden_gem | fallen_quality",
    "sections": {s: {"points": "number within max", "confidence": "High | Med | Low",
                     "evidence": ["str, cite the fact"], "gaps": ["str"]}
                 for s in ("business", "management", "balance_sheet", "financials", "macro",
                           "strategic_intent", "leadership", "regulatory")},
    "caps_confirmed": [{"item": "id from CHECK list", "confirmed": "bool", "reason": "str",
                        "quote": "exact text from the FACTS that proves it (required to confirm)"}],
    "profile": {"moat": "bool", "valuation": "bool (<=15x mid-cycle or FCF yield > local 10y)",
                "curable_negative": "bool", "insider_is_parent_or_pe": "bool"},
    "curable_negative": "str: what went wrong and the dated catalyst that fixes it, or 'structural'",
    "bear_case": ["str"],
    "what_would_change_my_mind": ["str"],
    "verdict": "str: 2-4 sentences",
}


def draft_system(market: str) -> str:
    return (DRAFT_SYSTEM_HEAD + rules_pack(market) +
            "\n\nReply with JSON only, in this shape:\n" + json.dumps(DRAFT_SCHEMA, indent=1))


def facts_pack(row: dict, metrics: dict, redflags: dict, filings: dict | None, jobs: dict | None,
               extracted: dict | None, max_points: dict, guidance: dict | None = None) -> str:
    # Budget: rules (~6k tokens) + facts (<~8k) + thinking + answer must fit num_ctx
    # (24k for Qwen 9B; drafts measured at 8-11k prompt tokens in Oct 2026).
    def j(x, limit=4000):
        return json.dumps(x, default=str, separators=(",", ":"))[:limit]

    f = {k: v for k, v in (filings or {}).items()
         if not k.startswith("_") and k not in ("announcements", "insider_trades", "resale", "xbrl_annual")}
    if f.get("flags") and isinstance(f["flags"], dict):
        f["flags"] = {k: (v[:8] if isinstance(v, list) else v) for k, v in f["flags"].items()}
    jobs_view = None
    if jobs:
        jobs_view = {k: jobs.get(k) for k in ("status", "ats", "note", "error")}
        jobs_view["summary"] = jobs.get("summary")
        jobs_view["previous_snapshot"] = jobs.get("previous_summary")
    parts = [
        "SECTION MAXIMUMS: " + j(max_points),
        "SCREEN (Phase 0, Yahoo T3; track is set by code): " + j(row),
        "METRICS (computed, annual unless noted): " + j(metrics, 6000),
        "RED FLAGS (hard caps already applied by code): " + j({k: redflags[k] for k in ("hard_caps", "notes")}),
        "CHECK (confirm or reject each, quote required to confirm): " + j(redflags["check_caps"]),
    ]
    if guidance:
        parts.append("GUIDANCE HISTORY (T1, read from results releases; counted by code): " + j({
            k: guidance.get(k) for k in ("status", "docs_read", "count_negative", "negative_events",
                                         "positive_events", "other_events")}, 3500))
    it = (filings or {}).get("insider_trades")
    if it and not it.get("error"):
        parts.append("INSIDER TRADES (SEC Form 4, T1, open-market only): " + j(it, 1500))
    rs = (filings or {}).get("resale")
    if rs and (rs.get("shelf_registrations") or rs.get("form_144_count")):
        parts.append("REGISTERED SHELVES / PLANNED INSIDER SALES (T1): " + j(rs, 600))
    parts += ["FILINGS (T1): " + j(f),
              "HIRING (B2): " + j(jobs_view),
              "ANNUAL / QUARTERLY REPORT EXTRACTS: " + j(extracted, 6000)]
    return "\n\n".join(parts)


REVIEW_SYSTEM = """You review a draft stock thesis written by a smaller local model under the MA(h)GIC rules.
Check: numbers match the FACTS; each section's points are justified by its evidence; caps were
confirmed or rejected correctly; the curable-vs-structural call is sound; anything material
the draft missed. Reply with JSON only:
{"agree": bool, "issues": [str], "section_points": {section: number},
 "caps_confirmed": [{"item": str, "confirmed": bool, "reason": str}], "verdict": str}"""

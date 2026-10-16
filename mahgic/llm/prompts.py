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


DRAFT_SYSTEM_HEAD = """You are the MA(h)GIC analyst. Apply the rules below exactly. Python has already
computed every number and red flag in the FACTS; do not recompute or contradict them.
Where data is missing say so and lower confidence; never fill a gap with a guess.
Score each section within its maximum (B6). Caps are applied by code afterwards, but you
must confirm or reject each CHECK item with a reason or quote from the facts.

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
    "caps_confirmed": [{"item": "id from CHECK list", "confirmed": "bool", "reason": "str"}],
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
               extracted: dict | None, max_points: dict) -> str:
    # Budget: the whole facts pack must stay under ~7k tokens (~26k chars) so that
    # rules + facts + answer fit a 16k context on a 16 GB Mac.
    def j(x, limit=4000):
        return json.dumps(x, default=str, separators=(",", ":"))[:limit]

    f = dict(filings or {})
    f.pop("_10k_items", None)
    f.pop("announcements", None)
    jobs_view = None
    if jobs:
        jobs_view = {k: jobs.get(k) for k in ("status", "ats", "note", "error")}
        jobs_view["summary"] = jobs.get("summary")
        jobs_view["previous_snapshot"] = jobs.get("previous_summary")
    return "\n\n".join([
        "SECTION MAXIMUMS: " + j(max_points),
        "SCREEN (Phase 0, Yahoo T3): " + j(row),
        "METRICS (computed, annual unless noted): " + j(metrics, 6000),
        "RED FLAGS (hard caps already applied by code): " + j({k: redflags[k] for k in ("hard_caps", "notes")}),
        "CHECK (confirm or reject each): " + j(redflags["check_caps"]),
        "FILINGS (T1): " + j(f),
        "HIRING (B2): " + j(jobs_view),
        "ANNUAL REPORT EXTRACTS: " + j(extracted, 6000),
    ])


REVIEW_SYSTEM = """You review a draft stock thesis written by a smaller local model under the MA(h)GIC rules.
Check: numbers match the FACTS; each section's points are justified by its evidence; caps were
confirmed or rejected correctly; the curable-vs-structural call is sound; anything material
the draft missed. Reply with JSON only:
{"agree": bool, "issues": [str], "section_points": {section: number},
 "caps_confirmed": [{"item": str, "confirmed": bool, "reason": str}], "verdict": str}"""

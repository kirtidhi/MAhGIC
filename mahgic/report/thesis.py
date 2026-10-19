"""Render one thesis_<TICKER>.md from the stored stage outputs."""
from __future__ import annotations


def _fmt(v, pct=False, money=False):
    if v is None:
        return "n/a (missing)"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if pct:
        return f"{v:.1%}"
    if money:
        a = abs(v)
        return f"{v/1e9:.2f}bn" if a >= 1e9 else f"{v/1e6:.0f}m"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


TITLES = {"business": "Business (Three Q)", "management": "Management (Three Q)",
          "balance_sheet": "Balance sheet (Three Q)", "financials": "Financials and valuation",
          "macro": "Macro and cycle fit", "strategic_intent": "Strategic intent and hiring",
          "leadership": "Leadership and insiders", "regulatory": "Regulatory and risks"}


def render(ticker: str, row: dict, metrics: dict, redflags: dict, draft: dict, scored: dict,
           review: dict | None, run_meta: dict) -> str:
    cur = metrics.get("currency") or ""
    L = [f"# {ticker} — {row.get('name') or ''}",
         f"**Run:** {run_meta['date']} · {run_meta['market']} / {run_meta['universe']} · "
         f"track: {draft.get('track') or row.get('track')} · drafted by {run_meta.get('draft_model')}"
         + (f" · reviewed by {run_meta.get('review_model')}" if review else ""),
         "",
         f"## Score: {scored['score']} / 10" + (" (low confidence)" if scored["low_confidence"] else ""),
         f"Raw {scored['raw']}" + (f", capped at {scored['binding_cap']}" if scored.get("binding_cap") else ""),
         "", f"> {draft.get('one_line', '')}", "",
         "| Section | Points | Max | Confidence |", "|---|---|---|---|"]
    for s, title in TITLES.items():
        L.append(f"| {title} | {scored['points'][s]:.1f} | {run_meta['max_points'][s]} | "
                 f"{scored['confidence_by_section'][s]} |")
    if scored["caps_applied"]:
        L += ["", "**Caps considered**"] + [f"- {c['cap']}: {c['why']}" for c in scored["caps_applied"]]

    L += ["", "## Key numbers (computed; Yahoo T3 unless marked)", "",
          f"- Price {_fmt(row.get('price'))} {row.get('currency') or ''}, "
          f"{_fmt(row.get('drawdown_from_high'), pct=True)} below 52-week high; forward P/E {_fmt(metrics.get('forward_pe'))}",
          f"- Revenue {_fmt(metrics.get('revenue_latest'), money=True)} {cur}, 5y CAGR {_fmt(metrics.get('revenue_cagr_5y'), pct=True)}, "
          f"1y {_fmt(metrics.get('revenue_growth_1y'), pct=True)}; operating margin trend {_fmt(metrics.get('operating_margin_trend'))}",
          f"- OCF/NI {_fmt(metrics.get('ocf_to_ni'))}; FCF {_fmt(metrics.get('fcf_latest'), money=True)} "
          f"({_fmt(metrics.get('fcf_yoy_change'), pct=True)} y/y); FCF yield {_fmt(metrics.get('fcf_yield'), pct=True)}",
          f"- Net debt {_fmt(metrics.get('net_debt'), money=True)}; ND/EBITDA {_fmt(metrics.get('net_debt_to_ebitda'))}; "
          f"ROIC {_fmt(metrics.get('roic'), pct=True)}; receivable days {_fmt(metrics.get('receivable_days'))}",
          f"- Share count change 1y {_fmt(metrics.get('share_change_pct_1y'))}%; insiders {_fmt(row.get('insider_pct'))}% (Yahoo; B5 check)",
          f"- SBC {_fmt(metrics.get('sbc_to_revenue'), pct=True)} of revenue; FCF yield after SBC "
          f"{_fmt(metrics.get('fcf_yield_after_sbc'), pct=True)} vs local 10y {_fmt(metrics.get('bond_10y'))}%",
          f"- A6 price test (code): {_fmt((metrics.get('valuation_test') or {}).get('passes'))} — "
          f"{(metrics.get('valuation_test') or {}).get('basis', 'n/a')}",
          ]
    if metrics.get("is_cyclical"):
        L.append(f"- Cyclical: latest EPS {_fmt(metrics.get('eps_latest'))} vs 5y median "
                 f"{_fmt(metrics.get('eps_median_5y'))}; price / mid-cycle EPS {_fmt(metrics.get('mid_cycle_pe'))}x")
    if draft.get("track_model"):
        L.append(f"- Track set by size from the screen; the model had proposed {draft['track_model']}")
    if metrics.get("data_gaps"):
        L.append(f"- Data gaps: {', '.join(metrics['data_gaps'])}")
    if redflags.get("notes"):
        L += ["", "## Flags"] + [f"- {n}" for n in redflags["notes"]]
    rejected = [c for c in draft.get("caps_confirmed", []) if "[discarded by code" in str(c.get("reason"))]
    if rejected:
        L += [f"- Check item '{c.get('item')}' claimed by the model but discarded: no supporting quote" for c in rejected]
    meta = draft.get("_meta") or {}
    if meta.get("overflows"):
        L.append(f"- Draft needed a retry after a context overflow ({meta.get('attempt')})")

    for s, title in TITLES.items():
        sec = (draft.get("sections") or {}).get(s) or {}
        L += ["", f"## {title}"] + [f"- {e}" for e in sec.get("evidence", [])]
        if sec.get("gaps"):
            L.append(f"- *Gaps:* {'; '.join(sec['gaps'])}")

    L += ["", "## Curable negative", draft.get("curable_negative", "n/a"),
          "", "## Bear case"] + [f"- {b}" for b in draft.get("bear_case", [])]
    L += ["", "## What would change my mind"] + [f"- {b}" for b in draft.get("what_would_change_my_mind", [])]
    L += ["", "## Verdict", draft.get("verdict", "")]
    if review:
        L += ["", "## Review", f"Agrees with draft: {_fmt(review.get('agree'))}"]
        L += [f"- {i}" for i in review.get("issues", [])]
        if review.get("verdict"):
            L += ["", review["verdict"]]
    L += ["", "*Framework method, not financial advice.*", ""]
    return "\n".join(L)

"""Stage 4b — B4/B5 red flags and B6 caps.

Caps that can be decided from numbers are applied here ("hard"). Caps that need
reading ("auditor change: resignation or rotation?", "is this going-concern
language or boilerplate?", "two guidance cuts?") are passed to the draft model
as "check" items; it must confirm or reject each with a quote.
"""
from __future__ import annotations


def evaluate(metrics: dict, filings: dict | None, cfg: dict) -> dict:
    caps = cfg["caps"]
    hard, check, notes = [], [], []

    # OCF < NI and bloated receivables -> cap 4
    if metrics.get("ocf_to_ni") is not None and metrics["ocf_to_ni"] < 1:
        rd = metrics.get("receivable_days")
        if (rd is not None and rd > cfg["flags"]["receivable_days_max"]) or metrics.get("receivables_outgrowing_revenue"):
            hard.append({"cap": caps["ocf_below_ni_and_receivables_over_120"],
                         "why": f"OCF/NI {metrics['ocf_to_ni']:.2f} with receivable days {rd and round(rd)}"})
        else:
            notes.append("OCF below net income in the latest year (receivables fine)")

    # Dilution
    d = metrics.get("share_change_pct_1y")
    if d is not None and d > 5:
        if metrics.get("cwip_trend") == "up":
            check.append({"cap": caps["dilution_over_5pct"], "item": "dilution_with_capex",
                          "why": f"Shares +{d:.1f}% but CWIP rising: is the raise funding visible capex?"})
        else:
            hard.append({"cap": caps["dilution_over_5pct"], "why": f"Shares +{d:.1f}% in a year, no visible capex"})
    elif d is not None and d > cfg["flags"]["dilution_flag_pct"]:
        notes.append(f"Dilution {d:.1f}% a year (flag above 3%)")

    if metrics.get("roic_below_min"):
        notes.append(f"ROIC {metrics['roic']:.1%} below ~10%")
    if metrics.get("fcf_fell_over_50pct"):
        notes.append("FCF fell more than 50% year on year (Phase 0 test 3)")

    f = filings or {}
    # SEC
    for e in (f.get("flags") or {}).get("events", []):
        flag = e["flag"]
        if "4.01" in flag:
            check.append({"cap": caps["auditor_resignation_or_qualified"], "item": "auditor_change",
                          "why": f"{e['date']} {flag}: resignation/dismissal over a disagreement, or routine rotation?"})
        elif "4.02" in flag:
            check.append({"cap": caps["auditor_resignation_or_qualified"], "item": "restatement",
                          "why": f"{e['date']} {flag}"})
        elif "late filing" in flag:
            notes.append(f"{e['date']} {flag}")
        elif "5.02" in flag:
            notes.append(f"{e['date']} {flag} (check if CEO/CFO and whether near a guidance cut)")
        else:
            notes.append(f"{e['date']} {flag}")
    phrases = (f.get("10k") or {}).get("phrases", {})
    if phrases.get("going_concern"):
        check.append({"cap": caps["going_concern"], "item": "going_concern",
                      "why": "10-K contains going-concern wording; confirm it is a conclusion, not boilerplate",
                      "quotes": phrases["going_concern"][:2]})
    if phrases.get("material_weakness"):
        notes.append("Material weakness wording in 10-K")
    if phrases.get("customer_concentration"):
        notes.append("Customer concentration disclosed: " + phrases["customer_concentration"][0][:200])

    # ASX
    af = f.get("counts") or {}
    if af.get("capital_raise", 0) >= 2:
        notes.append(f"{af['capital_raise']} capital-raising announcements in the window")
    if af.get("trading_halt"):
        notes.append(f"{af['trading_halt']} trading halts/suspensions")
    if af.get("asx_query"):
        notes.append(f"{af['asx_query']} ASX price/aware queries")

    # Always asked of the model: guidance credibility needs reading results calls
    check.append({"cap": caps["guidance_misses_2plus"], "item": "guidance_misses",
                  "why": "Two or more guidance misses or cuts in the last 4-6 quarters?"})

    return {"hard_caps": hard, "check_caps": check, "notes": notes,
            "hard_cap": min((c["cap"] for c in hard), default=None)}

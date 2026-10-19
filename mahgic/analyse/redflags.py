"""Stage 4b — B4/B5 red flags and B6 caps.

Caps that can be decided from numbers or dated documents are applied here ("hard").
Caps that need reading ("auditor change: resignation or rotation?", "is this going-concern
language or boilerplate?") are passed to the draft model as "check" items; it must confirm
or reject each, and a confirmation counts only with a quote found in the facts.

Oct 2026 changes (Claude-vs-local test):
- Banks and insurers skip the industrial cash-flow tests (OCF/NI, receivable days, ROIC):
  CBA was capped at 4 for "OCF/NI -0.60, receivable days 68", which says nothing about a bank.
- Guidance credibility is counted by code from the guidance history when it was read;
  the model is asked only when no results releases could be read. ADBE was capped at 5
  because the model "confirmed" two guidance misses with no evidence.
- Notes for investigations / class actions, Form 4 insider selling and buying, registered
  resale shelves, Form 144s, ASX leadership / substantial-holder / guidance headlines, and a
  parent or strategic holder hiding in Yahoo's insider figure.
"""
from __future__ import annotations


def evaluate(metrics: dict, filings: dict | None, cfg: dict, is_financial: bool = False,
             guidance: dict | None = None, info: dict | None = None) -> dict:
    caps = cfg["caps"]
    hard, check, notes = [], [], []

    if is_financial:
        notes.append("Bank/insurer/financial: industrial cash-flow tests (OCF vs net income, receivable "
                     "days, ROIC) not applied; judge on capital, credit quality and returns on equity (A7)")
    else:
        # OCF < NI and bloated receivables -> cap 4
        if metrics.get("ocf_to_ni") is not None and metrics["ocf_to_ni"] < 1:
            rd = metrics.get("receivable_days")
            if (rd is not None and rd > cfg["flags"]["receivable_days_max"]) or metrics.get("receivables_outgrowing_revenue"):
                hard.append({"cap": caps["ocf_below_ni_and_receivables_over_120"],
                             "why": f"OCF/NI {metrics['ocf_to_ni']:.2f} with receivable days {rd and round(rd)}"})
            else:
                notes.append("OCF below net income in the latest year (receivables fine)")
        if metrics.get("roic_below_min"):
            notes.append(f"ROIC {metrics['roic']:.1%} below ~10%")

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

    if metrics.get("fcf_fell_over_50pct"):
        notes.append("FCF fell more than 50% year on year (Phase 0 test 3)")
    if metrics.get("sbc_material"):
        y = metrics.get("fcf_yield_after_sbc")
        notes.append(f"SBC is {metrics['sbc_to_revenue']:.0%} of revenue: judge cash returns after SBC"
                     + (f" (FCF yield after SBC {y:.1%})" if y is not None else ""))
    if metrics.get("is_cyclical") and metrics.get("eps_at_peak"):
        notes.append(f"Cyclical with latest EPS {metrics['eps_latest']:.2f} vs 5-year median "
                     f"{metrics['eps_median_5y']:.2f}: earnings look near peak; value on mid-cycle EPS"
                     + (f" ({metrics['mid_cycle_pe']:.1f}x)" if metrics.get("mid_cycle_pe") else ""))

    ins = (info or {}).get("heldPercentInsiders")
    h = cfg["hypothetical_8"]
    if ins is not None and ins * 100 >= h.get("parent_suspect_pct", 50):
        notes.append(f"Yahoo shows insiders {ins:.0%}: a stake this size is usually a parent company or "
                     "strategic holder, not founder skin (not counted for A6 until verified)")

    f = filings or {}
    # SEC
    for e in (f.get("flags") or {}).get("events", []) if isinstance(f.get("flags"), dict) else []:
        flag = e["flag"]
        if "4.01" in flag:
            check.append({"cap": caps["auditor_resignation_or_qualified"], "item": "auditor_change",
                          "why": f"{e['date']} {flag}: resignation/dismissal over a disagreement, or routine rotation?"})
        elif "4.02" in flag:
            check.append({"cap": caps["auditor_resignation_or_qualified"], "item": "restatement",
                          "why": f"{e['date']} {flag}"})
        elif "5.02" in flag:
            notes.append(f"{e['date']} {flag} (check if CEO/CFO and whether near a guidance cut)")
        else:
            notes.append(f"{e['date']} {flag}")
    phrases = {}
    for src in ("10k", "10q"):
        for k, v in ((f.get(src) or {}).get("phrases") or {}).items():
            phrases.setdefault(k, []).extend(v)
    if phrases.get("going_concern"):
        check.append({"cap": caps["going_concern"], "item": "going_concern",
                      "why": "Filing contains going-concern wording; confirm it is a conclusion, not boilerplate",
                      "quotes": phrases["going_concern"][:2]})
    if phrases.get("material_weakness"):
        notes.append("Material weakness disclosed: " + phrases["material_weakness"][0][:220])
    if phrases.get("investigation"):
        notes.append("Investigation / subpoena wording in filings: " + phrases["investigation"][0][:260])
    if phrases.get("class_action"):
        notes.append("Class action wording in filings: " + phrases["class_action"][0][:220])
    if phrases.get("customer_concentration"):
        notes.append("Customer concentration disclosed: " + phrases["customer_concentration"][0][:200])

    it = f.get("insider_trades") or {}
    if it.get("open_market_sales") or it.get("open_market_buys"):
        notes.append(f"Form 4 since {(f.get('flags') or {}).get('since', 'window start')}: "
                     f"{it.get('open_market_buys', 0)} open-market buys (${it.get('buy_value', 0):,.0f}), "
                     f"{it.get('open_market_sales', 0)} sales (${it.get('sell_value', 0):,.0f})")
    rs = f.get("resale") or {}
    for sh in rs.get("shelf_registrations", [])[:3]:
        notes.append(f"{sh['date']} {sh['form']} registration: may register a founder/VC stake for resale "
                     "(insider skin unreliable until checked)")
    if rs.get("form_144_count"):
        notes.append(f"{rs['form_144_count']} Form 144 notices of planned insider sales (latest {rs.get('latest_form_144')})")

    # ASX
    af = f.get("counts") or {}
    fl = f.get("flags") if isinstance(f.get("flags"), dict) else {}
    if af.get("capital_raise", 0) >= 2:
        notes.append(f"{af['capital_raise']} capital-raising announcements in the window")
    if af.get("trading_halt"):
        notes.append(f"{af['trading_halt']} trading halts/suspensions")
    if af.get("asx_query"):
        notes.append(f"{af['asx_query']} ASX price/aware queries")
    for k, label in (("leadership_change", "Leadership"), ("guidance_change", "Guidance headline")):
        for h_ in (fl.get(k) or [])[:3]:
            notes.append(f"{h_['date']} {label}: {h_['headline']}")
    if af.get("director_interest"):
        notes.append(f"{af['director_interest']} director-interest notices (Appendix 3Y): check buys vs sells")

    # Guidance credibility (B5/B6): code decides when the releases were read
    g = guidance or {}
    if g.get("status") == "ok":
        n = g.get("count_negative", 0)
        dates = ", ".join(g.get("negative_event_dates", [])[:6])
        if n >= 2:
            hard.append({"cap": caps["guidance_misses_2plus"],
                         "why": f"{n} guidance cuts/withdrawals/misses in the window ({dates})"})
        else:
            notes.append(f"Guidance record from {g.get('docs_read', 0)} results releases: "
                         f"{n} negative event{'s' if n != 1 else ''}" + (f" ({dates})" if dates else ""))
    else:
        check.append({"cap": caps["guidance_misses_2plus"], "item": "guidance_misses",
                      "why": "No results releases could be read. Confirm only if the FACTS quote two or more "
                             "cuts/withdrawals/misses of the company's own guidance in the last 4-6 quarters"})

    return {"hard_caps": hard, "check_caps": check, "notes": notes,
            "hard_cap": min((c["cap"] for c in hard), default=None)}

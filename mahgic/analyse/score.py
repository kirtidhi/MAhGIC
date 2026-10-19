"""B6 scoring: combine the model's section scores with the caps and the
"hypothetical 8" rule. The model proposes; this file decides the number.
"""
from __future__ import annotations

SECTIONS = ("business", "management", "balance_sheet", "financials", "macro",
            "strategic_intent", "leadership", "regulatory")


def max_points(cfg: dict) -> dict:
    w = cfg["weights"]
    return {**w["three_q"], **{k: w[k] for k in ("financials", "macro", "strategic_intent", "leadership", "regulatory")}}


def final(draft: dict, redflags: dict, metrics: dict, info: dict, cfg: dict) -> dict:
    mp = max_points(cfg)
    sections = draft.get("sections", {})
    points, problems = {}, []
    for s in SECTIONS:
        v = (sections.get(s) or {}).get("points")
        if not isinstance(v, (int, float)):
            problems.append(f"{s}: no points")
            v = 0.0
        points[s] = max(0.0, min(float(v), mp[s]))
    raw = round(sum(points.values()), 1)

    caps = [(c["cap"], c["why"]) for c in redflags.get("hard_caps", [])]
    confirmed = {c.get("item") for c in draft.get("caps_confirmed", []) if c.get("confirmed")}
    for c in redflags.get("check_caps", []):
        if c["item"] in confirmed:
            caps.append((c["cap"], c["why"]))

    # Hypothetical-8 profile (A6): all five or cap 7. Code decides the parts it has data for;
    # the model's view counts only for moat and curable negative, and for valuation when no
    # valuation data exists (MNDY Oct 2026: the model called 13.5x non-GAAP P/E "valuation
    # met" while FCF after SBC yielded ~3.5% against a 5.28% bond).
    h = cfg["hypothetical_8"]
    model_profile = draft.get("profile") or {}
    vt = metrics.get("valuation_test") or {}
    if vt.get("passes") is not None:
        valuation = bool(vt["passes"])
    else:
        fpe = metrics.get("forward_pe")
        valuation = bool(fpe and 0 < fpe <= h["max_mid_cycle_pe"]) or bool(model_profile.get("valuation"))
    ins = info.get("heldPercentInsiders")
    parent_suspect = ins is not None and ins * 100 >= h.get("parent_suspect_pct", 50)
    profile = {
        "moat": bool(model_profile.get("moat")),
        "valuation": valuation,
        "curable_negative": bool(model_profile.get("curable_negative")),
        "net_cash_and_cash_real": bool(metrics.get("net_cash") and metrics.get("cash_is_real")),
        "insider_skin": bool(ins is not None and ins * 100 >= h["min_insider_pct"] and not parent_suspect
                             and not model_profile.get("insider_is_parent_or_pe")),
    }
    if not all(profile.values()):
        caps.append((7, "hypothetical-8 profile incomplete: " + ", ".join(k for k, v in profile.items() if not v)))

    cap = min((c for c, _ in caps), default=10)
    score = round(min(raw, cap), 1)

    conf = [((sections.get(s) or {}).get("confidence") or "Low") for s in SECTIONS]
    low = sum(c == "Low" for c in conf)
    return {"raw": raw, "score": score, "points": points, "caps_applied": [{"cap": c, "why": w} for c, w in caps],
            "binding_cap": cap if cap < raw else None, "profile_8": profile,
            "confidence_by_section": dict(zip(SECTIONS, conf)),
            "low_confidence": low >= 2, "problems": problems,
            "valuation_basis": vt.get("basis"),
            "_ey_fcf": {"earnings_yield": metrics.get("earnings_yield"), "fcf_yield": metrics.get("fcf_yield")}}

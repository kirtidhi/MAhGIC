"""Offline tests for the Oct 2026 fixes from the Claude-vs-local comparison (no network, no LLM)."""
import re

import pytest

from mahgic.analyse import metrics, redflags, score
from mahgic.config import scoring
from mahgic.fetch import asx, guidance, sec
from mahgic.llm import providers
from mahgic.pipeline import check_quotes

CFG = scoring()


# ---------- filings ----------
def test_split_items_rejoins_broken_item_word():
    # CPRT FY26: headings rendered as "Ite\nm 1A." so only the table of contents matched
    toc = "Item 1A. Risk Factors 14\nItem 3. Legal Proceedings 30\nItem 7. MD&A 40\n\n"
    body = ("Ite\nm 1A. \nRisk Factors\n" + "risk text. " * 6000 + "\nIte\nm 3. \nLegal Proceedings\n"
            + "The DOJ issued a subpoena. " * 50 + "\nItem 7. Management's Discussion\n" + "mdna " * 3000)
    items = sec.split_items(toc + body)
    assert len(items["1A"]) > 50_000 and len(items["3"]) > 1000 and len(items["7"]) > 10_000


def test_20f_read_order_targets_risk_and_review():
    assert sec.READ_ORDER["20-F"][:2] == ("3", "5")
    assert sec.READ_ORDER["10-K"][0] == "1A"


def test_tenq_items_skip_table_of_contents():
    q = ("Item 2. Management's Discussion and Analysis of Financial Condition 5\nItem 1. Legal Proceedings 20\n\n"
         "Item 2. Management's Discussion and Analysis of Financial Condition\n" + "m " * 800 +
         "\nItem 3. Quantitative and Qualitative Disclosures\n...\nItem 1. Legal Proceedings\nDOJ " + "l " * 400 +
         "\nItem 1A. Risk Factors\nNo material changes " + "r " * 300 + "\nItem 2. Unregistered Sales\n")
    items = sec.tenq_items(q)
    assert items["Q_LEGAL"].startswith("Item 1. Legal Proceedings\nDOJ")
    assert "Q_MDA" in items


def test_phrases_ignore_hypothetical_material_weakness_and_find_investigations():
    hits = sec.scan_phrases("If we identify a material weakness in our internal control, our stock may fall. "
                            "In March the Department of Justice opened an investigation.")
    assert hits["material_weakness"] == []
    assert len(hits["investigation"]) == 1
    real = sec.scan_phrases("Management identified a material weakness in internal control over revenue.")
    assert real["material_weakness"]


def test_parse_form4_open_market_sale():
    xml = ("<ownershipDocument><aff10b5One>1</aff10b5One><reportingOwner><reportingOwnerId><rptOwnerName>Doe Jane"
           "</rptOwnerName></reportingOwnerId><reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CEO"
           "</officerTitle></reportingOwnerRelationship></reportingOwner><nonDerivativeTable><nonDerivativeTransaction>"
           "<transactionDate><value>2026-09-01</value></transactionDate><transactionCoding><transactionCode>S"
           "</transactionCode></transactionCoding><transactionAmounts><transactionShares><value>1000</value>"
           "</transactionShares><transactionPricePerShare><value>250</value></transactionPricePerShare>"
           "</transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>")
    t = sec.parse_form4(xml)
    assert t == [{"date": "2026-09-01", "who": "Doe Jane", "role": "CEO", "type": "sell", "shares": 1000.0,
                  "value": 250000, "rule_10b5_1": True}]


def test_resale_shelf_and_form_144():
    f = [{"form": "F-3ASR", "filingDate": "2026-05-28"}, {"form": "144", "filingDate": "2026-06-01"},
         {"form": "S-3", "filingDate": "2020-01-01"}]
    r = sec.resale_and_planned_sales(f, "2025-04-01")
    assert r["shelf_registrations"] == [{"date": "2026-05-28", "form": "F-3ASR"}] and r["form_144_count"] == 1


def test_asx_guidance_headlines():
    pat = asx.PATTERNS["guidance_change"]
    for h in ("FLT Amends FY26 Profit Guidance and Announces Buy-Back", "FLT to Acquire Iglu Cruise & Amended Guidance",
              "Earnings guidance downgrade"):
        assert re.search(pat, h, re.I), h
    assert not re.search(pat, "FY26 Full Year Results Presentation", re.I)


# ---------- guidance history ----------
DOC = "Group outlook. We now expect FY26 underlying profit before tax of $255m to $270m, down from $305m to $340m."


def test_guidance_quotes_must_be_in_the_document():
    good = {"metric": "FY26 PBT", "change": "lowered", "quote": "We now expect FY26 underlying profit before tax of $255m"}
    bad = {"metric": "FY27 revenue", "change": "withdrawn", "quote": "The company withdraws its FY27 revenue target entirely"}
    kept, dropped = guidance.verify([good, bad], DOC)
    assert kept == [good] and dropped == 1


def test_guidance_counts_dates_and_hard_cap():
    per_doc = [{"date": "2026-06-16", "statements": [{"change": "lowered", "quote": "q"}]},
               {"date": "2025-12-10", "statements": [{"change": "lowered", "quote": "q"}, {"change": "withdrawn"}]},
               {"date": "2026-02-24", "statements": [{"change": "reaffirmed", "vs_prior_guidance": "met"}]}]
    s = guidance.summarise(per_doc)
    assert s["count_negative"] == 2 and s["negative_event_dates"] == ["2026-06-16", "2025-12-10"]
    rf = redflags.evaluate({}, None, CFG, guidance={"status": "ok", "docs_read": 3, **s})
    assert rf["hard_cap"] == CFG["caps"]["guidance_misses_2plus"]
    assert not any(c["item"] == "guidance_misses" for c in rf["check_caps"])


def test_guidance_read_with_one_event_means_no_cap_and_no_model_check():
    rf = redflags.evaluate({}, None, CFG, guidance={"status": "ok", "docs_read": 4, "count_negative": 1,
                                                    "negative_event_dates": ["2026-05-01"]})
    assert rf["hard_cap"] is None and not rf["check_caps"]
    assert any("1 negative event" in n for n in rf["notes"])


def test_no_guidance_docs_leaves_a_quoted_check():
    rf = redflags.evaluate({}, None, CFG)
    assert [c["item"] for c in rf["check_caps"]] == ["guidance_misses"]


def test_check_confirmation_needs_a_quote_from_the_facts():
    facts = "FILINGS: 2026-06-16 Guidance headline: FLT Amends FY26 Profit Guidance and Announces Buy-Back"
    d = {"caps_confirmed": [
        {"item": "guidance_misses", "confirmed": True, "reason": "track implies a miss", "quote": ""},
        {"item": "auditor_change", "confirmed": True, "reason": "x", "quote": "FLT Amends FY26 Profit Guidance"}]}
    check_quotes(d, facts)
    assert d["caps_confirmed"][0]["confirmed"] is False and "discarded" in d["caps_confirmed"][0]["reason"]
    assert d["caps_confirmed"][1]["confirmed"] is True


def test_focus_keeps_outlook_paragraphs():
    text = "Intro. " * 3000 + "\nOutlook: we expect revenue growth of 16-17%." + " filler." * 2000
    f = guidance.focus(text, 6000)
    assert len(f) <= 6000 and "we expect revenue growth of 16-17%" in f


# ---------- metrics and rules ----------
FUND = {"currency": "USD", "quote_currency": "USD", "has_quarterly": True,
        "annual": {"revenue": [1200, 1000, 800], "net_income": [100, 80, 60], "ocf": [330, 280, 200],
                   "fcf": [320, 270, 190], "receivables": [100, 90, 80], "cash": [1100], "total_debt": [0],
                   "equity": [900], "shares_out": [51, 50], "operating_income": [60], "tax_rate": [0.2],
                   "eps_diluted": [2.0, 1.6, 1.2], "sbc": [170]},
        "quarterly": {}}


def test_sbc_heavy_valuation_uses_fcf_after_sbc():
    # MNDY-like: forward P/E 13.5x and FCF yield 8% pre-SBC, but ~3.75% after SBC vs a 5.28% bond
    m = metrics.compute({"marketCap": 4000, "forwardPE": 13.5, "sector": "Technology"}, FUND, CFG, bond_10y=5.28)
    assert m["sbc_material"] and round(m["fcf_yield_after_sbc"], 4) == 0.0375
    assert m["valuation_test"]["passes"] is False and "after SBC" in m["valuation_test"]["basis"]


def test_cyclical_at_peak_uses_mid_cycle_pe():
    fund = {**FUND, "annual": {**FUND["annual"], "eps_diluted": [30.0, 12.0, 8.0, 10.0, 6.0], "sbc": [1]}}
    m = metrics.compute({"marketCap": 4000, "forwardPE": 8, "sector": "Energy", "currentPrice": 180}, fund, CFG,
                        bond_10y=5.28)
    assert m["eps_at_peak"] is True and m["mid_cycle_pe"] == 18.0
    assert m["valuation_test"]["passes"] is False
    rf = redflags.evaluate(m, None, CFG)
    assert any("near peak" in n for n in rf["notes"])


def test_bank_skips_industrial_cash_tests():
    # CBA Oct 2026 was capped at 4 for "OCF/NI -0.60 with receivable days 68"
    m = {"ocf_to_ni": -0.6, "receivable_days": 68, "receivables_outgrowing_revenue": True, "roic_below_min": True,
         "roic": 0.03}
    assert redflags.evaluate(m, None, CFG)["hard_cap"] == 4
    rf = redflags.evaluate(m, None, CFG, is_financial=True)
    assert rf["hard_cap"] is None and not any("ROIC" in n and "below" in n for n in rf["notes"])


def _draft(points=1.0, **profile):
    secs = {s: {"points": 9, "confidence": "High"} for s in score.SECTIONS}
    return {"sections": secs, "caps_confirmed": [],
            "profile": {"moat": True, "valuation": True, "curable_negative": True, **profile}}


def test_parent_stake_is_not_founder_skin_and_model_cannot_overrule_valuation():
    m = {"net_cash": True, "cash_is_real": True, "valuation_test": {"passes": True, "basis": "x"}}
    s = score.final(_draft(), {"hard_caps": [], "check_caps": []}, m, {"heldPercentInsiders": 0.627}, CFG)
    assert s["profile_8"]["insider_skin"] is False and s["score"] == 7  # REA: News Corp ~61%
    m2 = {**m, "valuation_test": {"passes": False, "basis": "after SBC"}}
    s2 = score.final(_draft(), {"hard_caps": [], "check_caps": []}, m2, {"heldPercentInsiders": 0.16}, CFG)
    assert s2["profile_8"]["valuation"] is False and s2["score"] == 7  # MNDY scored 9.0 before


# ---------- LLM routing ----------
def test_overflow_retries_concise_then_bigger_context(monkeypatch):
    calls = []

    def fake_call(task, system, user, json_mode=False, provider=None, overrides=None):
        calls.append((user.endswith(providers.CONCISE_HINT), (overrides or {}).get("num_ctx")))
        if len(calls) < 3:
            raise providers.ContextOverflow("hit num_ctx=24576")
        return '{"ok": 1}', {}

    monkeypatch.setattr(providers, "call", fake_call)
    data, meta = providers.call_json("draft_thesis", "sys", "user")
    assert data == {"ok": 1} and meta["attempt"] == "bigger_ctx" and len(meta["overflows"]) == 2
    assert calls == [(False, None), (True, None), (True, 32768)]


def test_overflow_never_escalates_when_paid_calls_are_zero(monkeypatch):
    def always_overflow(*a, **k):
        raise providers.ContextOverflow("hit num_ctx")

    monkeypatch.setattr(providers, "call", always_overflow)
    with pytest.raises(ValueError, match="overflows"):
        providers.call_json("draft_thesis", "sys", "user")


def test_tasks_route_to_two_local_models():
    assert providers.provider_for("extract_filing") == "ollama_fast"
    assert providers.provider_for("draft_thesis") == "ollama"
    assert providers.is_local("ollama_fast") and providers.impl_of("ollama_fast") == "ollama"


def test_exhibit_name_pattern_covers_6k_styles():
    for n in ("exhibit_99-1.htm", "ex99-1.htm", "ex-99_1.htm", "d123dex991.htm", "exhibit991.htm", "ex991.htm"):
        assert guidance.EX99.search(n), n
    assert not guidance.EX99.search("form6-k.htm")


def test_resale_shelf_means_no_insider_skin():
    m = {"net_cash": True, "cash_is_real": True, "valuation_test": {"passes": True, "basis": "x"}}
    f = {"resale": {"shelf_registrations": [{"date": "2026-05-28", "form": "F-3ASR"}]}}
    s = score.final(_draft(), {"hard_caps": [], "check_caps": []}, m, {"heldPercentInsiders": 0.196}, CFG, f)
    assert s["profile_8"]["insider_skin"] is False and s["score"] == 7  # ITRN scored 9.5 without this
    s2 = score.final(_draft(), {"hard_caps": [], "check_caps": []}, m, {"heldPercentInsiders": 0.196}, CFG, {})
    assert s2["profile_8"]["insider_skin"] is True


def test_asx_guidance_change_announcements_are_read_first(monkeypatch):
    anns = [{"date": d, "headline": h, "price_sensitive": True, "key": k} for d, h, k in [
        ("2026-08-25", "FY26 Full Year Results Announcement", "a"),
        ("2026-06-16", "FLT Amends FY26 Profit Guidance and Announces Buy-Back", "b"),
        ("2026-02-24", "FY26 Half Year Results Release (inc guidance commentary)", "c"),
        ("2025-11-11", "Chair & MD's AGM Speeches (inc trading update & guidance)", "d"),
        ("2025-08-20", "FY25 Results Release", "e"),
        ("2025-05-02", "Amendment to FY25 Guidance and up to $200m Buyback", "f")]]
    read = []
    monkeypatch.setattr(asx, "download", lambda key: read.append(key) or b"x")
    monkeypatch.setattr(guidance, "pdf_text", lambda data: "guidance " * 200)
    docs = guidance.asx_docs(anns, max_docs=3)
    assert [d["key"] for d in docs] == ["b", "f", "a"]


def test_bank_return_on_price_cap_and_price_test():
    info = {"industry": "Banks - Diversified", "priceToBook": 3.335, "returnOnEquity": 0.1386, "marketCap": 3e11}
    m = metrics.compute(info, {"currency": "AUD", "quote_currency": "AUD", "annual": {}, "quarterly": {}}, CFG, bond_10y=5.22)
    assert m["is_financial"] and round(m["return_on_price"], 3) == 0.042
    assert m["valuation_test"]["passes"] is False
    rf = redflags.evaluate(m, None, CFG, is_financial=True)
    assert rf["hard_cap"] == 5  # CBA Oct 2026: raw 10/10 from the model, ended 7 only via the 8+ cap
    insurer = metrics.compute({**info, "industry": "Insurance - Property & Casualty", "priceToBook": 2.33,
                               "returnOnEquity": 0.193}, {"annual": {}, "quarterly": {}}, CFG, bond_10y=5.22)
    assert insurer["valuation_test"]["passes"] is True
    assert redflags.evaluate(insurer, None, CFG, is_financial=True)["hard_cap"] is None


def test_summary_orders_ties_by_raw_and_states_no_review():
    from mahgic.report import summary
    rows = [{"ticker": t, "name": t, "track": "fallen_quality", "score": 7.0, "raw": r, "cap": 7, "phase0": 5,
             "low_conf": False, "one_line": "", "reviewed": False} for t, r in (("A", 7.2), ("B", 8.6), ("C", 7.8))]
    out = summary.build(rows, {"market": "asx", "universe": "x", "date": "d", "draft_model": "q", "paid_calls": 0})
    assert out.index("| B |") < out.index("| C |") < out.index("| A |")
    assert "Reviews: none" in out


def test_points_above_section_max_are_flagged_not_clamped_into_a_perfect_score():
    d = _draft()
    d["sections"]["business"]["points"] = 5  # CBA Oct 2026: 0-10 style points on a max-1.0 section
    mp = score.max_points(CFG)
    assert score.out_of_range(d, mp) == {"business": 5, "management": 9, "balance_sheet": 9, "financials": 9,
                                         "macro": 9, "strategic_intent": 9, "leadership": 9, "regulatory": 9}
    s = score.final(d, {"hard_caps": [], "check_caps": []}, {}, {}, CFG)
    assert s["low_confidence"] and any("scale error" in p for p in s["problems"])


def test_json_retry_tells_the_model_what_was_wrong(monkeypatch):
    sent = []

    def fake_call(task, system, user, json_mode=False, provider=None, overrides=None):
        sent.append(user)
        return ('{"x": 1}', {})

    def validate(d):
        if len(sent) == 1:
            raise ValueError("points above the section maximum: business 5 (max 1.0)")

    monkeypatch.setattr(providers, "call", fake_call)
    data, meta = providers.call_json("draft_thesis", "sys", "user", validate)
    assert meta["attempt"] == "json_retry" and "business 5 (max 1.0)" in sent[1]

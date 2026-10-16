"""Offline tests: no network, no LLM."""
from mahgic.analyse import metrics, redflags, score
from mahgic.config import scoring
from mahgic.fetch import jobs, sec
from mahgic.screen import phase0

CFG = scoring()

INFO = {"symbol": "TEST", "shortName": "Test Co", "sector": "Industrials", "industry": "Specialty Business Services",
        "currency": "USD", "marketCap": 3e9, "totalCash": 500e6, "totalDebt": 100e6, "ebitda": 300e6,
        "operatingCashflow": 250e6, "freeCashflow": 200e6, "netIncomeToCommon": 180e6, "currentPrice": 60,
        "fiftyTwoWeekHigh": 100, "heldPercentInsiders": 0.12, "forwardPE": 14}


def test_phase0_all_pass_and_track():
    r = phase0(INFO, cfg=CFG)
    assert r["score"] == 6 and r["tests_missing"] == 0
    assert r["track"] == "hidden_gem"
    assert r["drawdown_from_high"] == 0.4


def test_phase0_missing_is_unknown_not_fail():
    info = {**INFO, "totalCash": None, "forwardPE": None}
    r = phase0(info, cfg=CFG)
    assert r["t1_survival"] is None and r["t6_not_pricey"] is None
    assert r["tests_missing"] == 2 and r["score"] == 4


def test_phase0_fcf_halved_fails():
    assert phase0(INFO, fcf_prev=500e6, cfg=CFG)["t3_fcf"] is False
    assert phase0(INFO, fcf_prev=300e6, cfg=CFG)["t3_fcf"] is True


def test_banks_flagged_not_scored():
    r = phase0({**INFO, "industry": "Banks - Regional"}, cfg=CFG)
    assert r["flag_financial"] and r["score"] is None


FUND = {"currency": "USD", "has_quarterly": True,
        "annual": {"revenue": [1000, 900, 800, 700, 600], "net_income": [100, 90, 80, 70, 60],
                   "ocf": [80, 95, 85, 75, 65], "fcf": [40, 100, 70, 60, 50], "receivables": [400, 250, 200, 180, 150],
                   "cash": [50, 60], "total_debt": [200, 150], "equity": [500, 450], "shares_out": [110, 100],
                   "operating_income": [150, 130], "tax_rate": [0.21], "cwip": [], "eps_diluted": [1, 0.9, 0.8],
                   "gross_profit": [400, 360], "sbc": [10], "ebitda": [180]},
        "quarterly": {"revenue": [260, 250, 240, 230, 220, 210, 200, 190]}}


def test_metrics_and_hard_caps():
    m = metrics.compute({"marketCap": 2000, "freeCashflow": 40, "forwardPE": 20}, FUND, CFG)
    assert round(m["receivable_days"]) == 146
    assert m["ocf_to_ni"] == 0.8
    assert m["fcf_fell_over_50pct"] is True
    assert round(m["share_change_pct_1y"]) == 10
    assert m["revenue_trend_8q"] == "up"
    rf = redflags.evaluate(m, None, CFG)
    assert rf["hard_cap"] == 4  # OCF<NI with receivables >120 days beats dilution cap 5
    assert any(c["item"] == "guidance_misses" for c in rf["check_caps"])


def test_score_caps_and_hypothetical_8():
    m = metrics.compute(INFO, FUND, CFG)
    rf = redflags.evaluate(m, None, CFG)
    sections = {s: {"points": mx, "confidence": "High"} for s, mx in score.max_points(CFG).items()}
    draft = {"sections": sections, "caps_confirmed": [{"item": "guidance_misses", "confirmed": True}],
             "profile": {"moat": True, "curable_negative": True}}
    s = score.final(draft, rf, m, INFO, CFG)
    assert s["raw"] == 10
    assert s["score"] == 4  # hard cap 4 wins over guidance 5 and profile 7


def test_score_clamps_section_points():
    rf = {"hard_caps": [], "check_caps": []}
    draft = {"sections": {"business": {"points": 9}}}
    s = score.final(draft, rf, {}, {}, CFG)
    assert s["points"]["business"] == 1.0 and "financials: no points" in s["problems"]
    assert s["low_confidence"]


def test_split_10k_items_skips_table_of_contents():
    text = ("Item 1. Business 3\nItem 1A. Risk Factors 9\nItem 7. MD&A 40\n\n"
            "Item 1. Business\n" + "We sell things. " * 200 +
            "\nItem 1A. Risk Factors\n" + "Risk. " * 300 + "\nItem 7. Management's Discussion\n" + "Grew. " * 100)
    items = sec.split_items(text)
    assert items["1A"].startswith("Item 1A. Risk Factors") and len(items["1A"]) > 1000
    assert len(items["1"]) > 2000


def test_sec_filing_flags():
    filings = [{"accessionNumber": "1", "filingDate": "2026-08-01", "form": "8-K", "primaryDocument": "a", "items": "4.01,9.01"},
               {"accessionNumber": "2", "filingDate": "2026-05-01", "form": "NT 10-Q", "primaryDocument": "b", "items": ""},
               {"accessionNumber": "3", "filingDate": "2024-01-01", "form": "8-K", "primaryDocument": "c", "items": "4.02"}]
    f = sec.filing_flags(filings, "2025-06-01")
    flags = [e["flag"] for e in f["events"]]
    assert any("4.01" in x for x in flags) and any("late" in x for x in flags)
    assert not any("4.02" in x for x in flags)


def test_ats_detection_patterns():
    assert jobs.match_ats('src="https://boards.greenhouse.io/embed/job_board?for=acme"') == {"platform": "greenhouse", "board": "acme"}
    assert jobs.match_ats("https://jobs.lever.co/foo/123") == {"platform": "lever", "board": "foo"}
    assert jobs.match_ats("https://acme.wd5.myworkdayjobs.com/en-US/Careers") == \
        {"platform": "workday", "tenant": "acme", "wd": "wd5", "site": "Careers"}
    assert jobs.match_ats("nothing here") is None


def test_jobs_summary_themes():
    s = jobs.summarise([{"title": "Senior Machine Learning Engineer"}, {"title": "Account Executive"},
                        {"title": "Plant Technician"}])
    assert s["total"] == 3 and s["themes"]["ai_data"] == 1 and s["themes"]["sales_gtm"] == 1

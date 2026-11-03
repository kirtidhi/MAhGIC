"""Plain-English evidence (report/plain.py), Nov 2026."""
from mahgic.report import plain


def test_known_keys():
    assert plain.evidence("revenue_growth_1y:-0.03826842697229538") == "Revenue fell 3.8% last year"
    assert plain.evidence("forward_pe:14.303394") == "Priced at 14.3 times next year's expected earnings"
    assert plain.evidence("is_cyclical:false") == "Not a cyclical business"
    assert plain.evidence("flag_cyclical:false") is None
    assert plain.evidence("count_negative:0 (Guidance history)") == "No guidance cuts found in the results releases read"


def test_json_fragments_from_the_model():
    assert plain.evidence('"revenue_growth_1y":-0.028511069654919785') == "Revenue fell 2.9% last year"
    assert plain.evidence('"cash":404247008.0""debt":220808000.0"', "AUD") == "Cash AUD 404m; Total debt AUD 221m"
    assert plain.evidence('"valuation_test":{"passes":true,"basis":"forward P/E 12.9x"}') == \
        "Passes the price test: forward P/E 12.9x"


def test_free_text_numbers():
    assert plain.evidence("ROIC 0.006031211615203917") == "ROIC 0.6%"
    assert plain.evidence("cash:11704000512.0, debt:63480000512.0 (SCREEN)") == "Cash 11.70bn; Total debt 63.48bn"
    assert plain.evidence("substantial_holder:[\"Change in substantial holding from PPT\"]") == \
        "Substantial holder: Change in substantial holding from PPT"


def test_leadership_counts_sec_changes():
    info = {"companyOfficers": [{"name": "Ms.  Jane  Doe CPA", "title": "Co-Founder & CEO", "age": 50}],
            "heldPercentInsiders": 0.62}
    rf = {"notes": ["2026-07-02 8-K 5.02: director/officer departure or appointment (check ...)",
                    "2026-05-08 8-K 5.02: director/officer departure or appointment (check ...)"]}
    L = plain.leadership(info, rf)
    assert L[0] == "- **Ms. Jane Doe**, Co-Founder & CEO, age 50"
    assert "parent company" in L[1]
    assert any("2 director or officer changes" in x and "2026-07-02" in x for x in L)

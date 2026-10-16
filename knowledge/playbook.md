# MA(h)GIC Playbook — How Each Signal Is Gathered
**Version:** v1.2 | **Written:** 15 Oct 2026 | **Changes:** rarely; bump the version on any method change.
**v1.2 (16 Oct 2026):** B1 "already known" filter replaced by two tracks, Hidden gem and Fallen quality, as labels rather than a cut (Kirti: large companies can be undervalued too). B1 note on `engines/discovery_engine.py` corrected.
**v1.1 (15 Oct 2026):** B6 weights changed by Kirti: Three Q 4 → 3, strategic intent and hiring 0.5 → 1.5. The Wisdom Brain section will later widen to multiple investor frameworks (Buffett and others); weights are provisional until then.

**What this file is:** the fixed method every market session (US, ASX, India) uses so results are comparable. It contains methods only, never current data; current data lives in `base_layer.md`. Where this file and the code disagree, this file governs until the code is fixed. Gaps are flagged as **[code gap]**.

**Read order for every session:**
1. `base_layer.md`: macro, cycle map, anchors, A7 calibration.
2. This file.
3. Local market factors.

**Source-quality tiers (used for confidence in B6):**

| Tier | What it covers | Confidence |
|---|---|---|
| T1 | Company filings and releases, exchange announcements, regulator data | High |
| T2 | Central banks, statistics bureaus, rating agencies, broker research quoting T1 | High–Med |
| T3 | Aggregators (Yahoo/yfinance, Screener, StockAnalysis, Trendlyne, Morningstar quote pages) | Med; check any number that drives a score against T1 |
| T4 | News, blogs, forums, prediction markets, LLM output | Low; never the sole source for a scored number |

---

## B1. Discovery (themes → candidates)

**Start from base_layer.md A3, not from `brains/macro_brain.py`.**
- `MacroBrain.get_macro_trends()` asks the LLM for trends from its own knowledge with no search.
- On a parse failure it falls back to hard-coded `["Generative AI", "Energy Transition"]`.
- **[code gap]:** treat its output as T4 and use it only to cross-check A3.

**Steps per theme, per market:**
1. **First-order beneficiaries:** companies whose revenue is directly the theme, from the A3 seed types.
2. **Second-order (picks and shovels):** walk the supply chain one or two steps upstream. Sources:
   - US 10-K Item 1 (suppliers and customers) and customer-concentration notes
   - Annual-report segment notes (ASX, India)
   - Government contract awards (US: USAspending.gov; India: order-win filings on NSE/BSE; ASX: announcements)
   - Trade-body member lists
3. **Map to listed tickers** with correct suffixes (`.AX`, `.NS`/`.BO`, none for US). `engines/discovery_engine.py` does this step by asking the LLM for exactly 100 tickers from its own knowledge, with no search; its only check is that yfinance returns a last price. Treat its output as T4, like the macro brain. **[code gap]** Verify every ticker resolves before screening.

**Two tracks: a label, never a cut.** Large companies can be badly mispriced too, so size never removes a candidate. Every candidate gets one track label, and both tracks are scored the same way (B6).

| Track | Who belongs | What must be true |
|---|---|---|
| **Hidden gem** | Passes two or more of the "less known" tests below | Phase 0 as normal |
| **Fallen quality** | Fails two or more of the "less known" tests (large, index member, heavily covered) | ≥30% below its 52-week high, quality evidence (moat, ROIC above cost of capital, low leverage) and a negative that looks curable (A7) |

"Less known" tests (count each test once; size and index membership are separate tests and must each be checked, not inferred from each other):

| Test | US | ASX | India |
|---|---|---|---|
| Size | ≤ US$5bn | ≤ A$5bn | ≤ ₹25,000 Cr |
| Index | Not in S&P 500 | Not in ASX 100 | Not in Nifty 100 |
| Analyst coverage | ≤ 8 analysts | ≤ 5 | ≤ 5 |
| Media | No front-page coverage in the last 90 days | Same | Same |

- Large companies that are neither cheap nor fallen (no ≥30% drop) simply fail Phase 0 test 4 as usual.
- Shortlist both tracks separately and rank within each; don't let one track crowd out the other.

**Entry to Phase 0.** Every theme-sourced candidate runs the six Phase 0 tests in the project instructions (survival, cash is real, free cash, curable dip, skin in the game, not pricey) before any thesis work. Then apply:
- **Banks and insurers:** flag, don't score (A7).
- **Cyclicals** in a Peak or Late sector in A4: Phase 0 test 6 uses mid-cycle EPS, not current EPS.
- **Drawdown >70%:** run the A7 checklist before the dip counts as "curable".

Shortlist 15–20 across both tracks, with at least 5 per track where candidates exist.

---

## B2. Strategic intent / hiring signal (replaces the job scraper)

Phase 3 in the README uses Playwright plus DuckDuckGo job scraping. In chat sessions, use this manual method instead.

**Sources**

| | US | ASX | India |
|---|---|---|---|
| Careers ATS | Company careers page (Workday, Greenhouse, Lever, SmartRecruiters) | Same | Same |
| Job boards | LinkedIn job count; Indeed | LinkedIn; Seek | LinkedIn; Naukri |
| Cuts | WARN notices (state sites); 8-K restructuring items | Announcements; media | Exchange filings; quarterly headcount in IT and services releases |
| Capex and expansion | 8-K, earnings calls, 10-Q capex | Announcements, investor days | Board approvals of capex or plants; credit-rating rationales |

**What matters**
- Role mix: R&D/AI, sales in new regions, plant or operations roles.
- Fit: whether hiring matches the stated strategy.
- Layoffs and freezes.
- Concrete steps: new facilities, acquisitions, new-region entry.

**Verdict per stock.** Use **Confirms / Neutral / Contradicts** management's story.
- *Confirms:* hiring or capex moves in the direction of the stated strategy, with dated evidence.
- *Contradicts:* the strategy says growth but there are cuts or freezes, or capex is announced but not started.

**Confidence**
- A single job-board snapshot has no trend, so confidence is **Low** by default.
- Raise to **Med** only with dated change evidence (earnings-call headcount comments, quarter-on-quarter disclosed headcount, WARN filings).
- Raise to **High** only when hiring and capex both appear in T1 filings.

---

## B3. Financials (Market Brain)

**Lookback:** 8 quarters plus 5 fiscal years. Use 8 quarters where they exist, as `brains/market_brain.py` `fetch_quarterly_data()` does via yfinance (`.head(8)`).

**Required metrics**

| Metric | Rule |
|---|---|
| Revenue and EPS trend | Direction over 8 quarters and 5 years |
| Gross and operating margin | Trend; compare to the cycle position in A4 |
| OCF vs net income | "Cash is real" = OCF > 0 and OCF ≥ NI (Phase 0 test 2) |
| FCF and FCF trend | Flag a fall of more than 50% year on year (Phase 0 test 3) |
| Net debt / EBITDA | Survival test: cash ≥ debt, or net debt < 2x EBITDA |
| Receivable days | Flag above 120 days or growing faster than revenue (Chugh "bloated receivables") |
| ROIC vs cost of capital | ROIC = NOPAT / (debt + equity − cash); flag if below ~10% |
| Share-count change | Dilution; flag above 3% a year unless funding visible capex |
| Capital work in progress | India: "CWIP" line; ASX: capital works in the PP&E note; US: construction in progress in the PP&E footnote |

**Code limits in `brains/market_brain.py`. Verify these manually until fixed.**
- `safe_extract()` pulls only five rows: revenue, net income, total debt, cash, FCF.
  - OCF, receivables, CWIP, share count and ROIC are not fetched. **[code gap]**
- It fills missing values with 0, and `generate_report()` prints 0 as "N/A".
  - A genuine zero and a missing value look the same.
  - Sparse half-yearly reporters (most ASX and many Indian small caps) come through as mostly "N/A". **[code gap]**
- Currency normalisation applies today's spot FX to all 8 quarters, so historical trends move with current FX. Judge trends in reporting currency. **[code gap]**
- The `evaluate()` prompt flags P/E > 50. That is looser than Phase 0 (forward P/E 0–25). Phase 0 and B6 govern. **[code gap]**

**When only annual or half-yearly data exists (ASX 4D/4E; Indian small caps on yfinance):**
- Use the last 4 halves plus 5 years from T1 filings.
  - ASX: Appendix 4D, 4E and annual report.
  - India: quarterly results under SEBI LODR on NSE/BSE, and the annual report.
- Annualise only from the latest two halves, and say so. Mark all such figures "(est.)".

**Valuation**
- Forward P/E against the stock's own 5-year range and 2–3 peers.
- EV/EBITDA for capital-heavy businesses.
- Peak or Late sectors (A4): mid-cycle EPS only (A7 low-P/E trap).
- No listed peers: use the A7 rule. Own history, plus earnings yield ≥ local 10y unless growth above 15% is visible in orders.

---

## B4. Regulatory and filings (Regulatory Brain)

**What `brains/regulatory_brain.py` does today**
- **US:** pulls the latest 10-K via `yfinance.get_sec_filings()` and truncates to the first 60,000 characters.
  - Later Item 1A risk factors and much of MD&A can be cut off. **[code gap]**
- **.NS / .BO / .AX / .L:** reads DuckDuckGo snippets and follows only the first result URL (PDFs: first 20 pages).
  - That page may not be the company's own filing.
  - Treat the output as **T4** until the URL is confirmed as the issuer's or the exchange's. **[code gap]**
- **Other suffixes:** no fetch at all.
- The manual sources below take priority.

**Sources and red flags per market**

**US**
- Sources: 10-K and 10-Q (Item 1A changes against the prior year), 8-K, DEF 14A, NT 10-K/10-Q.
- Red flags:
  - Going-concern language
  - 8-K Item 4.01 (auditor change) or 4.02 (non-reliance or restatement)
  - Item 5.02 CFO or CEO exit
  - NT (late) filing
  - Material weakness
  - Large Item 1A additions
  - Customer concentration above 20%
  - ATM or shelf raise while the stock is near lows

**ASX**
- Sources:
  - Annual report, Appendix 4D (half-year) and 4E (preliminary final)
  - Appendix 4C (quarterly cash flow) and 5B (miners)
  - Continuous disclosure, capital raisings (placement, SPP, Appendix 2A/3B)
  - Substantial holder notices (603/604/605)
- Red flags:
  - Fewer than 4 quarters of cash runway on the 4C
  - Repeated placements or discounted SPPs
  - Trading halts pending raise
  - Auditor emphasis of matter
  - ASX price or aware queries
  - Licence or approval dependence

**India**
- Sources:
  - Annual report: notes, related-party transactions, auditor report and CARO, contingent liabilities
  - Quarterly results and shareholding pattern on NSE/BSE
  - Credit rating actions (CRISIL, ICRA, CARE)
  - SAST and pledge disclosures
- Red flags:
  - Auditor qualification or resignation
  - Rising related-party transactions
  - Promoter pledge above 25%, or rising
  - Rating downgrade or "Issuer Not Cooperating"
  - Large contingent liabilities
  - GSM/ESM listing: Chugh calls this an opportunity only if fundamentals are clean, so check the reason

---

## B5. Leadership and insiders

**Sources**

| | US | ASX | India |
|---|---|---|---|
| Insider trades | SEC Form 4; 13D/13G | Appendix 3Y (director's interest) | SEBI PIT disclosures; SAST |
| Ownership | DEF 14A beneficial-ownership table | Annual report; top-20 holders | Quarterly shareholding pattern (promoter % and pledge %) |
| Turnover | 8-K Item 5.02 | Announcements | Exchange filings |

**`fetch_linkedin_data()` in `brains/market_brain.py` is a stub.**
- When a Proxycurl key is set, it returns the fixed string "...has a strong track record of capital allocation" for every officer without calling the API.
- That fabricated line then appears in the report the LLM scores.
- **Never use it as evidence. Fix or remove it before running with a key. [code gap]**

**What counts**
1. **Open-market buying beats everything else.**
   - Option exercises, tax-withholding sales (Form 4 code F) and trust gifts (code G) are neutral.
   - Example: PEGA's September 2026 Form 4 gifts.
2. **Selling clusters** (several insiders within ~30 days, outside a 10b5-1 plan) are negative.
3. **Insider test (A7):**
   - Count founders and their family vehicles and trusts.
   - Do not count corporate parents, governments or PE sponsors.
   - Director buying is a positive note but does not pass the ≥5% test.
4. **CEO or CFO turnover:** a CFO exit within 12 months of a guidance cut is a red flag. An interim CEO counts as moderate risk.
5. **Guidance credibility:** compare promises with delivery over the last 4–6 quarters. Two or more misses or cuts triggers a B6 cap.
6. **Bad times:** check what management did in the last downturn.
   - Positive: cut costs, bought back below intrinsic value, held the dividend from FCF.
   - Negative: issued equity at lows, levered up.
   - Munger "Planck vs chauffeur" test on call transcripts: operational specifics vs buzzwords and macro excuses.

---

## B6. Signal weighting and score

**Weights (sum to 10 points)**

| Section | Points | Inputs |
|---|---|---|
| Wisdom Brain (Three Q) | 3 | Business 1.0 (moat, no peer group, longevity) · Management 1.0 (skin, allocation, credibility) · Balance sheet 1.0 (survival, cash over P&L, CWIP) |
| Financials and valuation | 2.5 | B3 metrics; price vs mid-cycle value |
| Macro and cycle fit | 1 | A3 theme tailwind or headwind; A4 position |
| Strategic intent and hiring | 1.5 | B2 verdict |
| Leadership and insiders | 1 | B5 |
| Regulatory and risks | 1 | B4 (concentration, dilution, policy dependence, litigation) |

**Score caps (apply after summing; the lowest cap wins)**

| Trigger | Max score |
|---|---|
| Going-concern language | 2 |
| Auditor resignation or qualified opinion | 3 |
| Promoter or insider pledge > 50% | 3 |
| Promoter or insider pledge 25–50%, or rising for 2+ quarters | 4 |
| OCF < net income in the latest FY **and** receivable days > 120 (or growing faster than revenue) | 4 |
| Two or more guidance misses or cuts in the last 4–6 quarters | 5 |
| Dilution > 5% a year without visible capex or CWIP | 5 |
| Peak/Late-cycle sector valued on current, not mid-cycle, earnings | Re-score on mid-cycle EPS. No cap; the trap must be removed |

**8+ requires all five parts of the A6 "hypothetical 8 profile":** moat; at most 12–15x mid-cycle earnings or FCF yield above the local 10y; a dated curable negative; net cash with OCF ≥ NI; insider skin of at least 10%. Missing any one caps the score at 7.

**Confidence (show per section)**
- **High:** every scored number is T1, dated within 90 days.
- **Med:** T2 or T3 checked against at least one T1 figure.
- **Low:** T3/T4 only, a single snapshot (default for B2), or conflicting sources.

State conflicts rather than averaging them. Example: Newgen Q1 FY27 profit direction in A6. If two or more sections are Low, the headline verdict must say "low confidence".

**Consistency with base_layer.md.** Insider rules, bank/insurer handling, peerless comparison, curable-vs-structural, drawdown >70%, justified negative FCF, the low-P/E trap and early-refresh triggers are defined once, in A7. This file applies them and never redefines them. If A7 changes, re-check B1, B3, B5 and B6.

*Framework method, not financial advice.*

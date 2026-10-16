# Learnings from the October 2026 run

The first full MA(h)GIC run (15–16 Oct 2026) was done by hand in Claude project chats, not by
this code. It screened the ASX 200 (196 companies), the S&P 500 (503) and 2,272 US small and
mid-caps (pre-filtered to 433), and produced nine full theses. None scored 7 or higher.

| Stock | Market | Track | Score | One-line read |
|---|---|---|---|---|
| Adobe (ADBE) | US | Fallen quality | 6.5 | ~10x earnings, FCF yield above the bond; new ARR growth down, CEO and CFO changing |
| ARB | ASX | Hidden gem | 6.5 | Net cash, ~15x forward; founder stake only ~6% |
| Lovisa (LOV) | ASX | Hidden gem | 6.5 | Sales +17.6%, founder buying; ~23x, CFO resigned |
| Copart (CPRT) | US | Fallen quality | 6 | Net cash; revenue flat, DOJ probe |
| Intuit (INTU) | US | Fallen quality | 6 (or 5) | Mailchimp reset: guidance cut or not is open |
| CAR Group (CAR) | ASX | Fallen quality | 6 | Price fell with no downgrade |
| REA Group (REA) | ASX | Fallen quality | 5.5 | Best business, still ~30x |
| Flight Centre (FLT) | ASX | Hidden gem | 5 | Capped: three guidance cuts or misses |
| Xero (XRO) | ASX | Fallen quality | 5 | Capped: ~10% dilution |

## Data access

| Source | What happened | 2.0 does |
|---|---|---|
| Yahoo Finance | Blocked from sandboxes until the allowlist was extended | Runs locally; no allowlist needed |
| Yahoo rate limits | ~11 of 196 ASX names failed (401/429) | 3 workers, back-off, per-day cache in `data/` |
| Yahoo screener API | Worked: 2,272 US small/mid-caps in 10 calls | Universe source (`us_smallmid`) |
| Index lists | Wikipedia blocked; Market Index refuses bots | CSVs in `config/universes/`, refresh quarterly |
| LinkedIn, Seek, careers pages | Block automated reads | ATS feeds (`fetch/jobs.py`) |
| SEC 10-Ks | Chat page reader stopped at ~120k characters | Full filing split by Item (`fetch/sec.py`) |
| Page-read approvals | Every fetch in a project chat needed a click | Fetches happen in code |
| Yahoo insider % | Counts parents and governments (News Corp in REA) | `flag_insider_check` at ≥20%; B5 confirms |

## Method

- **The screen finds candidates but cannot rank them.** Deep-dives reordered every batch.
- **Guidance credibility is missing from the screen.** Flight Centre was #3 on the screen and 5/10 after three cuts were counted. 2.0 asks the model to confirm the guidance cap for every company.
- **Analyst coverage beats size as the "hidden" test.** All three ASX Hidden gems had 7–9 brokers. 2.0 adds `analyst_count` to the screen.
- **Size must not be a cut.** Two tracks are labels only (playbook v1.2).
- **Caps did real work.** Three of nine were capped. 2.0 applies numeric caps in code.
- **Nothing cleared 7.** In a high-rate year the FCF-yield-vs-bond part of the "hypothetical 8" profile binds.
- **Shared knowledge files kept scores comparable** across markets.

## Cost

The hand run used about a third of a weekly Pro quota and almost two session windows. Most of
it was deep-dives and page reads. 2.0 moves fetching and arithmetic to Python and drafting to a
local model; Claude reviews only the top 3 per track.

## v1 code gaps fixed in 2.0

| v1 | Fix |
|---|---|
| `fetch_linkedin_data()` returned a canned line for every officer | Removed. No ATS feed = recorded gap, Low confidence |
| `safe_extract()` filled missing with 0 | `None` end to end |
| Spot FX applied to all quarters | Reporting currency kept |
| P/E > 50 flag | Phase 0 forward P/E 0–25 from `config/scoring.yaml` |
| 10-K cut at 60k; DuckDuckGo for non-US | Full 10-K by Item; ASX announcements feed |
| Macro and discovery from model memory | Index universes + base layer (refreshed monthly with search) |
| Empty job scraper | ATS feeds with detection |
| Unpinned packages, placeholder SEC User-Agent, no tests | Pinned, `CONTACT_EMAIL` required, offline tests |

## Open decisions

- Is Intuit's Mailchimp reset a guidance cut? (Defines "cut" for playbook v1.3.)
- Chrome as a last-resort hiring source, or accept Low confidence without an ATS feed?
- When to add the Buffett, Lynch and Fisher lenses to the Three Q section.

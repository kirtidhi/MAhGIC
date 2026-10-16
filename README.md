# MA(h)GIC 2.0 — Macro AI (hidden) Gem Intelligence Core

MA(h)GIC finds undervalued companies using Ashish Chugh's Three Q framework (business,
management, balance sheet) plus macro fit, hiring signals, leadership and regulatory checks.
Version 2.0 is built to run **every company in an index, every month, on a local model**:
the full ASX 200 and the US top 100 by market cap, with Claude used only for a second read
of the best names.

v1 (the multi-brain prototype) is kept at tag [`v1.0`](../../tree/v1.0).

## What changed from v1

| | v1 | 2.0 |
|---|---|---|
| Universe | Model names 100 tickers from memory | Index CSV in `config/universes/` or Yahoo's screener API |
| Numbers | 5 rows, missing filled with 0, today's FX on old quarters | Every B3 row, missing stays `null`, reporting currency kept |
| Filings | 10-K cut at 60k chars; non-US = first DuckDuckGo hit | SEC submissions + XBRL + full 10-K split by Item; ASX announcements feed |
| Hiring | Playwright + search, mostly empty; LinkedIn stub returned a canned line | Company's own ATS feed (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Workable, PageUp), monthly snapshots |
| Scoring | Model gives a number | Python computes metrics and caps; model scores sections; Python applies caps and the "hypothetical 8" rule |
| Models | One provider for everything | Per-task routing in `config/models.yaml`: Ollama by default, paid calls capped per run |
| Runs | One shot | Six resumable stages, snapshots in `data/<date>/<market>/<universe>/` |

## Pipeline

```
1 universe  →  2 screen  →  3 fetch  →  4 analyse  →  5 draft  →  6 review + reports
  Python        Python       Python       Python        local LLM    Claude (top 3/track)
                Phase 0      T1/T2/T3     B3 metrics,   B6 section
                6 tests      sources      red flags,    scores as
                + tracks                  hard caps     JSON
```

The rules live in `knowledge/base_layer.md` (dated global view: macro, cycle map, anchors,
calibration) and `knowledge/playbook.md` (fixed method: B1–B6). The draft prompt is built
from their sections; `config/scoring.yaml` holds the same weights and caps in machine form.

## Setup (Mac)

```bash
git clone https://github.com/kirtidhi/MAhGIC.git && cd MAhGIC && git checkout v2
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set CONTACT_EMAIL (SEC needs it); ANTHROPIC_API_KEY optional
set -a; source .env; set +a

# Local model — see docs/LOCAL_LLM.md for which model fits your Mac
brew install ollama             # or download the app from ollama.com
OLLAMA_CONTEXT_LENGTH=16384 ollama serve &   # the desktop app also works; set context to 16k
ollama pull qwen3.5:9b          # 16 GB Mac; confirm the tag on ollama.com/library

python -m mahgic check          # confirms Ollama, the model, and keys
pytest -q                       # offline tests, no network
```

## Running

```bash
# Full monthly run, one market at a time (resumable: re-run the same command after a stop)
python -m mahgic run --market asx --universe asx200
python -m mahgic run --market us  --universe us_top100

# US small/mid-cap Hidden gems from Yahoo's screener
python -m mahgic run --market us --universe us_smallmid

# Pieces
python -m mahgic run --market us --universe us_top100 --stages universe,screen,fetch,analyse   # no LLM
python -m mahgic run --market us --universe us_top100 --tickers ADBE,CPRT --force               # redo two names
python -m mahgic status --market us --universe us_top100                                         # progress
```

Outputs per run, under `data/<date>/<market>/<universe>/`:

- `screen.csv` — Phase 0 for every company, with tracks and flags
- `<TICKER>/thesis_<TICKER>.md` — the thesis: score, section table, caps, key numbers, evidence, verdict
- `summary_<market>_<universe>.md` — every company ranked within its track

Time on a 16 GB M5 MacBook Pro with a 9B model (estimate, not yet measured): stages 1–4 take
about 15–30 minutes per market; drafting takes a few minutes a company (six 10-K chunks plus the
thesis), so the ASX 200 plus the US top 100 is one or two overnight runs. `--max-chunks 3`
shortens it. The first run doubles as the speed test.

## Tracks, not cuts

Every company is scored. The screen labels each one **Hidden gem** (small, under-covered) or
**Fallen quality** (large, out of favour); size never removes a company.

## Known gaps

- ASX annual reports (PDF) are not read yet; ASX B4 relies on the announcements feed.
- Guidance credibility is judged by the model from filings; there is no structured history yet.
- Valuation against a stock's own 5-year P/E range is not computed yet (`pe_5y_median_proxy`).
- India is paused (needs `niftyindices.com` or `nsearchives.nseindia.com`).
- The ASX announcements endpoint is undocumented; the first local run should confirm it.
- Other investor frameworks (Buffett, Lynch, Fisher) will widen the Three Q section later;
  `knowledge/wisdom_corpus.txt` is kept for that.

See `docs/LEARNINGS.md` for what the October 2026 run taught us.

*Framework method, not financial advice.*

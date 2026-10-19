# Running MA(h)GIC 2.0 on a local model

## The setup this was built for

Kirti's 14" MacBook Pro: base M5, 16 GB unified memory (about 12 GB usable for a model).
This follows the plan in the "Setting up a local LLM" project (25 Sep 2026):

| | Choice (measured Oct 2026) |
|---|---|
| Runtime | Ollama 0.17.1+ on localhost only, cloud features off |
| Drafts (`draft_thesis`) | Qwen 3.5 9B `qwen3.5:9b-q4_K_M` at **24k** context, thinking on: ~5–6 min a company, valid JSON first try in 22 of 24 drafts. At 16k its thinking filled the window and no answer came back |
| Reading (`extract_filing`, `extract_guidance`) | Gemma 4 E4B `gemma4:e4b-it-q4_K_M` at 16k: ~25 s a chunk, ~10x faster than Qwen for similar extraction quality |
| Rejected | Gemma 4 12B QAT (thinks longer than Qwen, overflowed 24k, ~17 min a failed draft); 26B/31B do not fit |

Each task names its provider in `config/models.yaml`; `ollama` and `ollama_fast` are two entries
on the same Ollama server. The draft stage reads every company first (Gemma), then drafts every
company (Qwen), so each model loads once; the code unloads one model before loading the other and
waits `model_switch_pause_s` (free memory dipped to 4% once when both were loaded).

**Context overflow.** If thinking + answer outgrow `num_ctx`, the call is logged and retried once
with an instruction to keep the reasoning short, then once at `overflow.retry_num_ctx` (32k).
2 of 13 drafts overflowed at 24k in the Oct 2026 test (MNTN, LOV). With `max_paid_calls_per_run: 0`
nothing is ever sent to a paid model.

Running MA(h)GIC itself needs no sandbox (fixed prompts, public data). The Docker sandbox in the
project plan is for a coding agent that edits the repo.

## What the code decides vs what the model decides

The Oct 2026 Claude-vs-local test (13 companies) found the local drafts scored ~1 point high,
mostly because negative facts never reached the model. So more is now fetched and decided in code:

| Fact | Source (T1) | Decided by |
|---|---|---|
| Guidance cuts / withdrawals / misses | 8-K 2.02 press releases (US), 6-K results (20-F filers), price-sensitive results / guidance / AGM announcements (ASX PDFs) | Gemma lists statements with exact quotes; quotes not found in the document are dropped; Python counts dated negative events; 2+ = cap 5 |
| Insider buying / selling | SEC Form 4 (open-market P/S), Form 144; ASX Appendix 3Y headlines | notes for the model |
| Founder stake registered for resale | S-3 / F-3 / S-1 / F-1 filings | note (insider skin unreliable) |
| Investigations, class actions | phrases in the 10-K and latest 10-Q | note with the quote |
| Latest quarter | 10-Q MD&A, legal proceedings, risk-factor updates (read before the 10-K) | extracts |
| Price test (A6 part 2) | SBC-heavy: FCF yield **after SBC** vs local 10y; cyclicals: price / median 5-year EPS; others: forward P/E <= 15 or FCF yield > 10y | code (the model can no longer overrule it) |
| Founder skin | Yahoo insiders >= 50% is treated as a parent or strategic holder (REA: News Corp) | code |
| Banks / insurers | industrial cash-flow tests (OCF/NI, receivable days, ROIC) skipped | code |
| Track | screen (size) | code |
| CHECK items | the model may confirm one only with a quote found in the facts | code |

## Overnight run

```bash
scripts/night_run.sh            # each night (or install scripts/com.mahgic.nightrun.plist for 23:00)
scripts/night_run.sh --status   # progress
scripts/night_run.sh --new      # start the next deep run (every ~6 months)
```

The script keeps the Mac awake while it runs (lid open, plugged in), stops cleanly at 07:00
(`STOP_AT`), and reuses one run date until ASX 200 and US top 100 are both complete. Finished
work is never redone. Expect ~5–6 nights for the first full run on a 16 GB M5.

One market by hand: `python -m mahgic run --market asx --universe asx200 --date 2026-10-20 --until 07:00`
(exit code 3 = stopped at `--until`; run it again with the same `--date`).

# Running MA(h)GIC 2.0 on a local model

## Pick a model by memory

| Mac memory | Model | Pull | Notes |
|---|---|---|---|
| 16 GB | `qwen3:8b` | `ollama pull qwen3:8b` | Works; weaker on the curable-vs-structural call |
| 32 GB | `qwen3:14b` (default) | `ollama pull qwen3:14b` | Good JSON discipline, ~9 GB |
| 32 GB | `gemma3:27b-it-qat` | `ollama pull gemma3:27b-it-qat` | Stronger reading, slower |
| 64 GB+ | `qwen3:32b` | `ollama pull qwen3:32b` | Best local quality |

Set the model in `config/models.yaml` → `providers.ollama.model`. Keep `num_ctx: 32768`:
the draft prompt is ~6k tokens of rules plus ~6–10k tokens of facts.

## What runs where

| Task (`config/models.yaml → tasks`) | Default | Why |
|---|---|---|
| `extract_filing` | Ollama | Pull facts from 10-K chunks; many calls, low stakes |
| `summarise_jobs` | Ollama | Reserved; jobs are summarised in Python today |
| `draft_thesis` | Ollama | Section scores + narrative as JSON |
| `review_thesis` | Anthropic | Top 3 per track per market only |

Paid calls stop at `max_paid_calls_per_run` (default 12). Set it to `0` for a fully local run.
A draft that fails JSON validation twice locally escalates to the review provider
(`escalate.on_invalid_json`), which also counts against the ceiling.

## Overnight run

```bash
caffeinate -dims &   # keep the Mac awake
python -m mahgic run --market asx --universe asx200 2>&1 | tee -a asx.log
python -m mahgic run --market us --universe us_top100 2>&1 | tee -a us.log
```

If it stops (sleep, network, rate limit), run the same command again; finished work is skipped.
Use `--date YYYY-MM-DD` to resume a run started on an earlier day.

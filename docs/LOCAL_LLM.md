# Running MA(h)GIC 2.0 on a local model

## The setup this was built for

Kirti's 14" MacBook Pro: base M5, 16 GB unified memory (about 12 GB usable for a model).
This follows the plan in the "Setting up a local LLM" project (25 Sep 2026):

| | Choice |
|---|---|
| Runtime | Ollama 0.17.1+ on localhost only, cloud features off (MLX-LM server is the alternative) |
| Model | Qwen 3.5 9B (~7 GB), Gemma 4 E4B (~3 GB) as fallback. Confirm tags on ollama.com/library |
| Context | 16k (`OLLAMA_CONTEXT_LENGTH=16384`); Ollama defaults to 4k under 24 GB and cuts prompts silently |
| Not on this Mac | 12–14B models are slow; Gemma 4 26B/31B do not fit |

Prompts are budgeted for 16k: rules about 5.5k tokens, facts about 2–3k, 10-K extracts read in
~3k-token chunks, leaving room for the answer.

Running MA(h)GIC itself needs no sandbox (fixed prompts, public data). The Docker sandbox in the
project plan is for a coding agent that edits the repo.

With more memory (a Mac mini, say), raise `num_ctx` to 32768 and try a 14B+ model.

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
OLLAMA_CONTEXT_LENGTH=16384 ollama serve &   # or set it in the Ollama app
caffeinate -dims &   # keep the Mac awake
python -m mahgic run --market asx --universe asx200 2>&1 | tee -a asx.log
python -m mahgic run --market us --universe us_top100 2>&1 | tee -a us.log
```

If it stops (sleep, network, rate limit), run the same command again; finished work is skipped.
Use `--date YYYY-MM-DD` to resume a run started on an earlier day.

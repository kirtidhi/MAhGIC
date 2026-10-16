# Contributing to MA(h)GIC

We welcome contributions! Please open an issue before submitting major pull requests.
1. Fork the repo.
2. Create a feature branch.
3. Commit your changes.
4. Push to the branch and submit a PR.

## Notes for AI Agents

Run 2.0 non-interactively. Before a run, confirm with the user in chat:
1. **Market and universe** (e.g. `asx asx200`, `us us_top100`, `us us_smallmid`)
2. **Stages** (all, or `universe,screen,fetch,analyse` for a no-LLM pass)
3. Whether paid review calls are allowed (`max_paid_calls_per_run` in `config/models.yaml`)

```bash
python -m mahgic check
python -m mahgic run --market us --universe us_top100
python -m mahgic status --market us --universe us_top100
```

Never fill a missing number or hiring signal with a guess; record the gap.

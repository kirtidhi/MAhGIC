"""MA(h)GIC 2.0 command line.

  python -m mahgic run --market asx --universe asx200
  python -m mahgic run --market us --universe us_top100 --stages screen,fetch,analyse
  python -m mahgic run --market us --universe us_top100 --tickers CPRT,ADBE --force
  python -m mahgic status --market us --universe us_top100
  python -m mahgic check            # Ollama reachable? model pulled? CONTACT_EMAIL set?
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import RunContext, markets, models
from .pipeline import STAGES, Pipeline


def check() -> int:
    import requests

    ok = True
    m = models()["providers"]["ollama"]
    try:
        tags = requests.get(f"{m['base_url']}/api/tags", timeout=5).json()
        names = [t["name"] for t in tags.get("models", [])]
        has = any(n == m["model"] or n.startswith(m["model"] + ":") for n in names)
        print(f"Ollama: up. Models: {', '.join(names) or 'none'}")
        if not has:
            ok = False
            print(f"  -> run: ollama pull {m['model']}")
    except Exception as e:
        ok = False
        print(f"Ollama: not reachable at {m['base_url']} ({e}). Start the Ollama app or `ollama serve`.")
    print("CONTACT_EMAIL:", "set" if os.environ.get("CONTACT_EMAIL") else "MISSING (needed for SEC)")
    print("ANTHROPIC_API_KEY:", "set" if os.environ.get("ANTHROPIC_API_KEY") else "not set (review stage will be skipped)")
    return 0 if ok else 1


def status(ctx: RunContext) -> None:
    from .store import Store

    s = Store(ctx)
    for stage in ("info", "fundamentals", "filings", "jobs", "analysis", "extracts", "draft", "review"):
        print(f"{stage:13s} {len(s.tickers_with(stage))}")
    for err in ("fetch_error", "draft_error"):
        bad = s.tickers_with(err)
        if bad:
            print(f"{err:13s} {len(bad)}: {', '.join(bad[:20])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mahgic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "status"):
        p = sub.add_parser(name)
        p.add_argument("--market", required=True, choices=[k for k, v in markets().items() if v.get("enabled", True)])
        p.add_argument("--universe", required=True)
        p.add_argument("--date", help="resume an earlier run (YYYY-MM-DD)")
        if name == "run":
            p.add_argument("--stages", default=",".join(STAGES))
            p.add_argument("--tickers", help="comma list, to (re)run a few names")
            p.add_argument("--limit", type=int)
            p.add_argument("--force", action="store_true", help="redo stages even if outputs exist")
            p.add_argument("--workers", type=int, default=3)
            p.add_argument("--max-chunks", type=int, default=6, help="10-K chunks read per company")
    sub.add_parser("check")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    if a.cmd == "check":
        return check()
    ctx = RunContext(a.market, a.universe, **({"run_date": a.date} if a.date else {}))
    if a.cmd == "status":
        status(ctx)
        return 0
    pipe = Pipeline(ctx, force=a.force, limit=a.limit, workers=a.workers, max_chunks=a.max_chunks,
                    tickers=[t.strip().upper() for t in a.tickers.split(",")] if a.tickers else None)
    pipe.run([s.strip() for s in a.stages.split(",")])
    return 0


if __name__ == "__main__":
    sys.exit(main())

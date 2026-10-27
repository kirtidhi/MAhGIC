"""MA(h)GIC 2.0 command line.

  python -m mahgic run --market asx --universe asx200
  python -m mahgic run --market us --universe us_top100 --stages screen,fetch,analyse
  python -m mahgic run --market us --universe us_top100 --tickers CPRT,ADBE --force
  python -m mahgic status --market us --universe us_top100
  python -m mahgic run --market asx --universe asx200 --date 2026-10-20 --until 07:00   # one night
  python -m mahgic check            # Ollama reachable? models pulled? CONTACT_EMAIL set?
  scripts/night_run.sh              # the multi-night first run (see the script header)
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
    m = models()
    from .llm.providers import impl_of
    local = {n: c for n, c in m["providers"].items()
             if impl_of(n) == "ollama" and n in set(m["tasks"].values())}
    for name, c in local.items():
        try:
            tags = requests.get(f"{c['base_url']}/api/tags", timeout=5).json()
            names = [t["name"] for t in tags.get("models", [])]
            has = any(n == c["model"] or n.startswith(c["model"] + ":") for n in names)
            tasks = ", ".join(t for t, prov in m["tasks"].items() if prov == name)
            print(f"Ollama [{name}] {c['model']} num_ctx={c.get('num_ctx')} for: {tasks} -> "
                  f"{'pulled' if has else 'MISSING'}")
            if not has:
                ok = False
                print(f"  -> run: ollama pull {c['model']}")
        except Exception as e:
            ok = False
            print(f"Ollama: not reachable at {c['base_url']} ({e}). Start the Ollama app or `ollama serve`.")
            break
    print("Paid calls allowed per run:", m.get("max_paid_calls_per_run", 0))
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


def pack(ctx: RunContext, tickers: list[str]) -> int:
    """Review packs for a Claude review: data/<date>/<market>/<universe>/<T>/pack_<T>.md and one
    combined packs_<market>.md. Uses only the fast local model; about 3 minutes a company."""
    import time

    from .analyse import score as score_mod
    from .config import scoring
    from .report import pack as pack_mod
    from .store import Store

    s, cfg = Store(ctx), scoring()
    mp, out = score_mod.max_points(cfg), []
    pipe = Pipeline(ctx)
    for i, t in enumerate(tickers, 1):
        if not s.has(t, "analysis"):
            logging.warning("%s: no analysis for this run date; skipped", t)
            continue
        t0 = time.time()
        pipe._analysis(t)  # current rules (e.g. the fund-manager fix) before the pack is written
        md = pack_mod.build(t, s, cfg, mp)
        s.save_text(t, f"pack_{t}", md)
        out.append(md)
        logging.info("[pack %d/%d] %s in %.0fs", i, len(tickers), t, time.time() - t0)
    p = ctx.dir / f"packs_{ctx.market}.md"
    p.write_text("\n\n---\n\n".join(out))
    logging.info("Wrote %s (%d packs)", p, len(out))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mahgic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "status", "pack"):
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
            p.add_argument("--max-chunks", type=int, default=6, help="filing chunks read per company")
            p.add_argument("--max-guidance-docs", type=int, default=5,
                           help="results releases / ASX guidance announcements read per company")
        if name == "pack":
            p.add_argument("--tickers", required=True, help="comma list of companies to prepare review packs for")
        if name == "run":
            p.add_argument("--until", help="stop cleanly at this local time (HH:MM, e.g. 07:00); "
                                           "resume the next night with the same --date")
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
    if a.cmd == "pack":
        return pack(ctx, [t.strip().upper() for t in a.tickers.split(",") if t.strip()])
    until = None
    if a.until:
        from datetime import datetime, timedelta
        hh, mm = (int(x) for x in a.until.split(":"))
        now = datetime.now()
        until = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if until <= now:
            until += timedelta(days=1)
        logging.info("Will stop at %s", until.strftime("%Y-%m-%d %H:%M"))
    pipe = Pipeline(ctx, force=a.force, limit=a.limit, workers=a.workers, max_chunks=a.max_chunks,
                    until=until, max_guidance_docs=a.max_guidance_docs,
                    tickers=[t.strip().upper() for t in a.tickers.split(",")] if a.tickers else None)
    pipe.run([s.strip() for s in a.stages.split(",")])
    return 3 if pipe.stopped else 0  # 3 = stopped at --until, resume next night


if __name__ == "__main__":
    sys.exit(main())

"""`python -m mahgic reprice`: refresh prices after a market move, without any model calls.

Nov 2026: the market fell sharply on 5 Nov, after the 22 Oct run was drafted. Prices drive the
price test (forward P/E, FCF yield), the track (30% below the high = fallen quality) and the caps,
so stale prices mean stale scores. This refetches Yahoo's quote data for the same companies
(membership is kept fixed, even where a top-N-by-size universe would now differ), keeps the old
quote as info_prev.json, rebuilds screen.csv, recomputes metrics and red flags, re-scores every
stored draft and re-renders the theses. The written paragraphs are NOT rewritten: the change
report lists the companies whose story may have changed, to redraft with
`python -m mahgic run --stages draft,review --tickers ... --force`.
"""
from __future__ import annotations

import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd

from . import screen as screen_mod
from .store import Store

log = logging.getLogger("mahgic")


def _old_scores(ctx, store, tickers) -> dict:
    out = {}
    for t in tickers:
        p = store.path(t, f"thesis_{t}", "md")
        if p.exists():
            m = re.search(r"## Score: ([\d.]+)", p.read_text())
            if m:
                out[t] = float(m.group(1))
    return out


def run(ctx, pipeline, workers: int = 3) -> int:
    store = Store(ctx)
    sc = ctx.dir / "screen.csv"
    old = pd.read_csv(sc)
    tickers = old["ticker"].tolist()
    stamp = date.today().isoformat()
    backup = ctx.dir / f"screen_before_reprice_{stamp}.csv"
    if not backup.exists():
        shutil.copy(sc, backup)
    old_scores = _old_scores(ctx, store, tickers)

    def work(t):
        prev = store.load(t, "info")
        info = screen_mod.fetch_info(t)
        if not info:
            return t, False
        info.setdefault("symbol", t)
        if prev and not store.has(t, "info_prev"):
            store.save(t, "info_prev", prev)
        store.save(t, "info", info)
        return t, True

    failed = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, ok in ex.map(work, tickers):
            if not ok:
                failed.append(t)
    log.info("Reprice: %d refreshed, %d kept old prices (Yahoo gave nothing): %s",
             len(tickers) - len(failed), len(failed), ", ".join(failed[:20]))

    rows = []
    for t in tickers:
        info = store.load(t, "info")
        if info:
            rows.append(screen_mod.phase0(info, fcf_prev=screen_mod._prev_year_fcf(store.load(t, "fundamentals"))))
    new = screen_mod.assign_tracks(pd.DataFrame(rows), ctx)
    new = new.sort_values(["score", "drawdown_from_high"], ascending=[False, False], na_position="last")
    new.to_csv(sc, index=False)

    for t in tickers:  # metrics + red flags on the new prices
        if store.has(t, "info"):
            pipeline._analysis(t)
    pipeline.review()  # re-score stored drafts, re-render theses and the summary

    new_scores = _old_scores(ctx, store, tickers)
    o = old.set_index("ticker")
    n = new.set_index("ticker")
    changes = []
    for t in tickers:
        if t not in n.index:
            continue
        p0, p1 = o.at[t, "price"] if t in o.index else None, n.at[t, "price"]
        move = (p1 / p0 - 1) if p0 and p1 and not pd.isna(p0) and not pd.isna(p1) else None
        tr0, tr1 = (o.at[t, "track"] if t in o.index else None), n.at[t, "track"]
        s0, s1 = old_scores.get(t), new_scores.get(t)
        nm = re.sub(r"\s+FPO\s*\[.*\]$", "", str(n.at[t, "name"])).title() if "FPO" in str(n.at[t, "name"]) else n.at[t, "name"]
        changes.append({"ticker": t, "name": nm, "price_then": p0, "price_now": p1, "move": move,
                        "track_then": tr0, "track_now": tr1, "score_then": s0, "score_now": s1,
                        "below_high": n.at[t, "drawdown_from_high"]})
    df = pd.DataFrame(changes)
    df.to_csv(ctx.dir / f"reprice_{stamp}.csv", index=False)
    p = ctx.dir / f"reprice_{stamp}.md"
    p.write_text(report(df, ctx, stamp, failed))
    log.info("Wrote %s", p)
    return 0


def _px(x):
    return "n/a" if x is None or pd.isna(x) else f"{x:,.2f}"


def _pct(x):
    return "n/a" if x is None or pd.isna(x) else f"{x:+.1%}"


def report(df: pd.DataFrame, ctx, stamp: str, failed: list[str]) -> str:
    names = {"hidden_gem": "Hidden gem", "fallen_quality": "Fallen quality", "large": "Large"}
    mv = df["move"].dropna()
    L = [f"# Reprice {ctx.market} / {ctx.universe}: {stamp}", "",
         f"Prices refreshed for {len(df)} companies (run date {ctx.run_date}). Median move {mv.median():+.1%}; "
         f"{(mv <= -0.10).sum()} fell 10% or more. Scores re-applied with the code's price test and caps; "
         "the written paragraphs were not rewritten.", ""]
    if failed:
        L += [f"Yahoo returned nothing for {len(failed)}, so they keep old prices: {', '.join(failed)}", ""]

    tr = df[df["track_then"] != df["track_now"]]
    L += [f"## Track changes ({len(tr)})", "", "| Company | Move | Then | Now | Below high |", "|---|---|---|---|---|"]
    L += [f"| {r.ticker} {r['name']} | {_pct(r.move)} | {names.get(r.track_then, r.track_then)} | "
          f"{names.get(r.track_now, r.track_now)} | {_pct(-r.below_high) if pd.notna(r.below_high) else 'n/a'} |"
          for _, r in tr.iterrows()]

    sc = df[(df["score_now"].notna()) & (df["score_then"].notna())]
    sc = sc[(sc["score_now"] - sc["score_then"]).abs() >= 0.5].sort_values("score_now", ascending=False)
    L += ["", f"## Score changes of 0.5 or more ({len(sc)})", "", "| Company | Move | Score then | Score now |",
          "|---|---|---|---|"]
    L += [f"| {r.ticker} {r['name']} | {_pct(r.move)} | {r.score_then:.1f} | {r.score_now:.1f} |"
          for _, r in sc.iterrows()]

    redo = df[(df["move"].abs() >= 0.15) | (df["track_then"] != df["track_now"])
              | ((df["score_now"] - df["score_then"]).abs() >= 0.5)]
    L += ["", f"## Redraft candidates ({len(redo)})", "",
          "Price moved 15% or more, track changed, or score moved 0.5 or more: the written verdict may be out of date.",
          "", "```", f"python -m mahgic run --market {ctx.market} --universe {ctx.universe} --date {ctx.run_date} "
          f"--stages draft,review --force --tickers {','.join(redo['ticker'])}", "```", ""]
    big = df.sort_values("move").head(15)
    L += ["## Biggest falls", "", "| Company | Then | Now | Move |", "|---|---|---|---|"]
    L += [f"| {r.ticker} {r['name']} | {_px(r.price_then)} | {_px(r.price_now)} | {_pct(r.move)} |"
          for _, r in big.iterrows()]
    return "\n".join(L) + "\n"

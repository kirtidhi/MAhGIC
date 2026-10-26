"""Market summary: one table of every analysed company, ranked within track."""
from __future__ import annotations

import pandas as pd


def build(rows: list[dict], run_meta: dict) -> str:
    if not rows:
        return "# No companies analysed\n"
    df = pd.DataFrame(rows).sort_values(["track", "score", "raw"], ascending=[True, False, False])
    L = [f"# MA(h)GIC {run_meta['market'].upper()} / {run_meta['universe']} — {run_meta['date']}", "",
         f"Analysed {len(df)} companies. Drafts: {run_meta.get('draft_model')}. "
         + (f"Reviews: {run_meta.get('review_model')} on the top {run_meta.get('review_top_n')} per track. "
            if run_meta.get("paid_calls") else "Reviews: none (fully local run; paid calls off). ")
         + f"Paid calls used: {run_meta.get('paid_calls', 0)}. Ties are ordered by raw score.", ""]
    order = {"hidden_gem": 0, "fallen_quality": 1, "large": 2}
    titles = {"hidden_gem": "Hidden gems (passes 2+ less-known tests)",
              "fallen_quality": "Fallen quality (large, 30%+ below its high)",
              "large": "Large, not fallen (no setup: no 30% fall)"}
    for track, g in sorted(df.groupby("track"), key=lambda kv: order.get(kv[0], 9)):
        L += [f"## {titles.get(track, track.replace('_', ' ').title())}", "",
              "| # | Ticker | Name | Score | Raw | Cap | Phase 0 | Low conf. | Reviewed | One line |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(g.to_dict("records"), 1):
            cap = "" if pd.isna(r["cap"]) else f"{r['cap']:g}"
            p0 = "fin." if pd.isna(r["phase0"]) else f"{int(r['phase0'])}/6"
            L.append(f"| {i} | {r['ticker']} | {r['name'] or ''} | {r['score']} | {r['raw']} | {cap} | {p0} | "
                     f"{'yes' if r['low_conf'] else ''} | {'yes' if r['reviewed'] else ''} | {(r['one_line'] or '')[:140]} |")
        L.append("")
    L.append("*Framework method, not financial advice.*")
    return "\n".join(L)

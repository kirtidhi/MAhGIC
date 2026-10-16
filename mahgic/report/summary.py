"""Market summary: one table of every analysed company, ranked within track."""
from __future__ import annotations

import pandas as pd


def build(rows: list[dict], run_meta: dict) -> str:
    if not rows:
        return "# No companies analysed\n"
    df = pd.DataFrame(rows).sort_values(["track", "score"], ascending=[True, False])
    L = [f"# MA(h)GIC {run_meta['market'].upper()} / {run_meta['universe']} — {run_meta['date']}", "",
         f"Analysed {len(df)} companies. Drafts: {run_meta.get('draft_model')}. "
         f"Reviews: {run_meta.get('review_model')} on the top {run_meta.get('review_top_n')} per track. "
         f"Paid calls used: {run_meta.get('paid_calls', 0)}.", ""]
    for track, g in df.groupby("track"):
        L += [f"## {track.replace('_', ' ').title()}", "",
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

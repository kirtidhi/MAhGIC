"""`python -m mahgic combine`: every thesis of a run in one readable file (Markdown + HTML).

Grouped by track (hidden gem, fallen quality, large), highest score first, with a contents list
per track. Open the .html in a browser.
"""
from __future__ import annotations

import csv
import html
import re

ORDER = {"hidden_gem": 0, "fallen_quality": 1, "large": 2}
NAMES = {"hidden_gem": "Hidden gems", "fallen_quality": "Fallen quality", "large": "Large, no setup"}
CSS = ("body{font-family:-apple-system,Helvetica,sans-serif;max-width:860px;margin:2em auto;padding:0 16px;"
       "line-height:1.5;color:#222}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 8px}"
       "h1{margin-top:2em}h2{margin-top:2.2em;border-top:2px solid #333;padding-top:.6em}"
       "blockquote{color:#555;border-left:3px solid #ccc;margin-left:0;padding-left:12px}")


def build(run_dir, store, title: str) -> tuple[str, str]:
    tracks = {}
    sc = run_dir / "screen.csv"
    if sc.exists():
        tracks = {r["ticker"]: r.get("track") for r in csv.DictReader(open(sc))}
    rows = []
    for t in store.tickers_with("draft"):
        p = store.path(t, f"thesis_{t}", "md")
        if not p.exists():
            continue
        txt = p.read_text()
        m, r = re.search(r"## Score: ([\d.]+)", txt), re.search(r"Raw ([\d.]+)", txt)
        d = store.load(t, "draft") or {}
        rows.append({"t": t, "score": float(m.group(1)) if m else 0.0, "raw": float(r.group(1)) if r else 0.0,
                     "track": tracks.get(t) or d.get("track") or "large", "one": d.get("one_line", ""),
                     "verdict": d.get("verdict", ""), "txt": txt})
    rows.sort(key=lambda x: (ORDER.get(x["track"], 3), -x["score"], -x["raw"]))
    out = [f"# {title}: every company the local model analysed", "",
           f"{len(rows)} companies, written by the local model. Not reviewed by Claude unless a Claude "
           "report says so. Framework analysis, not financial advice."]
    cur = None
    for x in rows:
        if x["track"] != cur:
            cur = x["track"]
            group = [y for y in rows if y["track"] == cur]
            out += ["", f"# {NAMES.get(cur, cur)} ({len(group)})", ""]
            out += [f"- **{y['t']}** {y['score']:.1f}: {y['one']}" for y in group]
            out.append("")
        body = re.sub(r"^## ", "### ", x["txt"], flags=re.M)
        body = re.sub(r"^# ", "## ", body, count=1, flags=re.M)
        if x["verdict"]:
            body = body.replace("\n### Score", f"\n**Verdict:** {x['verdict']}\n\n### Score", 1)
        out += ["", body]
    md = "\n".join(out)
    try:
        import markdown

        h = markdown.markdown(md, extensions=["tables"])
    except Exception:
        h = "<pre>" + html.escape(md) + "</pre>"
    page = f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title><style>{CSS}</style>{h}"
    return md, page

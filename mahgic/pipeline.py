"""The six stages. Each is resumable per ticker; re-running skips finished work.

  1 universe   config CSV or Yahoo screener            (Python)
  2 screen     Phase 0 six tests, tracks, flags          (Python, Yahoo T3)
  3 fetch      statements, filings, job boards           (Python, T1/T2/T3)
  4 analyse    B3 metrics, B4/B5 red flags, hard caps    (Python)
  5 draft      filing extracts + B6 section scores       (local LLM)
  6 review     second read of the top N per track        (Claude) + reports
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd

from . import screen as screen_mod
from . import universe as universe_mod
from .analyse import metrics as metrics_mod
from .analyse import redflags as redflags_mod
from .analyse import score as score_mod
from .config import DATA_DIR, RunContext, models, scoring
from .fetch import asx as asx_mod
from .fetch import fundamentals as fund_mod
from .fetch import jobs as jobs_mod
from .llm import prompts
from .llm import providers as llm
from .report import summary as summary_mod
from .report import thesis as thesis_mod
from .store import Store

log = logging.getLogger("mahgic")
CHUNK = 12000  # characters of 10-K text per extract call
STAGES = ["universe", "screen", "fetch", "analyse", "draft", "review"]


class Pipeline:
    def __init__(self, ctx: RunContext, force: bool = False, limit: int | None = None,
                 tickers: list[str] | None = None, workers: int = 3, max_chunks: int = 6):
        self.ctx, self.force, self.limit, self.only, self.workers = ctx, force, limit, tickers, workers
        self.max_chunks = max_chunks
        self.store = Store(ctx)
        self.cfg = scoring()

    # ---------- helpers ----------
    def _need(self, t: str, stage: str) -> bool:
        return self.force or not self.store.has(t, stage)

    def selected(self) -> list[str]:
        p = self.ctx.dir / "screen.csv"
        if not p.exists():
            raise RuntimeError("Run the screen stage first")
        df = pd.read_csv(p)
        ts = df["ticker"].tolist()
        if self.only:
            ts = [t for t in ts if t in self.only]
        return ts[: self.limit] if self.limit else ts

    def screen_row(self, t: str) -> dict:
        df = pd.read_csv(self.ctx.dir / "screen.csv")
        r = df[df["ticker"] == t]
        return {} if r.empty else {k: (None if pd.isna(v) else v) for k, v in r.iloc[0].to_dict().items()}

    def previous_jobs(self, t: str) -> dict | None:
        """Latest earlier snapshot of this ticker's job board, for month-on-month change."""
        for d in sorted(DATA_DIR.glob(f"*/{self.ctx.market}/*/{t}/jobs.json"), reverse=True):
            if not str(d).startswith(str(self.ctx.dir)):
                import json
                prev = json.loads(d.read_text())
                return {"date": d.parts[-5], "summary": prev.get("summary")}
        return None

    # ---------- stages ----------
    def universe(self):
        return universe_mod.load(self.ctx)

    def screen(self):
        uni = pd.read_csv(self.ctx.dir / "universe.csv") if (self.ctx.dir / "universe.csv").exists() else self.universe()
        return screen_mod.run(self.ctx, uni, workers=self.workers, force=self.force)

    def fetch(self):
        since = (date.fromisoformat(self.ctx.run_date) - timedelta(days=548)).isoformat()  # ~6 quarters
        filings_src = self.ctx.market_cfg.get("filings")
        def get_filings(t):
            if filings_src == "sec":
                from .fetch import sec as sec_mod
                rec = sec_mod.fetch(t, since)
                items = rec.pop("_10k_items", None)
                if items:
                    self.store.save(t, "10k_items", items)
                return rec
            if filings_src == "asx":
                return asx_mod.fetch(t)
            return {"ticker": t, "note": "no filings source for this market"}

        def get_jobs(t):
            rec = jobs_mod.fetch(t, (self.store.load(t, "info") or {}).get("website"))
            prev = self.previous_jobs(t)
            if prev:
                rec["previous_summary"] = prev
            return rec

        parts = {"fundamentals": fund_mod.fetch, "filings": get_filings, "jobs": get_jobs}
        for i, t in enumerate(self.selected(), 1):
            errors = {}
            for stage, fn in parts.items():
                if not self._need(t, stage):
                    continue
                try:  # one source failing never stops the others, or the batch
                    self.store.save(t, stage, fn(t))
                except Exception as e:
                    errors[stage] = str(e)[:400]
            if errors:
                self.store.save(t, "fetch_error", errors)
                log.warning("[fetch %d] %s partial: %s", i, t, ", ".join(errors))
            else:
                log.info("[fetch %d] %s ok", i, t)

    def analyse(self):
        for t in self.selected():
            if not self._need(t, "analysis"):
                continue
            info, fund = self.store.load(t, "info") or {}, self.store.load(t, "fundamentals") or {}
            m = metrics_mod.compute(info, fund, self.cfg)
            filings, jobs = self.store.load(t, "filings"), self.store.load(t, "jobs")
            if not filings or filings.get("error"):
                m["data_gaps"].append("filings (T1) unavailable: B4/B5 Low confidence")
            if not jobs or jobs.get("status") != "ok":
                m["data_gaps"].append("no job-board feed: B2 Low confidence")
            rf = redflags_mod.evaluate(m, filings, self.cfg)
            self.store.save(t, "analysis", {"metrics": m, "redflags": rf})

    def _extract(self, t: str) -> dict | None:
        if not self._need(t, "extracts") and self.store.has(t, "extracts"):
            return self.store.load(t, "extracts")
        items = self.store.load(t, "10k_items")
        if not items:
            return None
        # Priority: risk factors, MD&A, business. ~12k chars (~3k tokens) per chunk fits 16k context.
        order = [k for k in ("1A", "7", "1") if k in items]
        chunks = []
        for k in order:
            body = items[k]
            for s in range(0, len(body), CHUNK):
                chunks.append((k, body[s:s + CHUNK]))
        chunks = chunks[: self.max_chunks]
        merged: dict = {}
        for k, c in chunks:
            try:
                data, _ = llm.call_json("extract_filing", prompts.EXTRACT_SYSTEM, f"10-K Item {k}:\n\n{c}")
            except Exception as e:
                log.warning("%s extract Item %s failed: %s", t, k, e)
                continue
            for key, v in data.items():
                if isinstance(v, list):
                    merged.setdefault(key, []).extend(v)
                elif v and v != "n/a":
                    merged.setdefault(key, []).append(v)
        merged = {k: list(dict.fromkeys(map(str, v)))[:12] for k, v in merged.items()}
        merged["_chunks_read"] = f"{len(chunks)} of {sum(-(-len(items[k]) // CHUNK) for k in order)}"
        self.store.save(t, "extracts", merged)
        return merged

    def draft(self):
        mp = score_mod.max_points(self.cfg)
        system = prompts.draft_system(self.ctx.market)

        def validate(d):
            for s in score_mod.SECTIONS:
                float(d["sections"][s]["points"])

        for i, t in enumerate(self.selected(), 1):
            if not self._need(t, "draft"):
                continue
            a = self.store.load(t, "analysis")
            if not a:
                continue
            t0 = time.time()
            try:
                extracted = self._extract(t)
                user = prompts.facts_pack(self.screen_row(t), a["metrics"], a["redflags"],
                                          self.store.load(t, "filings"), self.store.load(t, "jobs"), extracted, mp)
                d, meta = llm.call_json("draft_thesis", system, f"COMPANY: {t}\n\nFACTS\n=====\n{user}", validate)
                d["_meta"] = meta
                self.store.save(t, "draft", d)
                log.info("[draft %d] %s in %.0fs", i, t, time.time() - t0)
            except Exception as e:
                log.warning("[draft %d] %s failed: %s", i, t, e)
                self.store.save(t, "draft_error", {"error": str(e)[:500]})

    def review(self):
        """Score every draft, send the top N per track to the review model, write reports."""
        mp = score_mod.max_points(self.cfg)
        m = models()
        rows = []
        for t in self.selected():
            d, a = self.store.load(t, "draft"), self.store.load(t, "analysis")
            if not (d and a):
                continue
            info, row = self.store.load(t, "info") or {}, self.screen_row(t)
            s = score_mod.final(d, a["redflags"], a["metrics"], info, self.cfg)
            rows.append({"ticker": t, "name": row.get("name"), "track": d.get("track") or row.get("track"),
                         "score": s["score"], "raw": s["raw"], "cap": s.get("binding_cap"),
                         "phase0": row.get("score"), "low_conf": s["low_confidence"], "one_line": d.get("one_line"),
                         "reviewed": False, "_s": s})

        top_n = m["escalate"].get("review_top_n_per_track", 3)
        review_provider = m["tasks"].get("review_thesis")
        df = pd.DataFrame(rows)
        to_review = set()
        if not df.empty and review_provider and m.get("max_paid_calls_per_run", 0) > 0:
            for _, g in df.sort_values("score", ascending=False).groupby("track"):
                to_review |= set(g.head(top_n)["ticker"])

        meta = {"date": self.ctx.run_date, "market": self.ctx.market, "universe": self.ctx.universe,
                "draft_model": m["providers"]["ollama"]["model"], "max_points": mp,
                "review_model": m["providers"].get(review_provider, {}).get("model"), "review_top_n": top_n}
        for r in rows:
            t = r["ticker"]
            d, a = self.store.load(t, "draft"), self.store.load(t, "analysis")
            rev = self.store.load(t, "review")
            if t in to_review and (rev is None or self.force):
                try:
                    md = thesis_mod.render(t, self.screen_row(t), a["metrics"], a["redflags"], d, r["_s"], None, meta)
                    facts = prompts.facts_pack(self.screen_row(t), a["metrics"], a["redflags"],
                                               self.store.load(t, "filings"), self.store.load(t, "jobs"),
                                               self.store.load(t, "extracts"), mp)
                    rev, _ = llm.call_json("review_thesis", prompts.REVIEW_SYSTEM,
                                           f"DRAFT\n=====\n{md}\n\nFACTS\n=====\n{facts}")
                    self.store.save(t, "review", rev)
                except Exception as e:
                    log.warning("review %s failed: %s", t, e)
                    rev = None
            if rev:
                # The reviewer's section points and cap calls replace the draft's
                secs = {k: dict(v or {}) for k, v in (d.get("sections") or {}).items()}
                for k, v in (rev.get("section_points") or {}).items():
                    if k in secs and isinstance(v, (int, float)):
                        secs[k]["points"] = v
                d2 = {**d, "sections": secs,
                      "caps_confirmed": rev.get("caps_confirmed") or d.get("caps_confirmed", [])}
                r["_s"] = score_mod.final(d2, a["redflags"], a["metrics"], self.store.load(t, "info") or {}, self.cfg)
                r.update(score=r["_s"]["score"], raw=r["_s"]["raw"], cap=r["_s"].get("binding_cap"), reviewed=True)
            md = thesis_mod.render(t, self.screen_row(t), a["metrics"], a["redflags"], d, r["_s"], rev, meta)
            self.store.save_text(t, f"thesis_{t}", md)

        meta["paid_calls"] = llm.paid_calls_used()
        out = summary_mod.build([{k: v for k, v in r.items() if k != "_s"} for r in rows], meta)
        p = self.ctx.dir / f"summary_{self.ctx.market}_{self.ctx.universe}.md"
        p.write_text(out)
        log.info("Wrote %s (%d companies, %d reviewed)", p, len(rows), sum(r["reviewed"] for r in rows))
        return p

    def run(self, stages: list[str]):
        for s in STAGES:
            if s in stages:
                log.info("== %s ==", s)
                getattr(self, s)()

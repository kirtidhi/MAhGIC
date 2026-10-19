"""The six stages. Each is resumable per ticker; re-running skips finished work.

  1 universe   config CSV or Yahoo screener            (Python)
  2 screen     Phase 0 six tests, tracks, flags          (Python, Yahoo T3)
  3 fetch      statements, filings, job boards           (Python, T1/T2/T3)
  4 analyse    B3 metrics, B4/B5 red flags, hard caps    (Python)
  5 draft      filing extracts + B6 section scores       (local LLM)
  6 review     second read of the top N per track        (Claude) + reports
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta

import pandas as pd

from . import screen as screen_mod
from . import universe as universe_mod
from .analyse import metrics as metrics_mod
from .analyse import redflags as redflags_mod
from .analyse import score as score_mod
from .config import DATA_DIR, RunContext, models, scoring
from .fetch import asx as asx_mod
from .fetch import fundamentals as fund_mod
from .fetch import guidance as guidance_mod
from .fetch import jobs as jobs_mod
from .llm import prompts
from .llm import providers as llm
from .report import summary as summary_mod
from .report import thesis as thesis_mod
from .store import Store

log = logging.getLogger("mahgic")
CHUNK = 12000  # characters of filing text per extract call (~3k tokens; fits Gemma at 16k)
JUNK = {"", "[]", "{}", "n/a", "na", "none", "null", "not mentioned", "not applicable", "-"}
STAGES = ["universe", "screen", "fetch", "analyse", "draft", "review"]


class Pipeline:
    def __init__(self, ctx: RunContext, force: bool = False, limit: int | None = None,
                 tickers: list[str] | None = None, workers: int = 3, max_chunks: int = 6,
                 until: datetime | None = None, max_guidance_docs: int = 5):
        self.ctx, self.force, self.limit, self.only, self.workers = ctx, force, limit, tickers, workers
        self.max_chunks, self.until, self.max_guidance_docs = max_chunks, until, max_guidance_docs
        self.stopped = False  # set when --until is reached
        self.store = Store(ctx)
        self.cfg = scoring()

    # ---------- helpers ----------
    def time_up(self) -> bool:
        """Night runs stop cleanly at --until; every finished step is saved, so the next
        night resumes where this one stopped (keep the same --date)."""
        if self.stopped:
            return True
        if self.until and datetime.now() >= self.until:
            self.stopped = True
            log.info("Reached --until %s: stopping; re-run with --date %s to resume",
                     self.until.strftime("%H:%M"), self.ctx.run_date)
            return True
        return False

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

        def guidance_docs(t, rec):
            if not self._need(t, "guidance_docs"):
                return
            try:
                self.store.save(t, "guidance_docs", guidance_mod.fetch(self.ctx.market, rec, since,
                                                                       self.max_guidance_docs))
            except Exception as e:
                log.warning("%s guidance documents failed: %s", t, str(e)[:200])
                self.store.save(t, "guidance_docs", {"status": "error", "error": str(e)[:300], "docs": []})

        def get_filings(t):
            if filings_src == "sec":
                from .fetch import sec as sec_mod
                rec = sec_mod.fetch(t, since)
                for key, stage in (("_10k_items", "10k_items"), ("_10q_items", "10q_items")):
                    items = rec.pop(key, None)
                    if items:
                        self.store.save(t, stage, items)
                guidance_docs(t, rec)
                rec.pop("_filings", None)
                return rec
            if filings_src == "asx":
                rec = asx_mod.fetch(t, since)
                if not rec.get("error"):
                    guidance_docs(t, rec)
                return rec
            return {"ticker": t, "note": "no filings source for this market"}

        def get_jobs(t):
            rec = jobs_mod.fetch(t, (self.store.load(t, "info") or {}).get("website"))
            prev = self.previous_jobs(t)
            if prev:
                rec["previous_summary"] = prev
            return rec

        parts = {"fundamentals": fund_mod.fetch, "filings": get_filings, "jobs": get_jobs}
        for i, t in enumerate(self.selected(), 1):
            if self.time_up():
                return
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

    def _redflags(self, t: str, m: dict) -> dict:
        row = self.screen_row(t)
        return redflags_mod.evaluate(m, self.store.load(t, "filings"), self.cfg,
                                     is_financial=bool(row.get("flag_financial")),
                                     guidance=self.store.load(t, "guidance"),
                                     info=self.store.load(t, "info") or {})

    def analyse(self):
        bond = self.ctx.market_cfg.get("ten_year_yield")
        for t in self.selected():
            if not self._need(t, "analysis"):
                continue
            info, fund = self.store.load(t, "info") or {}, self.store.load(t, "fundamentals") or {}
            m = metrics_mod.compute(info, fund, self.cfg, bond_10y=bond)
            filings, jobs = self.store.load(t, "filings"), self.store.load(t, "jobs")
            if not filings or filings.get("error"):
                m["data_gaps"].append("filings (T1) unavailable: B4/B5 Low confidence")
            if not jobs or jobs.get("status") != "ok":
                m["data_gaps"].append("no job-board feed: B2 Low confidence")
            self.store.save(t, "analysis", {"metrics": m, "redflags": self._redflags(t, m)})

    def _chunk_plan(self, t: str) -> tuple[list[tuple[str, str]], int]:
        """What to read, newest first: the latest 10-Q (MD&A, legal, risk updates), then the
        annual report's risk factors, MD&A and legal proceedings. 20-F filers use their own
        Item numbers (ITRN Oct 2026 read Item 7 'major shareholders' as if it were MD&A)."""
        tenk = self.store.load(t, "10k_items") or {}
        tenq = self.store.load(t, "10q_items") or {}
        form = tenk.get("_form", "10-K")
        order = pipeline_read_order(form)
        plan: list[tuple[str, int]] = []   # (label, max chunks from this section)
        if tenq.get("Q_LEGAL") or tenq.get("Q_RISK"):
            plan.append(("10-Q legal+risk", 1))
        if tenq.get("Q_MDA"):
            plan.append(("10-Q MD&A", 1))
        for k in order:
            if len(tenk.get(k, "")) > 500:
                risk = (form == "10-K" and k == "1A") or (form == "20-F" and k == "3")
                plan.append((f"{form} Item {k}", 2 if risk else 1))
        texts = {"10-Q legal+risk": (tenq.get("Q_LEGAL", "") + "\n\n" + tenq.get("Q_RISK", "")).strip(),
                 "10-Q MD&A": tenq.get("Q_MDA", "")}
        texts.update({f"{form} Item {k}": tenk.get(k, "") for k in order})
        chunks: list[tuple[str, str]] = []
        # first pass: up to each section's share; second pass: fill the rest of the budget in order
        for label, share in plan:
            body = texts[label]
            chunks += [(label, body[i:i + CHUNK]) for i in range(0, min(len(body), share * CHUNK), CHUNK)]
        for label, share in plan:
            body = texts[label]
            chunks += [(label, body[i:i + CHUNK]) for i in range(share * CHUNK, len(body), CHUNK)]
        total = len(chunks)
        return chunks[: self.max_chunks], total

    def _extract(self, t: str) -> dict | None:
        if not self.force and self.store.has(t, "extracts"):
            return self.store.load(t, "extracts")
        chunks, total = self._chunk_plan(t)
        if not chunks:
            return None
        merged: dict = {}
        seen: set = set()
        for label, c in chunks:
            try:
                data, _ = llm.call_json("extract_filing", prompts.EXTRACT_SYSTEM, f"{label}:\n\n{c}")
            except Exception as e:
                log.warning("%s extract %s failed: %s", t, label, e)
                continue
            for key, v in data.items():
                vals = v if isinstance(v, list) else [v]
                for x in vals:
                    sx = str(x).strip()
                    if sx.lower() in JUNK or (key, sx.lower()) in seen:  # Gemma sometimes returns "[]"
                        continue
                    seen.add((key, sx.lower()))
                    merged.setdefault(key, []).append(f"[{label}] {sx}" if key != "management_tone" else sx)
        merged = {k: list(dict.fromkeys(v))[:12] for k, v in merged.items()}
        merged["_chunks_read"] = f"{len(chunks)} of {total}: " + ", ".join(dict.fromkeys(lbl for lbl, _ in chunks))
        self.store.save(t, "extracts", merged)
        return merged

    def _guidance(self, t: str) -> dict | None:
        if not self.force and self.store.has(t, "guidance"):
            return self.store.load(t, "guidance")
        gd = self.store.load(t, "guidance_docs")
        if not gd:
            return None
        per_doc, other, dropped = [], [], 0
        previous: list[str] = []  # read oldest first so each release is compared with earlier guidance
        for doc in sorted(gd.get("docs", []), key=lambda d: d["date"]):
            prev = ("PREVIOUS GUIDANCE (earlier releases, for comparison):\n" + "\n".join(previous[-15:]) + "\n\n"
                    if previous else "")
            try:
                data, _ = llm.call_json("extract_guidance", prompts.GUIDANCE_SYSTEM,
                                        f"{prev}DOCUMENT ({doc['date']}, {doc.get('title')}):\n\n{doc['text']}")
            except Exception as e:
                log.warning("%s guidance %s failed: %s", t, doc.get("date"), e)
                continue
            kept, n_drop = guidance_mod.verify(data.get("statements") or [], doc["text"])
            dropped += n_drop
            previous += [f"{doc['date']}: {st.get('metric')} ({st.get('period')}): {st.get('guidance_text')}"
                         for st in kept if st.get("guidance_text")]
            per_doc.append({"date": doc["date"], "title": doc.get("title"), "statements": kept})
            other += [f"{doc['date']}: {x}" for x in (data.get("other_events") or [])
                      if str(x).strip().lower() not in JUNK][:4]
        summary = guidance_mod.summarise(per_doc, gd.get("headline_events"))
        per_doc.sort(key=lambda d: d["date"], reverse=True)
        rec = {"status": "ok" if per_doc else gd.get("status", "no_docs"), "docs_read": len(per_doc),
               "statements_dropped_unquoted": dropped, **summary, "other_events": other[:10],
               "per_doc": per_doc}
        self.store.save(t, "guidance", rec)
        return rec

    def draft(self):
        """Two passes so each model loads once: (a) the fast model reads filings and results
        releases for every company, (b) the drafting model writes every thesis."""
        mp = score_mod.max_points(self.cfg)
        system = prompts.draft_system(self.ctx.market)
        todo = [t for t in self.selected() if self._need(t, "draft") and self.store.has(t, "analysis")]

        for i, t in enumerate(todo, 1):  # (a) reading
            if self.time_up():
                return
            t0 = time.time()
            try:
                self._extract(t)
                self._guidance(t)
                log.info("[read %d/%d] %s in %.0fs", i, len(todo), t, time.time() - t0)
            except Exception as e:
                log.warning("[read %d] %s failed: %s", i, t, e)

        def validate(d):
            for sct in score_mod.SECTIONS:
                float(d["sections"][sct]["points"])

        for i, t in enumerate(todo, 1):  # (b) drafting
            if self.time_up():
                return
            a = self.store.load(t, "analysis")
            a["redflags"] = self._redflags(t, a["metrics"])  # now with the guidance history
            self.store.save(t, "analysis", a)
            row = self.screen_row(t)
            t0 = time.time()
            try:
                user = prompts.facts_pack(row, a["metrics"], a["redflags"], self.store.load(t, "filings"),
                                          self.store.load(t, "jobs"), self.store.load(t, "extracts"), mp,
                                          self.store.load(t, "guidance"))
                facts = f"COMPANY: {t}\n\nFACTS\n=====\n{user}"
                d, meta = llm.call_json("draft_thesis", system, facts, validate)
                check_quotes(d, facts)
                if row.get("track") and d.get("track") != row["track"]:
                    d["track_model"], d["track"] = d.get("track"), row["track"]  # size decides the track
                d["_meta"] = meta
                self.store.save(t, "draft", d)
                log.info("[draft %d/%d] %s in %.0fs (%s)", i, len(todo), t, time.time() - t0, meta.get("attempt"))
            except Exception as e:
                log.warning("[draft %d] %s failed: %s", i, t, e)
                self.store.save(t, "draft_error", {"error": str(e)[:800]})

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
            s = score_mod.final(d, a["redflags"], a["metrics"], info, self.cfg, self.store.load(t, "filings"))
            rows.append({"ticker": t, "name": row.get("name"), "track": row.get("track") or d.get("track"),
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
                "draft_model": m["providers"][llm.provider_for("draft_thesis")]["model"], "max_points": mp,
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
                                               self.store.load(t, "extracts"), mp, self.store.load(t, "guidance"))
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
                r["_s"] = score_mod.final(d2, a["redflags"], a["metrics"], self.store.load(t, "info") or {}, self.cfg,
                                         self.store.load(t, "filings"))
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
                if self.time_up():
                    return
                log.info("== %s ==", s)
                getattr(self, s)()


def pipeline_read_order(form: str) -> tuple[str, ...]:
    from .fetch.sec import READ_ORDER
    return READ_ORDER.get(form, READ_ORDER["10-K"])


def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9%$.]+", " ", str(x or "").lower()).strip()


def check_quotes(draft: dict, facts: str) -> None:
    """A CHECK item counts as confirmed only if its quote is found in the facts sent to the
    model (ADBE Oct 2026: 'guidance misses confirmed' because the track was fallen_quality)."""
    hay = _norm(facts)
    for c in draft.get("caps_confirmed") or []:
        if not c.get("confirmed"):
            continue
        q = _norm(c.get("quote") or "")[:50]
        if len(q) < 12 or q not in hay:
            c["confirmed"] = False
            c["reason"] = "[discarded by code: no supporting quote found in the facts] " + str(c.get("reason") or "")

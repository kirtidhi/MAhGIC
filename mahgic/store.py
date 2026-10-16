"""Snapshot store: data/<date>/<market>/<universe>/<ticker>/<stage>.json

Every stage writes its output per ticker. A stage is skipped for a ticker when
its file already exists, so an interrupted run resumes where it stopped
(`--force` re-runs). Missing values are stored as null, never 0.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .config import RunContext


def _clean(obj: Any) -> Any:
    """Make values JSON-safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


class Store:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.root = ctx.dir

    def path(self, ticker: str, stage: str, ext: str = "json") -> Path:
        d = self.root / ticker
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{stage}.{ext}"

    def has(self, ticker: str, stage: str, ext: str = "json") -> bool:
        return self.path(ticker, stage, ext).exists()

    def save(self, ticker: str, stage: str, data: Any) -> Path:
        p = self.path(ticker, stage)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(_clean(data), indent=1, default=str))
        tmp.replace(p)  # atomic, so a crash never leaves half a file
        return p

    def load(self, ticker: str, stage: str) -> Any | None:
        p = self.path(ticker, stage)
        return json.loads(p.read_text()) if p.exists() else None

    def save_text(self, ticker: str, stage: str, text: str, ext: str = "md") -> Path:
        p = self.path(ticker, stage, ext)
        p.write_text(text)
        return p

    def load_text(self, ticker: str, stage: str, ext: str = "md") -> str | None:
        p = self.path(ticker, stage, ext)
        return p.read_text() if p.exists() else None

    # run-level files (universe list, screen table, summary)
    def run_file(self, name: str) -> Path:
        return self.root / name

    def tickers_with(self, stage: str) -> list[str]:
        return sorted(p.parent.name for p in self.root.glob(f"*/{stage}.json"))

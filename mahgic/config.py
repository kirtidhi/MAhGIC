"""Paths and config loading. Everything the pipeline reads lives under the repo root."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
KNOWLEDGE_DIR = ROOT / "knowledge"
DATA_DIR = Path(os.environ.get("MAHGIC_DATA_DIR", ROOT / "data"))


@lru_cache
def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name) as f:
        return yaml.safe_load(f) or {}


def markets() -> dict:
    return load_yaml("markets.yaml")


def models() -> dict:
    return load_yaml("models.yaml")


def scoring() -> dict:
    return load_yaml("scoring.yaml")


def ats_map() -> dict:
    path = CONFIG_DIR / "ats.yaml"
    return load_yaml("ats.yaml") if path.exists() else {}


def contact_email() -> str:
    """SEC requires a real contact in the User-Agent. Set CONTACT_EMAIL; there is no default."""
    email = os.environ.get("CONTACT_EMAIL", "").strip()
    if not email:
        raise RuntimeError(
            "Set CONTACT_EMAIL (SEC asks every client to identify itself). "
            "Example: export CONTACT_EMAIL=you@example.com"
        )
    return email


def knowledge(name: str) -> str:
    return (KNOWLEDGE_DIR / name).read_text()


@dataclass(frozen=True)
class RunContext:
    market: str
    universe: str
    run_date: str = date.today().isoformat()

    @property
    def market_cfg(self) -> dict:
        return markets()[self.market]

    @property
    def universe_cfg(self) -> dict:
        return self.market_cfg["universes"][self.universe]

    @property
    def dir(self) -> Path:
        d = DATA_DIR / self.run_date / self.market / self.universe
        d.mkdir(parents=True, exist_ok=True)
        return d

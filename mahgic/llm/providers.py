"""LLM routing. `call(task, system, user)` picks the provider from
config/models.yaml. Local (Ollama) by default; paid providers are counted
against `max_paid_calls_per_run` and refused past it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

import requests

from ..config import models

log = logging.getLogger("mahgic")
_paid_calls = [0]
_lock = threading.Lock()


LOCAL = {"ollama", "mlx"}


class BudgetExceeded(RuntimeError):
    pass


def _ollama(system: str, user: str, cfg: dict, json_mode: bool) -> str:
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "options": {"num_ctx": cfg.get("num_ctx", 32768), "temperature": cfg.get("temperature", 0.2)},
    }
    if json_mode:
        body["format"] = "json"
    r = requests.post(f"{cfg['base_url']}/api/chat", json=body, timeout=cfg.get("timeout_s", 900))
    r.raise_for_status()
    text = r.json()["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # qwen3 thinking traces


def _mlx(system: str, user: str, cfg: dict, json_mode: bool) -> str:
    """Any OpenAI-compatible local server (mlx_lm.server, LM Studio, llama.cpp server)."""
    body = {"model": cfg["model"], "temperature": cfg.get("temperature", 0.2),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = requests.post(f"{cfg['base_url']}/chat/completions", json=body, timeout=cfg.get("timeout_s", 900))
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _anthropic(system: str, user: str, cfg: dict, json_mode: bool) -> str:
    key = os.environ.get(cfg.get("api_key_env", "ANTHROPIC_API_KEY"))
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=600, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": cfg["model"], "max_tokens": cfg.get("max_tokens", 8000), "system": system,
              "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def _openai(system: str, user: str, cfg: dict, json_mode: bool) -> str:
    key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"))
    body = {"model": cfg["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post("https://api.openai.com/v1/chat/completions", json=body, timeout=600,
                      headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(system: str, user: str, cfg: dict, json_mode: bool) -> str:
    key = os.environ.get(cfg.get("api_key_env", "GEMINI_API_KEY"))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"parts": [{"text": user}]}]}
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    r = requests.post(url, params={"key": key}, json=body, timeout=600)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


IMPL = {"ollama": _ollama, "mlx": _mlx, "anthropic": _anthropic, "openai": _openai, "gemini": _gemini}


def provider_for(task: str) -> str:
    return models()["tasks"].get(task, "ollama")


def call(task: str, system: str, user: str, json_mode: bool = False, provider: str | None = None) -> tuple[str, dict]:
    m = models()
    name = provider or provider_for(task)
    cfg = m["providers"][name]
    if name not in LOCAL:
        with _lock:
            if _paid_calls[0] >= m.get("max_paid_calls_per_run", 0):
                raise BudgetExceeded(f"Paid-call ceiling reached ({_paid_calls[0]}); {task} not sent to {name}")
            _paid_calls[0] += 1
    t0 = time.time()
    text = IMPL[name](system, user, cfg, json_mode)
    return text, {"provider": name, "model": cfg["model"], "seconds": round(time.time() - t0, 1),
                  "chars_in": len(system) + len(user), "chars_out": len(text)}


def parse_json(text: str) -> dict:
    """Accept fenced or bare JSON; raise ValueError if none."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def call_json(task: str, system: str, user: str, validate=None) -> tuple[dict, dict]:
    """Local first; on invalid JSON retry once locally, then escalate if configured."""
    last_err = None
    for attempt in range(2):
        text, meta = call(task, system, user if attempt == 0 else
                          user + "\n\nYour last reply was not valid JSON for the schema. Reply with JSON only.",
                          json_mode=True)
        try:
            data = parse_json(text)
            if validate:
                validate(data)
            meta["attempts"] = attempt + 1
            return data, meta
        except (ValueError, KeyError, TypeError) as e:
            last_err = e
    if models()["escalate"].get("on_invalid_json") and provider_for(task) in LOCAL:
        rev = models()["tasks"].get("review_thesis", "anthropic")
        text, meta = call(task, system, user, json_mode=True, provider=rev)
        data = parse_json(text)
        if validate:
            validate(data)
        meta["escalated"] = True
        return data, meta
    raise ValueError(f"{task}: no valid JSON after retries ({last_err})")


def paid_calls_used() -> int:
    return _paid_calls[0]

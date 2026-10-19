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


LOCAL_IMPLS = {"ollama", "mlx"}
_current_model: dict = {}  # base_url -> model last used on that Ollama server


class BudgetExceeded(RuntimeError):
    pass


class ContextOverflow(ValueError):
    """The model ran out of context (prompt + thinking + answer > num_ctx)."""


def _switch_model(cfg: dict) -> None:
    """Unload the other model before loading this one, so two never share 16 GB."""
    url, model = cfg["base_url"], cfg["model"]
    prev = _current_model.get(url)
    if prev and prev != model:
        try:
            requests.post(f"{url}/api/generate", json={"model": prev, "keep_alive": 0}, timeout=60)
        except requests.RequestException as e:
            log.warning("could not unload %s: %s", prev, e)
        pause = models().get("model_switch_pause_s", 5)
        log.info("model switch %s -> %s (pause %ss)", prev, model, pause)
        time.sleep(pause)
    _current_model[url] = model


def _ollama(system: str, user: str, cfg: dict, json_mode: bool) -> str:
    _switch_model(cfg)
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "options": {"num_ctx": cfg.get("num_ctx", 16384), "temperature": cfg.get("temperature", 0.2)},
    }
    if json_mode:
        body["format"] = "json"
    if "think" in cfg:
        # With think set explicitly, Ollama returns the reasoning in message.thinking and
        # keeps message.content clean, so JSON parsing is unaffected.
        body["think"] = cfg["think"]
    for attempt in range(2):  # Ollama occasionally returns 500 while swapping models
        r = requests.post(f"{cfg['base_url']}/api/chat", json=body, timeout=cfg.get("timeout_s", 1800))
        if getattr(r, "status_code", 200) < 500 or attempt == 1:
            break
        log.warning("Ollama %s on %s; retrying in 20 s", r.status_code, cfg["model"])
        time.sleep(20)
    r.raise_for_status()
    data = r.json()
    msg = data.get("message", {})
    _last_stats.update({
        "thinking_chars": len(msg.get("thinking") or ""),
        "prompt_tokens": data.get("prompt_eval_count"),
        "output_tokens": data.get("eval_count"),
        "done_reason": data.get("done_reason"),
    })
    if data.get("done_reason") == "length":
        # Thinking used up the context before the answer finished. Retrying won't help;
        # raise num_ctx (memory permitting) or shorten the prompt.
        raise ContextOverflow(f"hit num_ctx={body['options']['num_ctx']} "
                              f"(prompt {data.get('prompt_eval_count')}, output {data.get('eval_count')} tokens)")
    text = msg.get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # models that inline their thinking


_last_stats: dict = {}


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


def impl_of(name: str) -> str:
    """Provider entries may share an implementation (`impl: ollama`); default is the name."""
    return models()["providers"].get(name, {}).get("impl", name)


def is_local(name: str) -> bool:
    return impl_of(name) in LOCAL_IMPLS


def call(task: str, system: str, user: str, json_mode: bool = False, provider: str | None = None,
         overrides: dict | None = None) -> tuple[str, dict]:
    m = models()
    name = provider or provider_for(task)
    cfg = {**m["providers"][name], **(overrides or {})}
    if not is_local(name):
        with _lock:
            if _paid_calls[0] >= m.get("max_paid_calls_per_run", 0):
                raise BudgetExceeded(f"Paid-call ceiling reached ({_paid_calls[0]}); {task} not sent to {name}")
            _paid_calls[0] += 1
    t0 = time.time()
    _last_stats.clear()
    text = IMPL[impl_of(name)](system, user, cfg, json_mode)
    return text, {"provider": name, "model": cfg["model"], "num_ctx": cfg.get("num_ctx"), "seconds": round(time.time() - t0, 1),
                  "chars_in": len(system) + len(user), "chars_out": len(text), **_last_stats}


def parse_json(text: str) -> dict:
    """Accept fenced or bare JSON; raise ValueError if none."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


CONCISE_HINT = ("\n\nIMPORTANT: your previous attempt ran out of space while reasoning. Keep your "
                "reasoning short: decide each section once, do not re-check or loop, then write the JSON.")


def call_json(task: str, system: str, user: str, validate=None) -> tuple[dict, dict]:
    """Local first. Invalid JSON: retry once. Context overflow: retry with a short-reasoning
    hint, then with a bigger num_ctx. Escalate to the paid reviewer only if configured and
    paid calls are allowed."""
    m = models()
    ov = m.get("overflow") or {}
    attempts = [("first", user, None)]
    last_err, overflows = None, []
    i = 0
    while i < len(attempts):
        label, u, over = attempts[i]
        i += 1
        try:
            text, meta = call(task, system, u, json_mode=True, overrides=over)
        except ContextOverflow as e:
            last_err = e
            overflows.append(f"{label}: {e}")
            log.warning("%s: context overflow on %s attempt: %s", task, label, e)
            if label == "first" and ov.get("concise_retry", True):
                attempts.append(("concise", user + CONCISE_HINT, None))
            elif label in ("first", "concise") and ov.get("retry_num_ctx"):
                attempts.append(("bigger_ctx", user + CONCISE_HINT, {"num_ctx": ov["retry_num_ctx"]}))
            continue
        try:
            data = parse_json(text)
            if validate:
                validate(data)
            meta.update(attempts=i, attempt=label, overflows=overflows)
            return data, meta
        except (ValueError, KeyError, TypeError) as e:
            last_err = e
            if label == "first":
                attempts.append(("json_retry", user + "\n\nYour last reply was not valid JSON for the schema. "
                                 "Reply with JSON only.", None))
    can_pay = m.get("max_paid_calls_per_run", 0) > 0
    if m["escalate"].get("on_invalid_json") and can_pay and is_local(provider_for(task)):
        rev = m["tasks"].get("review_thesis", "anthropic")
        text, meta = call(task, system, user, json_mode=True, provider=rev)
        data = parse_json(text)
        if validate:
            validate(data)
        meta["escalated"] = True
        return data, meta
    raise ValueError(f"{task}: no valid JSON after {i} attempts ({last_err})"
                     + (f"; overflows: {overflows}" if overflows else ""))


def paid_calls_used() -> int:
    return _paid_calls[0]

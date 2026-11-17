"""Shared plumbing: config, state files, LLM calls, spend tracking."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"

OFFLINE = os.environ.get("SHORTS_OFFLINE") == "1"


def config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def env(name: str, required: bool = True) -> str | None:
    val = os.environ.get(name)
    if required and not val and not OFFLINE:
        raise SystemExit(f"Missing required secret: {name}")
    return val


def load(name: str, default):
    p = DATA / name
    if not p.exists():
        return default
    with open(p) as f:
        return json.load(f)


def save(name: str, obj) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = DATA / (name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    tmp.replace(DATA / name)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def month_key() -> str:
    return now().strftime("%Y-%m")


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].strip("-") or "video"


# ---------------------------------------------------------------- spend


# Approximate list prices per million tokens; only used for the budget guard.
_PRICE = {"sonnet": (3.0, 15.0), "haiku": (1.0, 5.0), "opus": (5.0, 25.0)}


def _tier(model: str) -> tuple[float, float]:
    for k, v in _PRICE.items():
        if k in model:
            return v
    return _PRICE["sonnet"]


def add_spend(kind: str, amount: float) -> None:
    spend = load("spend.json", {})
    m = spend.setdefault(month_key(), {})
    m[kind] = round(m.get(kind, 0) + amount, 4)
    save("spend.json", spend)


def over_budget() -> str | None:
    cfg = config()["budget"]
    m = load("spend.json", {}).get(month_key(), {})
    if m.get("anthropic_usd", 0) >= cfg["anthropic_usd"]:
        return f"Anthropic spend hit ${cfg['anthropic_usd']} cap this month"
    if m.get("elevenlabs_chars", 0) >= cfg["elevenlabs_chars"]:
        return f"Voice usage hit {cfg['elevenlabs_chars']} character cap this month"
    return None


# ---------------------------------------------------------------- LLM


def ask(prompt: str, *, model_role: str = "writer", system: str = "",
        max_tokens: int = 4000, want_json: bool = True, offline_stub=None):
    """One shot Claude call. Returns parsed JSON when want_json."""
    if OFFLINE:
        if offline_stub is None:
            raise RuntimeError("offline mode needs a stub")
        return offline_stub
    import requests

    model = config()["models"][model_role]
    if want_json:
        prompt += "\n\nRespond with ONLY valid JSON. No prose, no code fences."
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    r = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=600, headers={
        "x-api-key": (env("ANTHROPIC_API_KEY") or "").strip(),
        "anthropic-version": "2023-06-01", "content-type": "application/json"})
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:300]}")
    j = r.json()

    from types import SimpleNamespace as NS
    msg = NS(usage=NS(**{k: j["usage"][k] for k in ("input_tokens", "output_tokens")}),
             content=[NS(type=b["type"], text=b.get("text", "")) for b in j["content"]])

    pin, pout = _tier(model)
    add_spend("anthropic_usd",
              (msg.usage.input_tokens * pin + msg.usage.output_tokens * pout) / 1e6)
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if not want_json:
        return text
    return parse_json(text)


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if not m:
            raise
        return json.loads(m.group(1))

"""Provider-agnostic model client. Core code asks for a role, never a model name."""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .providers import meta

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "models.json"
PROVIDERS = {"meta": meta}

load_dotenv(ROOT / ".env")


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def estimate_cost(cfg, model, usage):
    price = cfg.get("pricing_per_million_tokens_usd", {}).get(model)
    if not price:
        return None
    return (
        usage["input_tokens"] * price["input"] + usage["output_tokens"] * price["output"]
    ) / 1_000_000


def _log_call(cfg, entry):
    path = ROOT / cfg["call_log"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def chat(role, messages, **opts):
    """Call the model behind `role`.

    Returns {text, usage: {input_tokens, output_tokens}, model, provider,
    latency_ms, cost_usd, raw}. Retries 429/5xx/network errors with backoff.
    """
    cfg = load_config()
    role_cfg = cfg["roles"].get(role)
    if role_cfg is None:
        raise KeyError(f"unknown role {role!r}; known: {sorted(cfg['roles'])}")
    if role_cfg.get("api") == "responses":
        raise NotImplementedError(f"role {role!r} is not a chat model (api=responses)")

    provider_name = role_cfg["provider"]
    provider_cfg = cfg["providers"][provider_name]
    adapter = PROVIDERS[provider_name]
    model = role_cfg["model"]
    opts.setdefault("max_tokens", role_cfg.get("max_tokens"))

    retries = provider_cfg.get("max_retries", 3)
    start = time.perf_counter()
    for attempt in range(retries + 1):
        try:
            text, usage, raw = adapter.chat(provider_cfg, model, messages, **opts)
            break
        except meta.ProviderError as e:
            if not e.retryable or attempt == retries:
                raise
            time.sleep(2**attempt + random.random())
    latency_ms = round((time.perf_counter() - start) * 1000)

    cost = estimate_cost(cfg, model, usage)
    _log_call(cfg, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "provider": provider_name,
        "model": model,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "latency_ms": latency_ms,
        "cost_usd": cost,
    })
    return {
        "text": text,
        "usage": usage,
        "model": model,
        "provider": provider_name,
        "latency_ms": latency_ms,
        "cost_usd": cost,
        "raw": raw,
    }

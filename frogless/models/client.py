"""Provider-agnostic model client. Core code asks for a role, never a model name."""

import base64
import json
import mimetypes
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from .providers import meta

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "models.json"
PROVIDERS = {"meta": meta}


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


def _log_charged_failure(cfg, role, provider_name, model, start, error, cost):
    """The API answered (and likely billed us) but the reply couldn't be read."""
    _log_call(cfg, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "provider": provider_name,
        "model": model,
        "latency_ms": round((time.perf_counter() - start) * 1000),
        "cost_usd": cost,
        "error": str(error)[:300],
    })


def _with_retries(provider_cfg, fn):
    """Run fn() with backoff on retryable ProviderErrors."""
    retries = provider_cfg.get("max_retries", 3)
    for attempt in range(retries + 1):
        try:
            return fn()
        except meta.ProviderError as e:
            if not e.retryable or attempt == retries:
                raise
            time.sleep(2**attempt + random.random())


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

    start = time.perf_counter()
    try:
        text, usage, raw = _with_retries(
            provider_cfg, lambda: adapter.chat(provider_cfg, model, messages, **opts)
        )
    except meta.ProviderError as e:
        if e.charged:  # token counts unknown, so cost unknown
            _log_charged_failure(cfg, role, provider_name, model, start, e, None)
        raise
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


def _image_to_url(image):
    """http(s) URLs and data URLs pass through; local files become base64 data URLs."""
    image = str(image)
    if image.startswith(("http://", "https://", "data:")):
        return image
    path = Path(image)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def segment(role, image, prompt, **opts):
    """Segment `prompt` (a short noun phrase, e.g. "crochet piece") in `image`.

    `image` is a local file path or an http(s) URL. Returns
    {matches: [{id, box: [x0,y0,x1,y1] (image pixels), score: float|None,
                mask: {size: [h, w], origin: [x, y], raster: bytes}}],
     model, provider, latency_ms, cost_usd, raw}.

    Mask format (ours): `raster` is row-major bytes of 0/1, h rows by w cols,
    covering only the box area, placed with its top-left at `origin` in the image.
    Cost is flat per image (cfg["sam_pricing_usd"]["per_1000_images"]).
    """
    cfg = load_config()
    role_cfg = cfg["roles"].get(role)
    if role_cfg is None:
        raise KeyError(f"unknown role {role!r}; known: {sorted(cfg['roles'])}")
    if role_cfg.get("api") != "responses":
        raise ValueError(f"role {role!r} is not a segmentation model")

    provider_name = role_cfg["provider"]
    provider_cfg = cfg["providers"][provider_name]
    adapter = PROVIDERS[provider_name]
    model = role_cfg["model"]
    image_url = _image_to_url(image)
    cost = cfg["sam_pricing_usd"]["per_1000_images"] / 1000

    start = time.perf_counter()
    try:
        matches, usage, raw = _with_retries(
            provider_cfg,
            lambda: adapter.segment(provider_cfg, model, image_url, prompt, **opts),
        )
    except meta.ProviderError as e:
        if e.charged:
            _log_charged_failure(cfg, role, provider_name, model, start, e, cost)
        raise
    latency_ms = round((time.perf_counter() - start) * 1000)

    _log_call(cfg, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "provider": provider_name,
        "model": model,
        "images": 1,
        "matches": len(matches),
        "latency_ms": latency_ms,
        "cost_usd": cost,
    })
    return {
        "matches": matches,
        "model": model,
        "provider": provider_name,
        "latency_ms": latency_ms,
        "cost_usd": cost,
        "raw": raw,
    }

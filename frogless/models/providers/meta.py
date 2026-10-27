"""Meta Model API adapter. The only place that knows Meta's wire format.

Docs: https://dev.meta.ai/docs/protocols/chat-completions
Chat Completions is OpenAI-style: POST {base_url}/chat/completions with a Bearer key.
Muse Spark always reasons (reasoning_effort "none" is a 400); reasoning tokens
are counted inside completion_tokens, so keep max_completion_tokens generous.
"""

import os

import httpx


class ProviderError(Exception):
    def __init__(self, message, status=None, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _error_message(resp):
    # OpenAI-style envelope: {"error": {"message": ...}}
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            return err.get("message") or str(err)
        if err:
            return str(err)
    except ValueError:
        pass
    return resp.text[:300]


def chat(provider_cfg, model, messages, max_tokens=None, **opts):
    """Single attempt. Returns (text, usage, raw). Raises ProviderError."""
    key = os.environ.get(provider_cfg["api_key_env"])
    if not key:
        raise ProviderError(f"env var {provider_cfg['api_key_env']} is not set")

    body = {"model": model, "messages": messages}
    if max_tokens:
        body["max_completion_tokens"] = max_tokens
    body.update(opts)  # e.g. temperature, reasoning_effort

    try:
        resp = httpx.post(
            provider_cfg["base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=provider_cfg.get("timeout_s", 120),
        )
    except httpx.TransportError as e:
        raise ProviderError(f"network error: {type(e).__name__}: {e}", retryable=True)

    if resp.status_code >= 400:
        retryable = resp.status_code == 429 or resp.status_code >= 500
        raise ProviderError(
            f"Meta API {resp.status_code}: {_error_message(resp)}",
            status=resp.status_code,
            retryable=retryable,
        )

    raw = resp.json()
    text = raw["choices"][0]["message"].get("content") or ""
    u = raw.get("usage") or {}
    usage = {
        "input_tokens": u.get("prompt_tokens", 0),
        "output_tokens": u.get("completion_tokens", 0),
    }
    return text, usage, raw

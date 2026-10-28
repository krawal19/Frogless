"""Meta Model API adapter. The only place that knows Meta's wire format.

Docs: https://dev.meta.ai/docs/protocols/chat-completions
Chat Completions is OpenAI-style: POST {base_url}/chat/completions with a Bearer key.
Muse Spark always reasons (reasoning_effort "none" is a 400); reasoning tokens
are counted inside completion_tokens, so keep max_completion_tokens generous.

Segmentation (SAM 3.1) uses the Responses API instead:
  https://dev.meta.ai/docs/media-segmentation
  https://dev.meta.ai/docs/sam/segmenting
  https://dev.meta.ai/docs/sam/reading-segmentation
POST {base_url}/responses, streamed (SSE). The stream events and the special-token
output (boxes + encoded masks) are parsed by Meta's `meta-sam-parser` package
(https://pypi.org/project/meta-sam-parser/), used as a dependency.
"""

import asyncio
import json
import os

import httpx
from meta_sam_parser import (
    ResponsesStreamError,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    image_segmentation_format,
    parse_responses_stream,
)


class ProviderError(Exception):
    """`charged` means the API answered (so it was likely billed) but we couldn't read it."""

    def __init__(self, message, status=None, retryable=False, charged=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.charged = charged


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


def chat(provider_cfg, model, messages, max_tokens=None, json_schema=None, **opts):
    """Single attempt. Returns (text, usage, raw). Raises ProviderError.

    json_schema: a JSON Schema the reply must follow (structured output).
    opts go straight into the request, e.g. reasoning_effort ("minimal" ... "max";
    "none" is rejected by Muse Spark).
    """
    key = os.environ.get(provider_cfg["api_key_env"])
    if not key:
        raise ProviderError(f"env var {provider_cfg['api_key_env']} is not set")

    body = {"model": model, "messages": messages}
    if max_tokens:
        body["max_completion_tokens"] = max_tokens
    if json_schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": json_schema}}
    body.update(opts)

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

    try:
        raw = resp.json()
        text = raw["choices"][0]["message"].get("content") or ""
        u = raw.get("usage") or {}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        raise ProviderError(f"unreadable chat response: {type(e).__name__}: {e}", charged=True)
    usage = {
        "input_tokens": u.get("prompt_tokens", 0),
        "output_tokens": u.get("completion_tokens", 0),  # includes reasoning tokens
        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
        "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
    }
    return text, usage, raw


# ---------------------------------------------------------------- segmentation


async def _aiter(items):
    for item in items:
        yield item


async def _final_result(events):
    stream = parse_responses_stream(_aiter(events), image_segmentation_format())
    return await stream.final_result()


def _parse_events(events):
    """Let meta-sam-parser turn the collected stream events into plain match dicts."""
    try:
        result = asyncio.run(_final_result(events))
        boxes = {r.object_id: r for r in result.records if isinstance(r, SegmentationBoxRecord)}
        matches = []
        for r in result.records:
            if not isinstance(r, SegmentationMaskRecord):
                continue
            box = boxes.get(r.object_id)
            score = box.confidence if box and box.confidence is not None else r.confidence
            matches.append({
                "id": r.object_id,
                "frame": r.frame.frame_index if r.frame else 0,
                "box": [round(v) for v in (r.bounds.left, r.bounds.top, r.bounds.right, r.bounds.bottom)],
                "score": score,
                "mask": {
                    "size": [r.mask.height, r.mask.width],
                    "origin": [round(r.bounds.left), round(r.bounds.top)],
                    "raster": decode_mask_to_raster(r.mask),
                },
            })
    except ResponsesStreamError as e:  # includes InvalidSegmentationMaskError
        raise ProviderError(f"Meta stream error: {type(e).__name__}: {e}", charged=True)
    return matches, result.raw_output


def segment(provider_cfg, model, image_url, prompt, **opts):
    """Single attempt. image_url is an http(s) URL or a base64 data URL.

    Returns (matches, usage, raw) where raw = {"text", "last_event"}.
    """
    key = os.environ.get(provider_cfg["api_key_env"])
    if not key:
        raise ProviderError(f"env var {provider_cfg['api_key_env']} is not set")

    body = {
        "model": model,
        "input": [{
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_url},
            ],
        }],
        "stream": True,
        # metadata values must be strings
        "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
    }
    body.update(opts)

    events = []
    try:
        with httpx.stream(
            "POST",
            provider_cfg["base_url"].rstrip("/") + "/responses",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "text/event-stream",
            },
            json=body,
            timeout=provider_cfg.get("timeout_s", 120),
        ) as resp:
            if resp.status_code >= 400:
                resp.read()
                retryable = resp.status_code == 429 or resp.status_code >= 500
                raise ProviderError(
                    f"Meta API {resp.status_code}: {_error_message(resp)}",
                    status=resp.status_code,
                    retryable=retryable,
                )
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    events.append(json.loads(data))
                except ValueError:
                    continue
    except httpx.TransportError as e:
        raise ProviderError(f"network error: {type(e).__name__}: {e}", retryable=True)

    matches, text = _parse_events(events)
    last_event = events[-1] if events else None
    usage = ((last_event or {}).get("response") or {}).get("usage") or {}
    return matches, usage, {"text": text, "last_event": last_event}

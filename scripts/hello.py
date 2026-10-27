"""Smoke test: one tiny call to the `translator` role.

Run from the repo root: python -m scripts.hello
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `python scripts/hello.py` works too

from frogless.models.client import chat

result = chat("translator", [{"role": "user", "content": "Say hi in five words."}])
print("reply:  ", result["text"])
print("model:  ", result["model"])
print("usage:  ", result["usage"])
print("latency:", result["latency_ms"], "ms")
print("cost:   ", result["cost_usd"])

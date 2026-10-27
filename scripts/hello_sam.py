"""Smoke test: one SAM 3.1 call (~$0.0025) on a freely licensed crochet photo.

Run from the repo root: python -m scripts.hello_sam
Writes logs/sam_input.jpg (downloaded) and logs/sam_overlay.png (masks + boxes).
"""

import sys
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `python scripts/hello_sam.py` works too

from frogless.models.client import ROOT, segment

IMAGE_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/9/96/Granny_square.jpg/1280px-Granny_square.jpg"
IMAGE_PAGE = "https://commons.wikimedia.org/wiki/File:Granny_square.jpg"
IMAGE_LICENSE = "CC BY-SA 4.0 (Wikimedia Commons, File:Granny_square.jpg)"
PROMPT = "crochet"
COLORS = [(230, 57, 70), (42, 157, 143), (244, 162, 97), (69, 123, 157), (131, 56, 236)]


def write_overlay(path, img_path, result):
    """Masks (tinted) and boxes (white) drawn over the photo."""
    photo = Image.open(img_path).convert("RGB")
    for i, m in enumerate(result["matches"]):
        h, w = m["mask"]["size"]
        alpha = Image.frombytes("L", (w, h), bytes(v * 140 for v in m["mask"]["raster"]))
        photo.paste(COLORS[i % len(COLORS)], tuple(m["mask"]["origin"]), alpha)
        ImageDraw.Draw(photo).rectangle(m["box"], outline="white", width=3)
    photo.save(path)


def main():
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    img_path = logs / "sam_input.jpg"
    if not img_path.exists():
        r = httpx.get(IMAGE_URL, headers={"User-Agent": "FroglessHackathon/0.1"}, follow_redirects=True, timeout=60)
        r.raise_for_status()
        img_path.write_bytes(r.content)

    print("image:  ", IMAGE_URL)
    print("page:   ", IMAGE_PAGE)
    print("license:", IMAGE_LICENSE)
    print("prompt: ", repr(PROMPT))

    result = segment("segment", img_path, PROMPT)  # local file -> base64 data URL
    print("model:  ", result["model"])
    print("matches:", len(result["matches"]))
    for m in result["matches"]:
        print(f"  #{m['id']} box={m['box']} score={m['score']} mask={m['mask']['size']} at {m['mask']['origin']}")
    print("latency:", result["latency_ms"], "ms")
    print("cost:   ", result["cost_usd"])
    if result["matches"]:
        out = logs / "sam_overlay.png"
        write_overlay(out, img_path, result)
        print("overlay:", out)


if __name__ == "__main__":
    main()

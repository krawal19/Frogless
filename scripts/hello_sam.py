"""Smoke test: one SAM 3.1 call (~$0.0025) on a photo of a crochet piece you provide.

Run from the repo root: python -m scripts.hello_sam path/to/photo.jpg
Writes logs/sam_overlay.png (masks + boxes drawn over the photo).
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `python scripts/hello_sam.py` works too

from frogless.models.client import ROOT, segment

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
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        sys.exit("usage: python -m scripts.hello_sam path/to/photo.jpg")
    img_path = Path(sys.argv[1])
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)

    print("image:  ", img_path)
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

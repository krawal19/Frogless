"""Render the visual sample patterns and build a review gallery.

Run from the repo root: python -m scripts.render_samples [name ...]
Needs the optional visual-rendering setup (README > Setup). Output: logs/renders/index.html
"""

import html
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frogless.engine import get_engine

OUT = Path(__file__).resolve().parents[1] / "logs" / "renders"


def check_summary(engine, code):
    r = engine.check(code)
    counts = " ".join(str(row.stitch_count) for row in r.rows)
    if r.ok:
        return True, f"ok, counts: {counts}"
    return False, f"NOT ok: {r.error.message if r.error else 'unknown'}; counts: {counts}"


SEEDS = (1, 7, 42)  # layout seeds for the stability test on flat samples
SEED_LINES = "\nDOT: start={seed}\nDOT: iterations=4000"


def figures(res, title):
    """Figure list for one render: (label, path)."""
    out = [(f"{title}, {view}", path) for view, path in res.get("views", {}).items()]
    if res.get("chart_2d"):
        out.append(("crochet chart", res["chart_2d"]))
    return out


def block(title, res):
    parts = [f"<h3>{html.escape(title)}</h3>"]
    if res["error"]:
        parts.append(f'<p class="bad"><b>Render failed:</b> {html.escape(res["error"])}</p>')
    if res.get("chart_error"):
        parts.append(f'<p class="bad">No chart: {html.escape(res["chart_error"])}</p>')
    if res.get("thickness_ratio") is not None:
        parts.append(
            f'<p class="small">size along longest/middle/thinnest axis: {res["extent"]}; '
            f'thickness / length = <b>{res["thickness_ratio"]}</b> (small means flat); {res.get("seconds", 0):.1f}s</p>'
        )
    imgs = figures(res, title)
    if imgs:
        parts.append('<div class="imgs">')
        for label, path in imgs:
            rel = os.path.relpath(path, OUT).replace("\\", "/")
            parts.append(f'<figure><img src="{rel}" alt="{html.escape(label)}"><figcaption>{html.escape(label)}</figcaption></figure>')
        parts.append("</div>")
    return "\n".join(parts)


def card(sample, ok, summary, blocks):
    return "\n".join(
        [
            f"<section><h2>{html.escape(sample['name'])}</h2>",
            f"<p><b>Expected:</b> {html.escape(sample['expected_shape'])}</p>",
            f'<p class="{"ok" if ok else "bad"}"><b>Check:</b> {html.escape(summary)}</p>',
            f"<pre>{html.escape(sample['code'])}</pre>",
            *[block(t, r) for t, r in blocks],
            "</section>",
        ]
    )


def main(only):
    engine = get_engine()
    samples = [s for s in engine.visual_samples() if not only or s["name"] in only]
    OUT.mkdir(parents=True, exist_ok=True)

    items = []  # (name, code, dim, chart); remember which sample and title each belongs to
    meta = []
    for s in samples:
        items.append((s["name"], s["code"], "3D", True))
        meta.append((s["name"], "3D mode"))
        items.append((s["name"], s["code"], "2D", False))
        meta.append((s["name"], "2D mode"))
        if s.get("seed_test"):
            for seed in SEEDS:
                items.append((f"{s['name']}_seed{seed}", s["code"] + SEED_LINES.format(seed=seed), "3D", False))
                meta.append((s["name"], f"3D mode, DOT start={seed}, iterations=4000"))
    t0 = time.time()
    results = engine.render_many(items, OUT)  # one browser for all
    print(f"{len(items)} renders in {time.time() - t0:.0f}s")

    by_sample = {}
    for (name, title), res in zip(meta, results):
        by_sample.setdefault(name, []).append((title, res))
        ratio = res.get("thickness_ratio")
        print(f"{name:26s} {title:42s} {res.get('seconds', 0):5.1f}s thickness/length={ratio}  {res['error'] or 'rendered'}")
    cards = []
    for s in samples:
        ok, summary = check_summary(engine, s["code"])
        cards.append(card(s, ok, summary, by_sample[s["name"]]))
    page = f"""<!doctype html><meta charset="utf-8"><title>Frogless renders</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#fafafa;color:#222}}
section{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px 18px;margin-bottom:28px}}
pre{{background:#f0f0f0;padding:8px;overflow:auto}}
.imgs{{display:flex;flex-wrap:wrap;gap:12px}}
figure{{margin:0}} img{{max-width:420px;border:1px solid #ccc;background:#fff}}
figcaption{{font-size:13px;color:#555}} .ok{{color:#176b2c}} .bad{{color:#b3261e}} .small{{font-size:12px;color:#666}}
</style><h1>Frogless renders</h1><p>Images come from the engine's own 3D view and crochet chart. Judge them by eye.</p>
{chr(10).join(cards)}"""
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print("gallery:", OUT / "index.html")


if __name__ == "__main__":
    main(set(sys.argv[1:]))

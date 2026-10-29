"""The page (Gradio): a pattern box on top, a verdict banner, "As written" next to "Corrected", and a Details accordion.

Text results appear as soon as the check is done; the chart images are filled in when drawing finishes
(the handler is a generator that yields twice). The page calls the same functions as the HTTP API.
"""

import html
from pathlib import Path

import gradio as gr

from . import api

ROOT = api.ROOT
EXAMPLE_DIRS = (("dev", ROOT / "external_patterns" / "dev"), ("smoke", ROOT / "logs" / "smoke"))  # read at run time
GROUP_TITLE = {"works": "Works", "breaks": "Breaks", "ambiguous": "Depends on how you read it", "unreadable": "Could not read it"}

THEME = gr.themes.Base(primary_hue="emerald", neutral_hue="slate", font=["system-ui", "Segoe UI", "sans-serif"]).set(
    body_background_fill="#f7f8f5", block_background_fill="#ffffff", block_border_width="1px",
    block_radius="10px", button_primary_background_fill="#2f7d4f", button_primary_background_fill_hover="#256640",
    button_primary_text_color="#ffffff")

CSS = """
.gradio-container { max-width: 1320px !important; }
.banner { border-radius: 10px; padding: 14px 18px; border: 1px solid; font-size: 16px; line-height: 1.5; }
.banner .msg { font-size: 17px; font-weight: 600; }
.banner ul { margin: 8px 0 0 18px; padding: 0; font-size: 14px; font-weight: 400; }
.banner .extra { margin-top: 8px; font-size: 14px; font-weight: 400; }
.banner.works { background: #e8f5ec; border-color: #9fd2b0; color: #174d2d; }
.banner.breaks { background: #fdeceb; border-color: #eba6a1; color: #6e1b16; }
.banner.ambiguous { background: #fff4de; border-color: #e8c675; color: #6a4a07; }
.banner.unreadable { background: #eceff3; border-color: #b9c1cc; color: #35404d; }
.banner.waiting { background: #f1f4f1; border-color: #d3d9d3; color: #4a554a; }
.pane h3 { margin: 0 0 6px 0; font-size: 16px; }
.pat { border: 1px solid #dfe3df; border-radius: 8px; background: #fff; padding: 6px 0; max-height: 230px; overflow: auto; font-size: 14px; }
.pl { padding: 3px 12px; white-space: pre-wrap; border-left: 4px solid transparent; line-height: 1.45; }
.pl.breaks { background: #fdeceb; border-left-color: #d9534f; }
.pl.fix { background: #e8f5ec; border-left-color: #2f7d4f; }
.pl .tag { font-size: 12px; font-weight: 600; margin-left: 8px; padding: 1px 6px; border-radius: 4px; background: #fff; border: 1px solid currentColor; }
.pl.breaks .tag { color: #b0332e; }
.pl.fix .tag { color: #2f7d4f; }
.empty { padding: 14px 16px; color: #4a554a; font-style: italic; }
.chartbox { border: 1px solid #dfe3df; border-radius: 8px; background: #fff; min-height: 120px; max-height: 520px; overflow: auto;
            display: flex; align-items: flex-start; justify-content: center; padding: 8px; }
.chartbox img { max-width: 100%; height: auto; }
.chartbox .hint { color: #6b756b; padding: 36px 10px; text-align: center; }
.chartnote { font-size: 13px; color: #6b756b; margin-top: 4px; }
table.rows { border-collapse: collapse; width: 100%; font-size: 13px; }
table.rows th, table.rows td { border-bottom: 1px solid #e3e7e3; padding: 5px 8px; text-align: left; vertical-align: top; }
table.rows th { background: #f1f4f1; position: sticky; top: 0; }
table.rows tr.breaks td { background: #fdeceb; }
table.rows tr.bad td { background: #fff4de; }
.scroll { max-height: 360px; overflow: auto; border: 1px solid #dfe3df; border-radius: 8px; }
table.times { border-collapse: collapse; font-size: 13px; }
table.times, table.times td { border: none !important; }
table.times td { padding: 3px 14px 3px 0; }
table.times tr.total td { font-weight: 600; border-top: 1px solid #c9cfc9; }
"""


# ---- example files, read when the page is built or loaded ----
def example_choices() -> list[tuple[str, str]]:
    found = []
    for name, folder in EXAMPLE_DIRS:
        if folder.is_dir():
            found += [(f"{name}: {p.stem}", str(p)) for p in sorted(folder.glob("*.txt"))]
    return found


def load_example(path: str | None) -> str:
    if not path:
        return gr.skip()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return gr.skip()


# ---- pieces of HTML ----
def _esc(text) -> str:
    return html.escape("" if text is None else str(text))


def banner_html(result: dict | None = None, waiting: str = "") -> str:
    if result is None:
        return f'<div class="banner waiting">{_esc(waiting)}</div>' if waiting else ""
    group = result["verdict"]["group"]
    parts = [f'<div class="msg">{_esc(result["user_message"])}</div>']
    if result["fix_lines"]:
        parts.append("<ul>" + "".join(f"<li>{_esc(line.strip())}</li>" for line in result["fix_lines"]) + "</ul>")
    extra = list(result["notes"])
    if extra:
        parts.append('<div class="extra">' + "<br>".join(_esc(n) for n in extra) + "</div>")
    return f'<div class="banner {group}">{"".join(parts)}</div>'


def lines_html(lines: list[dict]) -> str:
    rows = []
    for ln in lines:
        mark = ln["mark"]
        tag = f'<span class="tag">{_esc(ln["note"])}</span>' if ln.get("note") else ""
        rows.append(f'<div class="pl {mark}">{_esc(ln["text"]) or "&nbsp;"}{tag}</div>')
    return f'<div class="pat">{"".join(rows)}</div>'


def left_html(result: dict | None) -> str:
    return lines_html(result["written_lines"]) if result else ""


def right_html(result: dict | None) -> str:
    if not result:
        return ""
    status = result["corrected_status"]
    if status == "none_needed":
        return '<div class="pat"><div class="empty">No corrections needed.</div></div>'
    if status == "no_fix":
        return '<div class="pat"><div class="empty">No re-checked fix found.</div></div>'
    if result["corrected_lines"]:
        note = ('<div class="chartnote">The fix could not be placed into your own wording, so this is the pattern '
                "rebuilt from the checked rows.</div>") if result.get("corrected_source") == "rebuilt" else ""
        return lines_html(result["corrected_lines"]) + note
    return ('<div class="pat"><div class="empty">A fix was found but could not be written into the pattern text; '
            "see the suggested fixes above.</div></div>")


def chart_html(images: dict | None, view: str, waiting: str = "") -> str:
    if waiting:
        return f'<div class="chartbox"><div class="hint">{_esc(waiting)}</div></div>'
    if not images:
        return ""
    key = {"Chart": "symbols", "Sketch": "sketch", "3D": "view_3d"}.get(view, "symbols")
    url = images.get(key)
    note = f'<div class="chartnote">{_esc(images["note"])}</div>' if images.get("note") else ""
    if not url:
        why = images.get("error") or "nothing to draw"
        return f'<div class="chartbox"><div class="hint">No image: {_esc(why)}</div></div>{note}'
    return f'<div class="chartbox"><a href="{_esc(url)}" target="_blank"><img src="{_esc(url)}" alt="{_esc(view)}"></a></div>{note}'


def view_choices(images: dict | None) -> list[str]:
    return ["Chart", "Sketch"] + (["3D"] if images and images.get("view_3d") else [])


def details_html(result: dict | None, render_seconds: float | None, total_cost: float | None) -> str:
    if not result:
        return ""
    rows = []
    for r in result["rows"]:
        css = "breaks" if r["status"] == "breaks" else ("bad" if r["status"] in ("not checked", "check the reading") else "")
        rows.append(
            f'<tr class="{css}"><td>{_esc(r["number"] if r["number"] is not None else "")}</td><td>{_esc(r["text"])}</td>'
            f'<td>{_esc(r["translated_by"])}</td><td>{_esc(r["read_back"])}</td><td>{_esc("" if r["stated"] is None else r["stated"])}</td>'
            f'<td>{_esc("" if r["computed"] is None else r["computed"])}</td>'
            f'<td>{_esc(r["status"])}{(": " + _esc(r["note"])) if r["note"] else ""}</td></tr>')
    table = ('<div class="scroll"><table class="rows"><tr><th>Row</th><th>Written</th><th>Translated by</th><th>Read back</th>'
             f'<th>Stated</th><th>Computed</th><th>Status</th></tr>{"".join(rows)}</table></div>')
    shape = ("<ul>" + "".join(f"<li>{_esc(s)}</li>" for s in result["shape_lines"]) + "</ul>") if result["shape_lines"] else "<p>None.</p>"
    t = result["timings"]
    times = "".join(f'<tr class="{"total" if k == "total" else ""}"><td>{k.replace("_", " ")}</td><td>{v:.2f} s</td></tr>' for k, v in t.items())
    if render_seconds is not None:
        times += f'<tr><td>render charts</td><td>{render_seconds:.2f} s</td></tr>'
    cost = f"${result['cost_usd']:.4f}"
    if total_cost is not None and total_cost != result["cost_usd"]:
        cost += f" for this size, ${total_cost:.4f} for all sizes"
    terms = f"<p>Terms: {_esc(result['terms'])}</p>" if result.get("terms") else ""
    return (f"<h4>Rows</h4>{table}<h4>Shape hints</h4>{shape}<h4>Timings</h4><table class=\"times\">{times}</table>"
            f"<h4>Cost of this check</h4><p>{cost}</p>{terms}")


# ---- the page ----
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Frogless") as demo:
        gr.Markdown("# Frogless\nPaste a crochet pattern. Frogless checks whether it works, says where it breaks, and suggests re-checked fixes.")
        with gr.Row(equal_height=False):
            with gr.Column(scale=3):
                text = gr.Textbox(label="Pattern", lines=6, max_lines=12, placeholder="Paste the written pattern here.")
            with gr.Column(scale=1, min_width=220):
                terms = gr.Radio(["auto", "US", "UK"], value="auto", label="Terms")
                examples = gr.Dropdown(example_choices(), value=None, label="Examples", info="Loaded from files on this computer.")
                size = gr.Dropdown([], value=None, label="Size", visible=False)
                go = gr.Button("Check", variant="primary", size="lg")
        banner = gr.HTML()
        with gr.Row(equal_height=False):
            with gr.Column(elem_classes="pane"):
                gr.Markdown("### As written")
                left_text = gr.HTML()
                left_view = gr.Radio(["Chart", "Sketch"], value="Chart", show_label=False, container=False)
                left_img = gr.HTML()
            with gr.Column(elem_classes="pane"):
                gr.Markdown("### Corrected")
                right_text = gr.HTML()
                right_view = gr.Radio(["Chart", "Sketch"], value="Chart", show_label=False, container=False)
                right_img = gr.HTML()
        with gr.Accordion("Details", open=False):
            details = gr.HTML()
        state = gr.State({})  # {"id", "results", "images": {"written", "corrected"}, "render_seconds", "index"}

        def show(st: dict, index: int, drawing: bool):
            """All page outputs for one size, with charts drawn or 'Drawing...' placeholders."""
            result = st["results"][index]
            images = st.get("images") or {}
            fixed = result["corrected_status"] == "fixed"
            wait = "Drawing the charts..." if drawing else ""
            return (banner_html(result), left_html(result), right_html(result),
                    chart_html(images.get("written"), "Chart", wait if drawing else ""),
                    chart_html(images.get("corrected"), "Chart", wait if fixed else ""),
                    gr.update(choices=view_choices(images.get("written")), value="Chart"),
                    gr.update(choices=view_choices(images.get("corrected")), value="Chart", visible=fixed),
                    details_html(result, st.get("render_seconds"), st.get("cost_usd")), st)

        outputs = [banner, left_text, right_text, left_img, right_img, left_view, right_view, details, state]

        def present(st: dict, index: int):
            """Yield the text results at once, then the same page with the charts."""
            st = {**st, "images": None, "render_seconds": None, "index": index}
            yield show(st, index, True)
            try:
                drawn = api.run_render(st["id"], index)
                st = {**st, "images": {"written": drawn["written"], "corrected": drawn["corrected"]},
                      "render_seconds": drawn["render_seconds"]}
            except Exception as e:  # keep the text results; say why there are no pictures
                failed = {"symbols": None, "sketch": None, "view_3d": None, "error": f"{type(e).__name__}: {e}", "note": ""}
                st = {**st, "images": {"written": failed, "corrected": failed}}
            yield show(st, index, False)

        def check(pattern: str, terms_choice: str):
            if not pattern.strip():
                yield (banner_html(waiting="Paste a pattern first."), "", "", "", "", gr.update(), gr.update(), "", {}, gr.update())
                return
            yield (banner_html(waiting="Checking the pattern... this can take up to a minute."), "", "", "", "",
                   gr.update(), gr.update(), "", {}, gr.update(visible=False))
            try:
                done = api.run_check(pattern, terms_choice)
            except Exception as e:
                yield (banner_html(waiting=f"Could not check the pattern: {type(e).__name__}: {e}"), "", "", "", "",
                       gr.update(), gr.update(), "", {}, gr.update(visible=False))
                return
            st = {"id": done["id"], "results": done["results"], "cost_usd": done["cost_usd"]}
            labels = [r["label"] for r in done["results"]]
            size_update = gr.update(choices=labels, value=labels[0], visible=len(labels) > 1)
            for out in present(st, 0):
                yield (*out, size_update)

        def change_size(label: str, st: dict):
            labels = [r["label"] for r in st.get("results", [])]
            if label not in labels:
                yield (gr.skip(),) * len(outputs)
                return
            yield from present(st, labels.index(label))

        def switch(view: str, st: dict, which: str):
            return chart_html((st.get("images") or {}).get(which), view)

        go.click(check, [text, terms], outputs + [size])
        examples.change(load_example, examples, text)
        size.input(change_size, [size, state], outputs)
        left_view.input(lambda v, st: switch(v, st, "written"), [left_view, state], left_img)
        right_view.input(lambda v, st: switch(v, st, "corrected"), [right_view, state], right_img)
        demo.load(lambda: gr.update(choices=example_choices()), None, examples)
    return demo

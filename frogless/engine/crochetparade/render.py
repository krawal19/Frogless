"""Render a pattern to pictures by driving the engine's own web page in headless Chromium.

Needs the optional visual-rendering step from README > Setup (Playwright + Chromium).
The page is served from a throwaway local http server rooted at the engine clone, because
it loads wasm and cannot run from file://.
"""

import functools
import http.server
import math
import threading
import time
from pathlib import Path

# Software GL so WebGL works in headless Chromium without a GPU.
CHROMIUM_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
VIEWPORT = {"width": 1500, "height": 1000}
TIMEOUT_S = 90  # per pattern: layout + 3D calculation can be slow for big patterns
CHART_PX = 900  # chart SVG resolution (its "height" field)
# The three files the page's "Save Standard Crochet Chart as SVG" downloads, by the name it gives them.
_SYMBOL_STYLE = "svg path{stroke:#222 !important;stroke-width:2.2px !important}"
_CHART_FILES = {"crochet_symbols.svg": "symbols", "graph.svg": "connectivity",
                "graph_with_std_crochet_symbols.svg": "overlay"}

# Camera views, in the model's principal axes: n = the thinnest direction (the normal,
# if the piece is flat), e1 = the longest direction.
VIEWS = ("oblique", "top", "side")

# Hook the page's renderer so we can reach the (otherwise private) camera, then expose helpers.
_HOOK_JS = """() => {
  window.__cam = null;
  const orig = renderer.render.bind(renderer);
  renderer.render = (s, c) => { window.__cam = c; return orig(s, c); };
  window.__points = () => {
    const out = [];
    scene.updateMatrixWorld(true);
    scene.traverse(o => {
      if (o.isMesh && o.geometry && o.geometry.type === 'SphereGeometry') {
        const e = o.matrixWorld.elements; out.push([e[12], e[13], e[14]]);
      }
    });
    return out;
  };
}"""

_SET_CAMERA_JS = """([pos, up, shift]) => {
  const c = window.__cam;
  c.up.set(up[0], up[1], up[2]);
  c.position.set(pos[0], pos[1], pos[2]);
  c.lookAt(0, 0, 0);
  scene.position.set(shift[0], shift[1], shift[2]);
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
}"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _principal_axes(points):
    """Eigenvectors of the covariance matrix, longest first (Jacobi method; 3x3 only)."""
    n = len(points)
    mean = [sum(p[i] for p in points) / n for i in range(3)]
    a = [[sum((p[i] - mean[i]) * (p[j] - mean[j]) for p in points) / n for j in range(3)] for i in range(3)]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(50):
        p, q = max(((0, 1), (0, 2), (1, 2)), key=lambda ij: abs(a[ij[0]][ij[1]]))
        if abs(a[p][q]) < 1e-12:
            break
        theta = 0.5 * math.atan2(2 * a[p][q], a[q][q] - a[p][p])
        c, s = math.cos(theta), math.sin(theta)
        for k in range(3):
            a[k][p], a[k][q] = c * a[k][p] - s * a[k][q], s * a[k][p] + c * a[k][q]
        for k in range(3):
            a[p][k], a[q][k] = c * a[p][k] - s * a[q][k], s * a[p][k] + c * a[q][k]
        for k in range(3):
            v[k][p], v[k][q] = c * v[k][p] - s * v[k][q], s * v[k][p] + c * v[k][q]
    order = sorted(range(3), key=lambda i: -a[i][i])
    return [[v[k][i] for k in range(3)] for i in order]  # longest, middle, thinnest


def _camera_for(view, axes, radius):
    """Camera position (looking at the origin) and up vector for a named view."""
    e1, e2, n = axes
    fit = radius * 1.7  # distance that fills the frame with a little margin (75 degree fov)
    if view == "top":  # looking straight down the thin axis
        return [x * fit for x in n], e1
    if view == "side":  # edge-on, so flatness (or cupping) shows as a profile
        return [x * fit for x in e1], n
    d = _norm([n[i] * 1.0 + e1[i] * 0.9 + e2[i] * 0.5 for i in range(3)])
    return [x * fit for x in d], n


class Renderer:
    """One headless browser and one local web server, reused across many renders."""

    def __init__(self, repo):
        self.repo = Path(repo)
        if not (self.repo / "index.html").is_file():
            raise RuntimeError(f"no index.html in {self.repo}")
        self._pw = self._browser = self._server = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "rendering needs Playwright: see README > Setup > Visual rendering (optional)"
            ) from e
        handler = functools.partial(_QuietHandler, directory=str(self.repo))
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(args=CHROMIUM_ARGS)
        except Exception as e:
            self.__exit__()
            raise RuntimeError(f"could not start Chromium (run: python -m playwright install chromium): {e}") from e
        return self

    def __exit__(self, *exc):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._pw = self._browser = self._server = None

    # ---- one pattern ----
    def render(self, code: str, out_dir, name: str = "render", dim: str = "3D", chart: bool = True) -> dict:
        """dim is the page's layout mode, "3D" or "2D" (its 2D/3D radio buttons)."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        result = {"model_3d": None, "chart_2d": None, "error": None, "views": {}}
        started = time.time()
        page = self._browser.new_page(viewport=VIEWPORT, accept_downloads=True)
        problems = []
        page.on("dialog", lambda d: (problems.append(d.message), d.dismiss()))
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
        try:
            self._render_page(page, code, out_dir, name, dim, chart, result)
        except Exception as e:
            detail = f" ({problems[0][:200]})" if problems else ""
            result["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}{detail}"
        finally:
            page.close()
        result["seconds"] = round(time.time() - started, 1)
        return result

    def _render_page(self, page, code, out_dir, name, dim, chart, result):
        page.set_default_timeout(TIMEOUT_S * 1000)
        page.goto(f"http://127.0.0.1:{self._server.server_address[1]}/index.html")
        page.fill("#inputText", code)
        page.check(f'input[name="rendering"][value="{dim}"]')
        result["dim"] = dim
        page.locator('[id="3dbutton"]').first.click()  # the id appears twice in the page
        deadline = time.time() + TIMEOUT_S
        while True:  # done when the 3D renderer exists; failed when the spinner stops without one
            state = page.evaluate(
                "({r: typeof renderer !== 'undefined' && renderer !== null,"
                " spin: document.getElementById('loading-icon').style.display})"
            )
            if state["r"]:
                break
            if state["spin"] == "none":
                raise RuntimeError("the engine page produced no 3D model for this pattern")
            if time.time() > deadline:
                raise TimeoutError("3D calculation timed out")
            time.sleep(0.3)
        page.evaluate(_HOOK_JS)
        page.wait_for_function("window.__cam !== null")

        points = self._settled_points(page)
        if not points:
            raise RuntimeError("the 3D scene has no stitches")
        mean = [sum(p[i] for p in points) / len(points) for i in range(3)]
        centred = [[p[i] - mean[i] for i in range(3)] for p in points]
        radius = max(math.sqrt(sum(x * x for x in p)) for p in centred) + 0.15
        axes = _principal_axes(points)
        # How thick the piece is compared with its longest side (small = flat).
        spans = [max(sum(p[i] * ax[i] for i in range(3)) for p in centred)
                 - min(sum(p[i] * ax[i] for i in range(3)) for p in centred) for ax in axes]
        result["extent"] = [round(x, 3) for x in spans]
        result["thickness_ratio"] = round(spans[2] / spans[0], 3) if spans[0] else None
        tag = "2dmode" if dim == "2D" else "3d"
        shift = [-x for x in mean]  # the page's camera always looks at the origin, so move the model there
        canvas = page.locator("#view3d canvas").first
        canvas.click()  # the page only takes key presses after a click on the canvas
        for _ in range(3):  # thicken the spheres and edges so they show up in a still image
            page.keyboard.press("Control+=")
        page.wait_for_timeout(1000)
        for view in VIEWS:
            pos, up = _camera_for(view, axes, radius)
            page.evaluate(_SET_CAMERA_JS, [pos, up, shift])
            path = out_dir / (f"{name}_{tag}.png" if view == "oblique" else f"{name}_{tag}_{view}.png")
            canvas.screenshot(path=str(path))
            result["views"][view] = str(path)
        result["model_3d"] = result["views"]["oblique"]

        if not chart:
            return
        # The chart is a projection of the current view, so take it face-on.
        pos, up = _camera_for("top", axes, radius)
        page.evaluate(_SET_CAMERA_JS, [pos, up, [0, 0, 0]])
        try:
            charts = self._chart(page, out_dir, name)
            result.update(charts_2d=charts, chart_2d=charts["symbols"])
        except Exception as e:
            result["chart_error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:150]}"

    @staticmethod
    def _settled_points(page):
        """Wait until the stitch positions stop moving (the page relaxes the model)."""
        prev = None
        deadline = time.time() + 20
        while True:
            points = page.evaluate("window.__points()")
            if points and points == prev:
                return points
            prev = points
            if time.time() > deadline:
                return points
            time.sleep(0.5)

    def _chart(self, page, out_dir: Path, name: str) -> dict:
        """Use the page's own 'Save Standard Crochet Chart as SVG', which downloads three SVG files.

        The page names them graph.svg (the connectivity sketch: stitch ids joined by arrows),
        graph_with_std_crochet_symbols.svg (the symbols drawn over that sketch) and crochet_symbols.svg
        (the standard crochet symbol chart). Each is saved as <name>_<kind>.svg and rasterised to .png.
        Returns {"symbols": png path, "connectivity": ..., "overlay": ..., "symbols_svg": svg path, ...}.
        The PNG of the symbol chart is drawn with heavier dark lines than the page's hairlines so that it
        reads in a still image; the saved SVG is the page's own.
        """
        downloads = []
        page.on("download", lambda d: downloads.append(d))
        page.evaluate("saveSvg()")  # opens a small options form
        page.fill("#svgHeight", str(CHART_PX))
        page.check("#colorCheckbox")
        page.click("form button[type=submit]")
        deadline = time.time() + 30
        while time.time() < deadline:  # wait for all three files, or for no more to arrive
            if len(downloads) >= len(_CHART_FILES):
                break
            page.wait_for_timeout(250)
        page.wait_for_timeout(250)
        found = {}
        for dl in downloads:
            kind = _CHART_FILES.get(dl.suggested_filename)
            if kind and kind not in found:
                found[kind] = Path(dl.path()).read_text(encoding="utf-8")
        if "symbols" not in found:
            raise RuntimeError(f"the engine page gave no symbol chart (files: {[d.suggested_filename for d in downloads]})")
        out = {}
        shot = self._browser.new_page(viewport={"width": CHART_PX + 40, "height": CHART_PX + 40}, device_scale_factor=2)
        try:
            for kind, svg in found.items():
                svg_path, png_path = out_dir / f"{name}_{kind}.svg", out_dir / f"{name}_{kind}.png"
                svg_path.write_text(svg, encoding="utf-8")
                style = f"<style>{_SYMBOL_STYLE}</style>" if kind == "symbols" else ""
                shot.set_content(f'{style}<body style="margin:20px;background:#fff">{svg}</body>')
                shot.locator("svg").first.screenshot(path=str(png_path))
                out[kind], out[f"{kind}_svg"] = str(png_path), str(svg_path)
        finally:
            shot.close()
        return out


def render_many(repo, items, out_dir) -> list[dict]:
    """items: list of (name, code) or (name, code, dim, chart). One browser for all of them."""
    with Renderer(repo) as r:
        return [r.render(code, out_dir, name, *rest) for name, code, *rest in items]


def render_code(repo, code, out_dir, name="render") -> dict:
    return render_many(repo, [(name, code)], out_dir)[0]

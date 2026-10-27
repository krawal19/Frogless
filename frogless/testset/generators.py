"""Generate known-answer pattern cases: a neutral spec, English text, and the expected answer.

Every number comes from arithmetic on the spec (frogless.testset.spec), never from running
the engine. The English wording is varied per case, chosen deterministically from the seed.
"""

import json
import random
from pathlib import Path

from .spec import Item, Repeat, Spec, consumed, expected, made, skipped

ROOT = Path(__file__).resolve().parents[2]
TURN_CH = {"sc": 1, "hdc": 2, "dc": 3}
# (single, range) label words per style, for rounds and for rows.
LABELS = {"round": ("Round", "Rounds"), "rnd": ("Rnd", "Rnds"), "r": ("R", "R")}
ROW_LABELS = {"round": ("Row", "Rows"), "rnd": ("Row", "Rows"), "r": ("R", "R")}


def load_config(path=None) -> dict:
    path = Path(path) if path else ROOT / "config" / "testset.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---- spec builders ----
def circle_spec(stitch, rounds, ring_size) -> Spec:
    """Flat circle: round n has n * ring_size stitches."""
    k = ring_size
    rows = [[Item("st", stitch, k)], [Item("inc", stitch, k)]]
    for n in range(3, rounds + 1):
        rows.append([Repeat([Item("st", stitch, n - 2), Item("inc", stitch)], k)])
    return Spec("ring", "rounds", rows[:rounds], stitch=stitch)


def ball_spec(peak, even_rounds) -> Spec:
    """Amigurumi ball: increase to 6*peak, work even, then decrease back down to 6."""
    spec = circle_spec("sc", peak, 6)
    spec.rows += [[Item("st", "sc", 6 * peak)] for _ in range(even_rounds)]
    for j in range(peak - 1, 0, -1):  # from 6*(j+1) down to 6*j
        body = ([Item("st", "sc", j - 1)] if j > 1 else []) + [Item("dec", "sc")]
        spec.rows.append([Repeat(body, 6)])
    return spec


def rows_spec(width, nrows) -> Spec:
    """Rectangle in turned sc rows."""
    return Spec("chain", "rows", [[Item("st", "sc", width)] for _ in range(nrows)], chain=width + 1)


# ---- English ----
def _inc(stitch, style, n=1):
    if style["inc"] == "inc":
        name = "inc" if stitch == "sc" else f"{stitch} inc"
        return name if n == 1 else f"{name} in next {n} sts"
    return f"2 {stitch} in next st" if n == 1 else f"2 {stitch} in each of next {n} sts"


def _dec(stitch, style):
    if style["inc"] == "inc":
        return "dec" if stitch == "sc" else f"{stitch} dec"
    return f"{stitch}2tog"


def _part(x, style):
    """One item or repeat group as English."""
    if isinstance(x, Repeat):
        body = ", ".join(_part(i, style) for i in x.items)
        if style["repeat"] == "paren":
            return f"({body}) {x.times} times"
        return f"*{body}* x {x.times}"
    if x.kind == "st":
        return x.stitch if x.n == 1 else f"{x.stitch} in next {x.n} sts"
    if x.kind == "inc":
        return _inc(x.stitch, style, x.n)
    return _dec(x.stitch, style) if x.n == 1 else f"{_dec(x.stitch, style)} {x.n} times"


def _body(items, prev, spec, style, first):
    """The stitch instructions of one round or row."""
    where = "across" if spec.mode == "rows" else "around"
    parts = ", ".join(_part(i, style) for i in items)
    if first and spec.start == "ring" and len(items) == 1:
        return f"{items[0].n} {items[0].stitch} in magic ring"
    if first and spec.start == "chain":
        x = items[0]
        if len(items) == 1 and x.kind == "st" and x.n == spec.chain - skipped(spec):
            return f"{x.stitch} in 2nd ch from hook and across"
        return f"{parts}, starting in 2nd ch from hook"
    if len(items) == 1 and prev is not None and consumed(items) == prev:  # works the whole previous row
        x = items[0]
        if isinstance(x, Repeat):
            if style["repeat"] == "rep" and spec.mode == "rounds":
                return f"*{', '.join(_part(i, style) for i in x.items)}; rep from * around"
        elif x.kind == "st":
            return f"{x.stitch} {where}" if style["across"] == "plain" else f"{x.stitch} in each st {where}"
        elif x.kind == "inc":
            if style["inc"] == "inc":
                return f"{_inc(x.stitch, style)} in each st {where}"
            return f"2 {x.stitch} in each st {where}"
        else:
            return f"{_dec(x.stitch, style)} {where}"
    return parts


def _label(a, b, spec, style):
    one, many = (ROW_LABELS if spec.mode == "rows" else LABELS)[style["label"]]
    word, span = (one, f"{a}") if a == b else (many, f"{a}-{b}")
    return f"{word}{span}:" if word == "R" else f"{word} {span}:"


def render_english(spec, style, stated) -> str:
    """Pattern text for a spec. stated[i] is the count printed after row i (may differ from the spec)."""
    lines = [f"Ch {spec.chain}."] if spec.start == "chain" else []
    i = 0
    while i < len(spec.rows):
        j = i  # rows i..j share one line when they are identical ("Rounds 4-6: ...")
        while style["ranges"] and i > 0 and j + 1 < len(spec.rows) \
                and spec.rows[j + 1] == spec.rows[i] and stated[j + 1] == stated[i]:
            j += 1
        prev = made(spec.rows[i - 1]) if i else None
        text = _body(spec.rows[i], prev, spec, style, first=i == 0)
        if spec.mode == "rows":
            if i:
                text = f"ch {TURN_CH[spec.stitch]}, {text}"
            if j < len(spec.rows) - 1:
                text += ", turn"
        count = f" ({stated[i]})" if style["count"] == "paren" else f" = {stated[i]}"
        lines.append(f"{_label(i + 1, j + 1, spec, style)} {text}{count}")
        i = j + 1
    return "\n".join(lines)


# ---- cases ----
def make_case(case_id, family, spec, style, stated=None, injection=None, known_gap=False) -> dict:
    """A case: spec, English, and the known answer. stated = counts the English claims per row."""
    stated = stated or [made(r) for r in spec.rows]
    return {
        "id": case_id,
        "family": family,
        "injection": injection,
        "known_gap": known_gap,
        "style": style,
        "spec": spec,
        "stated": stated,
        "english": render_english(spec, style, stated),
        "expected": expected(spec, stated),
    }


def pick_style(cfg, case_id) -> dict:
    rng = random.Random(f"{cfg['seed']}:{case_id}")
    return {key: rng.choice(options) for key, options in cfg["styles"].items()}


def base_cases(cfg) -> list[dict]:
    fam = cfg["families"]
    items = []  # (id, family, spec)
    for stitch in fam["circle"]["stitches"]:
        for rounds in fam["circle"]["rounds"]:
            spec = circle_spec(stitch, rounds, fam["circle"]["ring_size"][stitch])
            items.append((f"circle-{stitch}-{rounds}r", "circle", spec))
    for peak in fam["ball"]["peaks"]:
        for even in fam["ball"]["even_rounds"]:
            items.append((f"ball-peak{6 * peak}-even{even}", "ball", ball_spec(peak, even)))
    for width, nrows in fam["rows"]["sizes"]:
        items.append((f"rows-{width}x{nrows}", "rows", rows_spec(width, nrows)))
    return [make_case(i, f, s, pick_style(cfg, i)) for i, f, s in items]

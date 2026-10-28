"""Adapter: runs the engine through bridge.js and maps results to our types."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ..base import (
    CheckError,
    CheckResult,
    Engine,
    RowInfo,
    StitchInfo,
    TranslateLine,
    TranslateResult,
)

BRIDGE = Path(__file__).with_name("bridge.js")
NOTATION_GUIDE = Path(__file__).with_name("notation_guide.md")
VISUAL_SAMPLES = Path(__file__).with_name("visual_samples_synthetic.json")
# Stitch types that are anchors, not counted as stitches.
NOT_STITCHES = {"ring", "tie_up", "start_at", "start_anew", "start_a_new_chain"}
# Slip stitches (round joins) and chains do not follow the normal count rules.
LOOSE_RULES = {"ss", "ch"}
# Rows the translator adds on its own (not written in the pattern).
SYNTHETIC_SOURCES = {"make a magic ring.", "tie_up"}


class CrochetEngine(Engine):
    def __init__(self, cfg):
        env = cfg["repo_path_env"]
        repo = os.environ.get(env)
        if not repo:
            raise RuntimeError(f"{env} is not set; add it to .env (see README > Setup)")
        self.repo = Path(repo)
        if not (self.repo / "parse64.js").is_file():
            raise RuntimeError(f"{env}={repo} is not a CrochetPARADE clone (no parse64.js)")
        self.node = cfg.get("node", "node")
        self.timeout = cfg.get("timeout_s", 30)

    # ---- check ----
    def _run_bridge(self, request):
        proc = subprocess.run(
            [self.node, str(BRIDGE), str(self.repo / "parse64.js")],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"engine bridge failed: {proc.stderr.strip()[:500]}")
        return json.loads(proc.stdout)

    def check(self, code: str) -> CheckResult:
        out = self._run_bridge({"op": "check", "code": _chain_after_turn(code)})
        warnings = [w.strip() for w in out["warnings"]]
        if not out["ok"]:
            return CheckResult(ok=False, error=_parse_error(out["error"]), warnings=warnings)

        rows, stats = _build_rows(out["stitches"])
        result = CheckResult(ok=True, warnings=warnings, rows=rows, stats=stats)
        for row in rows:  # report the first count problem
            if row.overflow or row.unworked:
                result.ok = False
                result.error = _count_error(row)
                break
        return result

    # ---- translate ----
    def translate(self, text: str) -> TranslateResult:
        _add_python_path(self.repo)
        from crochetparade_translator.browser.review_model import (
            build_browser_review_model,
        )

        lines = []
        for row in build_browser_review_model(_label_rows(text))["rows"]:
            cand = next(
                (c for c in row["candidates"] if c["id"] == row.get("selectedId")),
                row["candidates"][0],
            )
            # Lines starting with # are the translator's review notes, not code.
            code = "\n".join(l for l in cand["cpLines"] if not l.startswith("#"))
            parsed = bool(cand["valid"])
            lines.append(
                TranslateLine(
                    source=row["english"],
                    code=code if parsed else "",
                    parsed=parsed,
                    reason="" if parsed else (cand.get("error") or "could not parse"),
                    synthetic=row["english"] in SYNTHETIC_SOURCES,
                )
            )
        _turn_rows(lines)
        return TranslateResult(lines=lines)

    def stitches(self) -> list[str]:
        _add_python_path(self.repo)
        from crochetparade_translator.ir import parser

        return sorted(parser._load_known_stitches(parser.IRParseConfig()))

    def describe(self, code: str) -> list[str]:
        from .describe import describe_code

        return describe_code(code)

    def encode(self, spec) -> str:
        from .encode import encode

        return encode(spec)

    def render(self, code: str, out_dir) -> dict:
        from .render import render_code

        return render_code(self.repo, code, out_dir)

    def render_many(self, items, out_dir) -> list[dict]:
        from .render import render_many

        return render_many(self.repo, items, out_dir)

    def visual_samples(self) -> list[dict]:
        return json.loads(VISUAL_SAMPLES.read_text(encoding="utf-8"))

    def notation_guide(self) -> str:
        return NOTATION_GUIDE.read_text(encoding="utf-8")


ROW_SOURCE = re.compile(r"^row\b", re.IGNORECASE)
ENDS_WITH_TURN = re.compile(r"(^|,)\s*turn\s*$")
# "Ch 21." on a line of its own: a foundation chain
FOUNDATION_LINE = re.compile(r"^\s*(?:ch|chain)\s*\d+\s*[.;]?\s*$", re.IGNORECASE | re.MULTILINE)
TURNS = re.compile(r"\bturn(?:ing)?\b(?!\s+chain)", re.IGNORECASE)
RINGS = re.compile(r"\b(?:magic\s+)?(?:ring|circle)\b|\bmr\b", re.IGNORECASE)
# "R1:", "R2-5 (RS):" at the start of a line
R_LABEL = re.compile(r"^(\s*)R\s*(?=\d+(?:\s*[-–]\s*\d+)?\s*[:(])", re.IGNORECASE | re.MULTILINE)


def _label_rows(text):
    """Flat pieces call their rows "R1:", "R2-5:", which the translator reads as rounds ("rnd").
    A pattern with a foundation chain line or "turn" and no ring is worked in rows, so say "Row"."""
    if (FOUNDATION_LINE.search(text) or TURNS.search(text)) and not RINGS.search(text):
        return R_LABEL.sub(r"\1Row ", text)
    return text


TRAILING_CHAIN = re.compile(r"^(?P<body>.+?),(?P<chain>\d*ch),turn$")
LEADING_CHAIN = re.compile(r"^\d*ch(,|$)")


def _chain_after_turn(code):
    """Put a turning chain written before "turn" at the start of the next row, where it belongs.

    "dc across, ch 3, turn" is code `14dc,3ch,turn`, but the language makes the next row work into
    that chain. The chain is the next row's turning chain: `14dc,turn` then `3ch,14dc`. A row that
    already starts with a chain keeps its own; after the piece's last row there is no row for it.
    """
    lines = code.splitlines()
    for i, line in enumerate(lines):
        m = TRAILING_CHAIN.match(line.strip())
        if not m:
            continue
        lines[i] = f"{m['body']},turn"
        nxt = next((j for j in range(i + 1, len(lines)) if lines[j].strip()), None)
        if nxt is not None and not LEADING_CHAIN.match(lines[nxt].strip()):
            lines[nxt] = f"{m['chain']},{lines[nxt].strip()}"
    return "\n".join(lines)


def _turn_rows(lines):
    """Flat rows are turned at the end even when the text doesn't say so; rounds aren't.

    The translator drops "turn" when it expands a range like "Rows 2-8". Every row
    line except the piece's last row gets one.
    """
    rows = [line for line in lines if ROW_SOURCE.match(line.source)]
    for line in rows[:-1]:
        if line.parsed and line.code and not ENDS_WITH_TURN.search(line.code):
            line.code += ",turn"


def create_engine(cfg) -> Engine:
    return CrochetEngine(cfg)


def _add_python_path(repo):
    sys.dont_write_bytecode = True  # keep the engine clone free of .pyc files
    path = str(repo / "python")
    if path not in sys.path:
        sys.path.insert(0, path)


def _parse_error(raw: str) -> CheckError:
    """Engine errors look like: message, then 'Context:' lines, then 'Tip: ...'."""
    message, _, rest = raw.partition("\nContext:")
    hint = ""
    if "Tip:" in rest:
        rest, _, hint = rest.partition("Tip:")
    elif "Tip:" in message:
        message, _, hint = message.partition("Tip:")
    m = re.search(r"^\s*row/round:\s*(\d+)", rest, re.M)
    return CheckError(
        message=message.strip(),
        row=int(m.group(1)) if m else None,
        hint=hint.strip(),
    )


def _count_error(row: RowInfo) -> CheckError:
    if row.overflow:
        msg = f"Row {row.index} has {row.overflow} more stitch(es) than the previous row has to work into."
    else:
        msg = f"Row {row.index} leaves {row.unworked} stitch(es) of the previous row unworked."
    return CheckError(message=msg, row=row.index, kind="count")


def _loops(group):
    """The loops a row makes, in working order: one dict per loop id."""
    return [
        {"id": i, "kind": s["type"], "attach": s["attach"], "explicit": s["explicit"],
         "labels": s.get("labels") or [], "entry": k}
        for k, s in enumerate(group)
        if s["type"] not in NOT_STITCHES
        for i in s["ids"]
    ]


def _units(loops):
    """What the next row has to work into: each stitch, and each chain space.

    A chain space is a run of chains with a real stitch on both sides. Chains written back to back
    ("ch 2, ch 2") are one space, even when only part of the run carries a label (`2ch.D,2ch`):
    working into the label works the whole space. Only two different labels in one run split it
    in two. Turning chains at the start or end of a row are not spaces, and neither is a
    foundation chain. Slip stitches are never required. Returns a list of
    {"ids": [...], "required": bool}, in working order; a space also has "start" and "end" (its
    first and last position in the row) and "labelled" (the ids of its chains that carry a label).
    """
    stitch_at = [k for k, lp in enumerate(loops) if lp["kind"] != "ch"]
    first, last = (stitch_at[0], stitch_at[-1]) if stitch_at else (None, None)
    units = []
    run = None  # the open chain run
    for k, lp in enumerate(loops):
        if lp["kind"] == "ch":
            labels = tuple(lp["labels"])
            if run and not (labels and run["labels"] and labels != run["labels"]):
                run["ids"].append(lp["id"])
                run["end"] = k
                if labels:
                    run["labels"] = labels
                    run["labelled"].add(lp["id"])
                continue
            run = {"ids": [lp["id"]], "labels": labels, "start": k, "end": k,
                   "labelled": {lp["id"]} if labels else set()}
            units.append(run)
        else:
            run = None
            units.append({"ids": [lp["id"]], "required": lp["kind"] not in LOOSE_RULES})
    for u in units:
        if "start" in u:
            u["required"] = first is not None and first < u["start"] and u["end"] < last
    return units


def _slide_past_spaces(group, prev_loops, units):
    """Where each stitch of the row really lands, as (attach per group entry, stitches past the end).

    The engine moves on from an @ group to the loop after the last one it used. When a chain
    space was written as a labelled part and an unlabelled part (`2ch.D,2ch`), that is the
    unlabelled chains of the same space, which `@D` already worked. The stitches that follow
    start there, so they would look as if they were worked into chains. They really start on the
    next stitch: slide them (and the stitches after them, until the next @ group) past the
    space. Stitches that slide past the end of the row below are counted and returned.
    """
    unit_of = {i: u for u, unit in enumerate(units) for i in unit["ids"]}
    pos_of = {lp["id"]: k for k, lp in enumerate(prev_loops)}
    # the end of the row below is its last real stitch (a round's closing slip stitch is past it)
    end = max((k for k, lp in enumerate(prev_loops) if lp["kind"] not in LOOSE_RULES), default=-1)
    attach = [list(s["attach"]) for s in group]
    reached: set[int] = set()  # spaces an @ group has worked into
    shift = 0
    past_end = 0
    for e, s in enumerate(group):
        if s["explicit"]:
            shift = 0
            reached.update(unit_of[a] for a in s["attach"] if a in unit_of)
            continue
        if not shift:
            for a in s["attach"]:
                u = unit_of.get(a)
                if u in reached and "start" in units[u] and a not in units[u]["labelled"]:
                    shift = len(units[u]["ids"]) - units[u]["ids"].index(a)
                    break
        if shift:
            moved = []
            for a in s["attach"]:
                k = pos_of.get(a)
                if k is None:
                    moved.append(a)
                elif k + shift <= end:
                    moved.append(prev_loops[k + shift]["id"])
            past_end += bool(s["attach"]) and not moved
            attach[e] = moved
    return attach, past_end


def _explicit_row_counts(group, loops, prev_loops):
    """Count problems of a row that uses @ attachments (labels, @R0, @[...]).

    Returns (unworked, overflow) against the row below.

    unworked: stitches and chain spaces of the row below that nothing in this row works into.
      - a stitch skipped with "sk" is worked (it was used up on purpose);
      - a chain space is worked if anything is worked into any of its chains;
      - turning chains and the foundation chain are never required (see _units);
      - a run of chains between two worked places bridges the stitches it passes over (the
        chain stands in for them, as in "ch 1" over a cluster of dc, or over one stitch in mesh
        work; a chain closing a round reaches back over the stitches before its first stitch).
        It never bridges a chain space: those are worked into or skipped with "sk".
    overflow: stitches that run past the end of the row below (they land on this row's own
      loops without an @), plus stitches that carry on into places already worked, or about
      to be worked by an explicit @ stitch (a side that works more stitches than it has).
    """
    own_ids = {lp["id"] for lp in loops}
    checked = [s for s in group if s["type"] not in NOT_STITCHES | LOOSE_RULES]
    # (an explicit @ into this row's own loops is fine: working back into chains just made)
    overflow = sum(1 for s in checked if not s["explicit"] and own_ids & set(s["attach"]))

    units = _units(prev_loops)
    unit_of = {i: u for u, unit in enumerate(units) for i in unit["ids"]}
    attach, past_end = _slide_past_spaces(group, prev_loops, units)
    overflow += past_end
    loops = [{**lp, "attach": attach[lp["entry"]]} for lp in loops]
    worked = {unit_of[a] for e in range(len(group)) for a in attach[e] if a in unit_of}

    # chains between two worked places stand in for the stitches they pass over
    for k, lp in enumerate(loops):
        if lp["kind"] != "ch" or (k and loops[k - 1]["kind"] == "ch"):
            continue
        end = k
        while end + 1 < len(loops) and loops[end + 1]["kind"] == "ch":
            end += 1
        before = next((l for l in reversed(loops[:k]) if l["kind"] not in LOOSE_RULES), None)
        after = next((l for l in loops[end + 1:] if l["kind"] not in LOOSE_RULES), None)
        wraps = after is None  # a chain at the end of a round reaches back to the round's start
        if wraps:
            after = next((l for l in loops if l["kind"] not in LOOSE_RULES | {"ch"}), None)
        if not before or not after:
            continue
        a = {unit_of[i] for i in before["attach"] if i in unit_of}
        b = {unit_of[i] for i in after["attach"] if i in unit_of}
        if not a or not b:
            continue
        if wraps:
            between = [u for u in range(len(units)) if u > max(a) or u < min(b)]
        elif min(b) >= max(a):
            between = range(max(a) + 1, min(b))
        else:
            between = range(max(b) + 1, min(a))
        worked.update(u for u in between if "start" not in units[u])

    unworked = sum(1 for u, unit in enumerate(units) if unit["required"] and u not in worked)

    # a round that runs off the end of the row below carries on into the stitches at its start
    # (the engine has no way to wrap): those stitches are worked, not left over
    start_unworked = 0
    for u, unit in enumerate(units):
        if not unit["required"]:
            continue
        if u in worked:
            break
        start_unworked += 1
    wrapped = min(overflow, start_unworked)
    unworked -= wrapped

    # overlap: a stitch worked in the order of the row that lands on a place another stitch uses
    hits: dict[int, list[tuple[int, bool]]] = {}
    for e, s in enumerate(group):
        if s["type"] in NOT_STITCHES | {"ss"}:
            continue
        for a in attach[e]:
            if a in unit_of:
                hits.setdefault(a, []).append((e, s["explicit"]))
    for e, s in enumerate(group):
        if s["explicit"] or s["type"] in NOT_STITCHES | LOOSE_RULES | {"sk"}:
            continue
        if any(
            (f < e) or (f > e and explicit)
            for a in attach[e]
            for f, explicit in hits.get(a, [])
            if f != e
        ):
            overflow += 1
    return unworked, overflow - wrapped


def _build_rows(stitches):
    """Group the engine's stitch list by row and compare each row to the one before."""
    by_row: dict[int, list[dict]] = {}
    for s in stitches:
        by_row.setdefault(s["row"], []).append(s)

    # where each loop sits: id -> (row index, position in that row)
    loops_of = {index: _loops(group) for index, group in by_row.items()}
    place = {
        lp["id"]: (index, pos)
        for index, loops in loops_of.items()
        for pos, lp in enumerate(loops)
    }

    rows = []
    prev = None  # previous row's stitches
    prev_index = None
    for index in sorted(by_row):
        group = by_row[index]
        counted = [s for s in group if s["type"] not in NOT_STITCHES]
        types: dict[str, int] = {}
        for s in counted:
            types[s["type"]] = types.get(s["type"], 0) + len(s["ids"])
        info = RowInfo(index=index, stitch_count=sum(types.values()), stitch_types=types)
        info.stitches = [
            StitchInfo(
                position=pos,
                kind=lp["kind"],
                into=list(dict.fromkeys(place[a] for a in lp["attach"] if a in place)),
                label=lp["labels"][0] if lp["labels"] else "",
            )
            for pos, lp in enumerate(loops_of[index])
        ]

        # Count check. Plain sequential rows: compare the loops directly.
        checked = [s for s in counted if s["type"] not in LOOSE_RULES]
        plain = not any(s["explicit"] for s in group)
        if prev is not None and any(s["attach"] for s in checked):
            if plain:
                own_ids = {i for s in group for i in s["ids"]}
                info.overflow = sum(1 for s in checked if own_ids & set(s["attach"]))
                worked = {i for s in group for i in s["attach"]}
                should = {
                    i
                    for s in prev
                    if s["type"] not in NOT_STITCHES | LOOSE_RULES
                    for i in s["ids"]
                }
                info.unworked = len(should - worked)
            else:
                info.unworked, info.overflow = _explicit_row_counts(
                    group, loops_of[index], loops_of[prev_index]
                )
        if counted:
            rows.append(info)
        prev = group
        prev_index = index
    stats = {"total_stitches": sum(r.stitch_count for r in rows), "rows": len(rows)}
    return rows, stats

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


def _build_rows(stitches):
    """Group the engine's stitch list by row and compare each row to the one before."""
    by_row: dict[int, list[dict]] = {}
    for s in stitches:
        by_row.setdefault(s["row"], []).append(s)

    rows = []
    prev = None  # previous row's stitches
    for index in sorted(by_row):
        group = by_row[index]
        counted = [s for s in group if s["type"] not in NOT_STITCHES]
        types: dict[str, int] = {}
        for s in counted:
            types[s["type"]] = types.get(s["type"], 0) + len(s["ids"])
        info = RowInfo(index=index, stitch_count=sum(types.values()), stitch_types=types)

        # Count check: only plain sequential rows (no explicit @ attachments).
        checked = [s for s in counted if s["type"] not in LOOSE_RULES]
        plain = not any(s["explicit"] for s in group)
        if prev is not None and plain and any(s["attach"] for s in checked):
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
        if counted:
            rows.append(info)
        prev = group
    stats = {"total_stitches": sum(r.stitch_count for r in rows), "rows": len(rows)}
    return rows, stats

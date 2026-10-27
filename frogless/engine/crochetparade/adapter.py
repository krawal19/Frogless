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
        out = self._run_bridge({"op": "check", "code": code})
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
        for row in build_browser_review_model(text)["rows"]:
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
        return TranslateResult(lines=lines)

    def stitches(self) -> list[str]:
        _add_python_path(self.repo)
        from crochetparade_translator.ir import parser

        return sorted(parser._load_known_stitches(parser.IRParseConfig()))

    def describe(self, code: str) -> list[str]:
        from .describe import describe_code

        return describe_code(code)

    def notation_guide(self) -> str:
        return NOTATION_GUIDE.read_text(encoding="utf-8")


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

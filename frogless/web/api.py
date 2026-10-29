"""The HTTP API (FastAPI) and the functions the page calls.

POST /api/check          check a pattern (every size of a multi-size pattern); returns the verdict, the texts and an id
POST /api/render/{id}    draw the charts of one size of a checked pattern; returns image URLs
GET  /api/examples       example patterns, read at run time from external_patterns/dev/ and logs/smoke/
GET  /files/<id>/...     the drawn images (served from logs/web/)
GET  /                   the page (static files in frogless/web/static/)

Only the public Frogless API is used: pipeline.check, pipeline.messages and pipeline.output.
"""

import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..pipeline import check as pipeline_check
from ..pipeline import messages, output

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "logs" / "web"
STATIC_DIR = Path(__file__).resolve().parent / "static"
EXAMPLE_DIRS = (("dev", ROOT / "external_patterns" / "dev"), ("smoke", ROOT / "logs" / "smoke"))  # read at run time
KEEP_REPORTS = 50  # checked patterns kept in memory

STAGES = ("translate", "faithfulness", "reconcile", "ledger", "engine_verdict", "review", "shape", "total")
VERDICT_GROUP = {"works": "works", "works_unverified": "works", "works_counts_only": "works",
                 "breaks": "breaks", "ambiguous": "ambiguous", "unreadable": "unreadable"}

_reports: "OrderedDict[str, list[tuple[str, object]]]" = OrderedDict()  # id -> [(size label, PatternReport)]
_render_lock = threading.Lock()  # one browser drawing at a time

_LABEL = re.compile(r"^\s*(?:rows?|rounds?|rnds?|r)\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*:", re.IGNORECASE)
_LABEL_TEXT = re.compile(r"^\s*(?:rows?|rounds?|rnds?|r)\b\s*[\d\s\-–,&and]*:\s*(?:\(\d+\):\s*)?", re.IGNORECASE)
_FIX_MARKS = ("[suggested fix", "[works if", "[added")


class CheckRequest(BaseModel):
    text: str
    terms: Literal["auto", "US", "UK"] = "auto"


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# ---- one report as JSON ----
def _row_offset(rows) -> int:
    """The number the first written row takes: the first labelled row says it ("Round 1" after a ring is row 1,
    "Row 1" after a foundation chain is row 1 while the chain is row 0)."""
    written = [r for r in rows if not r.synthetic]
    for n, row in enumerate(written):
        m = _LABEL.match(row.source)
        if m:
            return int(m.group(1)) - n
    return 1


def _table(report) -> list[dict]:
    v = report.verdict
    offset = _row_offset(report.rows)
    table, n = [], 0
    for row in report.rows:
        if row.synthetic:
            table.append({"number": None, "text": "(added: magic ring)", "translated_by": "added",
                          "read_back": row.english, "stated": None, "computed": None, "status": "added", "note": row.note})
            continue
        number = n + offset
        n += 1
        if row.ledger_ok is not None:
            by, status = "counted by AI", ("ok" if row.ledger_ok else "breaks")
        elif not row.code:
            by, status = ("model" if row.origin == "model" else "none"), "not checked"
        else:
            by, status = row.origin, "ok"
        if v and v.kind == "breaks" and v.row == number:
            status = "breaks"
        elif v and v.kind == "breaks" and v.row is not None and number > v.row and status == "ok":
            status = "after the break"
        elif row.faithful is False and status == "ok":
            status = "check the reading"
        notes = [x for x in (row.note, row.ledger_note, f"read as: {row.reading}" if row.reading else "") if x]
        table.append({"number": number, "text": _LABEL_TEXT.sub("", row.source.strip(), count=1).strip() or row.source.strip(),
                      "translated_by": by, "read_back": row.english, "stated": report.stated.get(number),
                      "computed": report.computed.get(number), "status": status, "note": "; ".join(notes)})
    return table


def _find_line(lines: list[str], written: str, number: int | None) -> int | None:
    """Index of the line holding the row: by its text, else by its label."""
    wanted = _plain(_LABEL_TEXT.sub("", written.strip(), count=1))
    if wanted:
        for i, line in enumerate(lines):
            if wanted in _plain(line):
                return i
    if number is not None:
        for i, line in enumerate(lines):
            m = _LABEL.match(line)
            if m and int(m.group(1)) <= number <= int(m.group(2) or m.group(1)):
                return i
    return None


def _written_lines(report, table: list[dict]) -> list[dict]:
    """The pattern as written, line by line; the breaking row and each row a fix changes are marked."""
    lines = report.text.splitlines()
    marks: dict[int, tuple[str, str]] = {}
    v = report.verdict
    if v and v.kind == "breaks" and v.row is not None:
        source = next((r["text"] for r in table if r["number"] == v.row), "")
        at = _find_line(lines, source, v.row)
        if at is not None:
            marks[at] = ("breaks", "breaks here")
    for f in (v.fixes if v else []):
        if f.insert:
            continue
        at = _find_line(lines, f.original, f.row)
        if at is not None and at not in marks:
            marks[at] = ("fix", "fixed on the right" + (" (only if the turning chain does not count)" if f.conditional else ""))
    return [{"text": line, "mark": marks.get(i, ("", ""))[0], "note": marks.get(i, ("", ""))[1]}
            for i, line in enumerate(lines)]


def _corrected_lines(text: str | None) -> list[dict]:
    return [{"text": line, "mark": "fix" if any(m in line for m in _FIX_MARKS) else "", "note": ""}
            for line in (text or "").splitlines()]


def _corrected_status(report) -> str:
    v = report.verdict
    if v and v.fixes:
        return "fixed"
    return "none_needed" if v and VERDICT_GROUP.get(v.kind) == "works" else "no_fix"


def describe(report, label: str = "") -> dict:
    """Everything the page shows about one checked pattern, as plain JSON-ready data."""
    v = report.verdict
    table = _table(report)
    corrected = output.corrected_pattern(report)
    clean = output.clean_pattern(report)
    # when the fix cannot be placed into the written text, show the rebuilt pattern (it has the fix applied and marked)
    shown, source = (corrected, "written") if corrected else (clean if _corrected_status(report) == "fixed" else None, "rebuilt")
    return {
        "label": label,
        "verdict": {"kind": v.kind if v else "unreadable", "group": VERDICT_GROUP.get(v.kind, "unreadable") if v else "unreadable",
                    "row": v.row if v else None},
        "user_message": messages.user_message(report),
        "fix_lines": messages.fix_lines(report),
        "notes": list(report.notes),
        "shape_lines": messages.shape_lines(report),
        "rows": table,
        "terms": report.terms.kind if report.terms else None,
        "written_lines": _written_lines(report, table),
        "corrected_status": _corrected_status(report),
        "corrected_pattern": corrected,
        "corrected_lines": _corrected_lines(shown),
        "corrected_source": source if shown else None,
        "clean_pattern": clean,
        "timings": {k: report.timings.get(k, 0.0) for k in STAGES},
        "cost_usd": round(report.cost_usd, 4),
    }


# ---- check ----
def run_check(text: str, terms: str = "auto") -> dict:
    """Check a pattern (all its sizes) and keep the reports by id. Slow when the model is needed."""
    if not text.strip():
        raise ValueError("Paste a pattern first.")
    sized = pipeline_check.check_pattern_sizes(text, terms=terms)
    check_id = uuid.uuid4().hex[:12]
    _reports[check_id] = sized
    while len(_reports) > KEEP_REPORTS:
        _reports.popitem(last=False)
    multi = len(sized) > 1
    results = [describe(report, label if multi else "") for label, report in sized]
    out = {"id": check_id, "sizes": len(results), "results": results,
           "cost_usd": round(sum(r["cost_usd"] for r in results), 4)}
    return {**results[0], **out}  # a single-size pattern reads flat: the first size's fields sit at the top too


# ---- render ----
def _url(path) -> str | None:
    if not path:
        return None
    try:
        return "/files/" + Path(path).resolve().relative_to(WEB_DIR.resolve()).as_posix()
    except ValueError:
        return None


def _images(drawn: dict) -> dict:
    sketch = drawn.get("connectivity") or drawn.get("overlay")
    return {"symbols": _url(drawn.get("symbols") or drawn.get("chart")), "sketch": _url(sketch),
            "overlay": _url(drawn.get("overlay")), "view_3d": _url(drawn.get("view")),
            "error": drawn.get("error"), "note": drawn.get("note") or ""}


def run_render(check_id: str, size: int = 0) -> dict:
    """Draw the as-written and corrected charts of one size of a checked pattern."""
    sized = _reports.get(check_id)
    if sized is None:
        raise KeyError(check_id)
    if not 0 <= size < len(sized):
        raise IndexError(size)
    _, report = sized[size]
    folder = WEB_DIR / check_id / f"size{size}"
    started = time.perf_counter()
    with _render_lock:
        written = _images(output.written_chart(report, folder, "written"))
        fixed = _corrected_status(report) == "fixed"
        corrected = _images(output.corrected_chart(report, folder, "corrected")) if fixed else None
    return {"id": check_id, "size": size, "written": written, "corrected": corrected,
            "render_seconds": round(time.perf_counter() - started, 2)}


# ---- examples ----
def list_examples() -> list[dict]:
    """The example patterns found right now: {name, group, text}. Read from disk on every call, never copied into the repo."""
    found = []
    for group, folder in EXAMPLE_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.txt")):
            try:
                found.append({"name": path.stem, "group": group, "text": path.read_text(encoding="utf-8")})
            except OSError:
                continue
    return found


# ---- the app ----
def create_api() -> FastAPI:
    app = FastAPI(title="Frogless")
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/files", StaticFiles(directory=WEB_DIR), name="files")

    @app.post("/api/check")
    def api_check(req: CheckRequest) -> dict:
        try:
            return run_check(req.text, req.terms)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/render/{check_id}")
    def api_render(check_id: str, size: int = 0) -> dict:
        try:
            return run_render(check_id, size)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown check id (the server keeps the last {KEEP_REPORTS} checks in memory).")
        except IndexError:
            raise HTTPException(status_code=404, detail="No such size.")

    @app.get("/api/examples")
    def api_examples() -> dict:
        return {"examples": list_examples()}

    if STATIC_DIR.is_dir():  # last, so it never shadows the routes above
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="page")
    return app

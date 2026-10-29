"""The HTTP API (FastAPI) and the functions the page calls.

POST /api/check          start a check in its own process; returns {"job": id}  (?wait=1: block and return the result)
POST /api/render/{id}    start drawing one size of a checked pattern in its own process; returns {"job": id}  (?wait=1: block)
GET  /api/job/{id}       the job's state: running | done | error | stopped, with the result when done
POST /api/stop/{id}      terminate the job's process (and the drawing of the same check)
GET  /api/examples       example patterns, read at run time from external_patterns/dev/ and logs/smoke/
GET  /files/<id>/...     the drawn images (served from logs/web/)
GET  /                   the page (static files in frogless/web/static/)

Only the public Frogless API is used: pipeline.check, pipeline.messages and pipeline.output.
"""

import multiprocessing
import queue as queue_mod
import re
import subprocess
import sys
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
                          "read_back": row.english, "stated": None, "computed": None, "status": "added", "note": row.note,
                          "double_checked": False})
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
                      "computed": report.computed.get(number), "status": status, "note": "; ".join(notes),
                      "double_checked": row.faithful is True or row.ledger_ok is not None})
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
    return _store_check(pipeline_check.check_pattern_sizes(text, terms=terms))


def _store_check(sized) -> dict:
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


# ---- jobs: a check or a drawing runs in its own process so Stop can end it ----
KEEP_JOBS = 100


def _check_worker(out, text: str, terms: str) -> None:
    """Child process: run the checker and send back the reports (top-level so Windows 'spawn' can import it)."""
    try:
        out.put(("ok", pipeline_check.check_pattern_sizes(text, terms=terms)))
    except BaseException as e:  # noqa: BLE001 - whatever happens, tell the parent
        out.put(("error", f"{type(e).__name__}: {e}"))


def _render_worker(out, lock, report, folder: str) -> None:
    """Child process: draw the as-written and corrected charts of one report."""
    try:
        with lock:
            written = output.written_chart(report, Path(folder), "written")
            fixed = _corrected_status(report) == "fixed"
            corrected = output.corrected_chart(report, Path(folder), "corrected") if fixed else None
        out.put(("ok", (written, corrected)))
    except BaseException as e:  # noqa: BLE001
        out.put(("error", f"{type(e).__name__}: {e}"))


_CTX = multiprocessing.get_context("spawn")
_render_lock_mp = None


def _mp_lock():
    global _render_lock_mp
    if _render_lock_mp is None:
        _render_lock_mp = _CTX.Lock()
    return _render_lock_mp


def _launch(target, args: tuple):
    """Start target(queue, *args) in a new process; returns (process, queue). Tests replace this."""
    out = _CTX.Queue()
    proc = _CTX.Process(target=target, args=(out, *args), daemon=True)
    proc.start()
    return proc, out


def _kill(proc) -> None:
    """End a process and everything it started (the drawing starts a browser)."""
    pid = getattr(proc, "pid", None)
    if pid and sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    proc.terminate()


class Job:
    def __init__(self, kind: str, proc, out, check_id: str | None = None, size: int = 0):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.proc, self.out, self.check_id, self.size = kind, proc, out, check_id, size
        self.started = time.perf_counter()
        self.state, self.result, self.error = "running", None, ""

    def view(self) -> dict:
        body = {"id": self.id, "kind": self.kind, "state": self.state}
        if self.state == "done":
            body["result"] = self.result
        if self.state == "error":
            body["error"] = self.error
        return body


_jobs: "OrderedDict[str, Job]" = OrderedDict()
_jobs_lock = threading.Lock()


def _add_job(job: Job) -> Job:
    with _jobs_lock:
        _jobs[job.id] = job
        for old in [k for k, j in _jobs.items() if j.state != "running"][:max(0, len(_jobs) - KEEP_JOBS)]:
            _jobs.pop(old, None)
    return job


def _render_result(job: Job, drawn) -> dict:
    written, corrected = drawn
    return {"id": job.check_id, "size": job.size, "written": _images(written),
            "corrected": _images(corrected) if corrected else None,
            "render_seconds": round(time.perf_counter() - job.started, 2)}


def _finish(job: Job, kind: str, payload) -> None:
    if kind == "error":
        job.state, job.error = "error", str(payload)
        return
    try:
        job.result = _store_check(payload) if job.kind == "check" else _render_result(job, payload)
        job.state = "done"
    except Exception as e:  # noqa: BLE001
        job.state, job.error = "error", f"{type(e).__name__}: {e}"


def poll_job(job_id: str) -> Job | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job.state != "running":
            return job
        try:
            kind, payload = job.out.get_nowait()
        except queue_mod.Empty:
            if job.proc.is_alive():
                return job
            try:  # the worker ended: its answer may still be on the way
                kind, payload = job.out.get(timeout=0.5)
            except queue_mod.Empty:
                job.state, job.error = "error", "The work stopped unexpectedly."
                return job
        _finish(job, kind, payload)
        return job


def stop_job(job_id: str) -> Job | None:
    """Terminate a job, and the drawing(s) of the same check."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        group = [j for j in _jobs.values() if j is job or (job.check_id and j.check_id == job.check_id)]
        for j in group:
            if j.state == "running":
                try:
                    _kill(j.proc)
                except Exception:  # noqa: BLE001
                    pass
                j.state = "stopped"
    return job


def start_check(text: str, terms: str = "auto") -> Job:
    if not text.strip():
        raise ValueError("Paste a pattern first.")
    proc, out = _launch(_check_worker, (text, terms))
    return _add_job(Job("check", proc, out))


def start_render(check_id: str, size: int = 0) -> Job:
    sized = _reports.get(check_id)
    if sized is None:
        raise KeyError(check_id)
    if not 0 <= size < len(sized):
        raise IndexError(size)
    folder = WEB_DIR / check_id / f"size{size}"
    proc, out = _launch(_render_worker, (_mp_lock(), sized[size][1], str(folder)))
    return _add_job(Job("render", proc, out, check_id=check_id, size=size))


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
    def api_check(req: CheckRequest, wait: bool = False) -> dict:
        try:
            return run_check(req.text, req.terms) if wait else {"job": start_check(req.text, req.terms).id}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/job/{job_id}")
    def api_job(job_id: str) -> dict:
        job = poll_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job.")
        return job.view()

    @app.post("/api/stop/{job_id}")
    def api_stop(job_id: str) -> dict:
        job = stop_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job.")
        return job.view()

    @app.post("/api/render/{check_id}")
    def api_render(check_id: str, size: int = 0, wait: bool = False) -> dict:
        try:
            return run_render(check_id, size) if wait else {"job": start_render(check_id, size).id}
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

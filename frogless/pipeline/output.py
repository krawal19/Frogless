"""What the user gets besides the verdict: a clean written pattern and a picture of the piece.

clean_pattern(report) rewrites the CHECKED code as plain US crochet text, row by row, with the
stitch count at the end of each row. chart(report, out_dir) draws the assembled code: the standard
crochet symbol chart (with the connectivity diagram and the overlay on the side), and the 3D view only for
pieces the shape hints call clearly 3D (the 3D view bends flat pieces, so it is not shown for them). For the as-written / corrected
pair: written_chart (every row as written, mistakes included), corrected_pattern, corrected_code and
corrected_chart (the review's re-checked fixes applied). None of these shows engine code except
corrected_code.
"""

import re
from pathlib import Path

from ..engine import get_engine
from ..patterns.repeats import merge_repeat_chains
from ..patterns.terms import to_us
from ..patterns.wording import normalise_wording
from .messages import change_text, user_message
from .report import PatternReport, RowResult
from .verdict import _map_rows

THREE_D_KINDS = ("ball", "dome", "cups", "tube")  # shape hints that say the piece is not flat
INSTALL_HINT = ("Rendering needs Playwright and Chromium: pip install playwright, then "
                "python -m playwright install chromium (README > Setup > Visual rendering).")

_LABEL = re.compile(r"^\s*(?P<word>rows?|rounds?|rnds?|r)\b\s*[\d\s\-–,&and]*:\s*(?:\(\d+\):\s*)?", re.IGNORECASE)
_ENGINE_PREFIX = re.compile(r"^(Round|Row)\s+\d+:\s*")


def _word(row: RowResult) -> str | None:
    """'Row' or 'Round' when the row is labelled in the pattern, None for an unlabelled line (a foundation chain)."""
    m = _LABEL.match(row.source)
    if not m:
        return None
    return "Row" if m["word"].lower().startswith("row") else "Round"


def _sentences(report: PatternReport, engine) -> dict[int, str]:
    """Position in report.rows -> its English sentence(s), engine numbering stripped."""
    coded = [(i, r) for i, r in enumerate(report.rows) if r.code]
    lines = [[ln for ln in r.code.splitlines() if ln.strip() and not ln.strip().startswith("#")] for _, r in coded]
    try:
        whole = engine.describe(report.code)
    except Exception:
        whole = []
    if len(whole) != sum(len(ls) for ls in lines):  # cannot line them up: describe each row alone
        whole = []
        for (_, r), ls in zip(coded, lines):
            whole += engine.describe(r.code) if ls else []
        lines = [[ln for ln in r.code.splitlines() if ln.strip() and not ln.strip().startswith("#")] for _, r in coded]
    out, at = {}, 0
    for (pos, _), ls in zip(coded, lines):
        parts = [_ENGINE_PREFIX.sub("", s) for s in whole[at:at + len(ls)]]
        at += len(ls)
        out[pos] = " ".join(p for p in parts if p)
    return out


def _span(word: str, numbers: list[int]) -> str:
    if len(numbers) == 1:
        return f"{word} {numbers[0]}"
    return f"{word}s {numbers[0]}-{numbers[-1]}"


def _written(source: str) -> str:
    """The row as the pattern wrote it, without its label."""
    return _LABEL.sub("", source.strip(), count=1).strip()


def _mark(f) -> str:
    if f.insert:
        return "[suggested fix: this row was added]"
    if f.conditional:
        return f"[works if the turning chain counts as a stitch; if not, suggested fix: {change_text(f.original, f.fixed_text)}]"
    return f"[suggested fix: {change_text(f.original, f.fixed_text)}]"


def clean_pattern(report: PatternReport) -> str:
    """A clean written pattern from the checked code, in US terms; plain text, no engine code.

    A pattern that breaks but has a re-checked fix is shown with the fix applied; fixed rows are marked
    "[suggested fix: ...]" (the same mark goes on the fixed rows of an ambiguous pattern).
    """
    v = report.verdict
    marks = {f.row: _mark(f) for f in (v.fixes if v else [])}
    fixed = report.review.fixed_report if report.review else None
    if v and v.kind == "breaks" and v.fixes and fixed is not None:
        word = _word_of(report)
        head = (f"Note: as written, this pattern breaks at {word} {v.row}. It is shown here with the suggested "
                f"fix{'es' if len(v.fixes) > 1 else ''} applied (marked); that version was re-checked and works.")
        return head + "\n" + _clean(fixed, marks)
    return _clean(report, marks)


def _clean(report: PatternReport, marks: dict[int, str]) -> str:
    engine = get_engine()
    mapped, _ = _map_rows(engine, report.rows, report.check)
    number = {id(m.result): m.number for m in mapped}
    sentences = _sentences(report, engine)
    v = report.verdict
    broke_at = v.row if v and v.kind == "breaks" else None
    first_unread = v.row if v and v.kind == "unreadable" else None
    interpreted = {it.row: it.reading for it in (v.interpreted if v else [])}
    unconfirmed = set(v.rows) if v and v.kind == "works_unverified" else set()
    unread_seen = False

    entries = []  # (word, number, text, note) per row
    for pos, row in enumerate(report.rows):
        n = number.get(id(row))
        word = _word(row)
        if row.synthetic:
            entries.append((None, None, sentences.get(pos, ""), ""))
            continue
        label_word = word or "Round"
        if row.ledger_ok is not None:  # counted by AI, never modelled: given as written
            note = ("[counts checked; not modelled]" if row.ledger_ok
                    else "[the pattern breaks here]")
            entries.append((word, n, _written(row.source) if word else row.source.strip(), note))
            continue
        if not row.code:
            unread_seen = True
            entries.append((word, n, _written(row.source) if word else row.source.strip(), "[not checked]"))
            continue
        if broke_at is not None and n is not None and n > broke_at:
            entries.append((word, n, _written(row.source) if word else row.source.strip(),
                            f"[not checked: the pattern breaks at {label_word} {broke_at}]"))
            continue
        text = sentences.get(pos, "") or (_written(row.source) if word else row.source.strip())
        notes = []
        if n in interpreted:
            notes.append(f"(read as: {interpreted[n]})")
        if n in unconfirmed:
            notes.append("[not confirmed]")
        if n in marks:
            notes.append(marks[n])
        if broke_at is not None and n == broke_at:
            notes.append("[the pattern breaks here]")
        count = report.computed.get(n) if word and n is not None else None
        if count is not None and not unread_seen:
            text = f"{text.rstrip('.')}. ({count})" if text else f"({count})"
        entries.append((word, n, text, " ".join(notes)))

    lines = []
    if v and v.kind == "breaks":
        lines.append(f"Note: this pattern breaks at {_word_of(report)} {v.row}: {v.message}. "
                     "Rows after it are given as written and were not checked.")
    elif v and v.kind == "unreadable":
        lines.append("Note: Frogless could not read every row. Those rows are given as written, marked [not checked].")
    elif v and v.kind == "ambiguous":
        lines.append("Note: " + (user_message(report).lstrip("⚠ ") if v.fixes else f"{v.message}."))
    # merge consecutive labelled rows that read the same (the pattern's "Rounds 10-12")
    i = 0
    while i < len(entries):
        word, n, text, note = entries[i]
        j = i
        while (word and n is not None and j + 1 < len(entries) and entries[j + 1][0] == word
               and entries[j + 1][1] == entries[j][1] + 1 and entries[j + 1][2] == text and entries[j + 1][3] == note):
            j += 1
        if word and n is not None:
            label = _span(word, [entries[k][1] for k in range(i, j + 1)])
            lines.append(" ".join(p for p in (f"{label}: {text}", note) if p))
        else:
            lines.append(" ".join(p for p in (text, note) if p))
        i = j + 1
    return "\n".join(line for line in lines if line.strip())


def _word_of(report: PatternReport) -> str:
    for r in report.rows:
        if not r.synthetic and _word(r):
            return _word(r)
    return "Round"


def _kind(report: PatternReport) -> str:
    """'3d' when the shape hints say the piece is clearly 3D, else 'chart'."""
    return "3d" if any(f.kind in THREE_D_KINDS for f in report.shape) else "chart"


def _code_before(report: PatternReport, row: int) -> str:
    """The code of the rows before the pattern's row number `row` (the ring, if any, comes along)."""
    mapped, _ = _map_rows(get_engine(), report.rows, report.check)
    number = {id(m.result): m.number for m in mapped}
    kept = [r.code for r in report.rows if r.code and (r.synthetic or number.get(id(r), row) < row)]
    return "\n".join(kept)


def _draw(code: str, out_dir, name: str, show_3d: bool) -> dict:
    """Render code into out_dir as <name>_*.png. Returns the picture paths, "seconds", and "error" (None if drawn)."""
    out = {"chart": None, "symbols": None, "symbols_svg": None, "connectivity": None, "overlay": None,
           "view": None, "error": None, "seconds": None}
    try:
        drawn = get_engine().render(code, Path(out_dir), name)
    except Exception as e:  # missing Playwright or Chromium, or the page failing
        message = f"{type(e).__name__}: {e}"
        out["error"] = INSTALL_HINT if ("Playwright" in message or "Chromium" in message
                                        or isinstance(e, ImportError)) else message
        return out
    charts = drawn.get("charts_2d") or {}
    out["chart"] = out["symbols"] = drawn.get("chart_2d")  # the symbol chart is the default chart
    out["symbols_svg"] = charts.get("symbols_svg")
    out["connectivity"], out["overlay"] = charts.get("connectivity"), charts.get("overlay")
    if show_3d:
        out["view"] = drawn.get("model_3d")
    out["seconds"] = drawn.get("seconds")
    out["error"] = drawn.get("error") or (None if out["chart"] or out["view"] else drawn.get("chart_error"))
    return out


def _has_code(code: str) -> bool:
    return bool(code.strip()) and code.strip() != "ring.R0"


def chart(report: PatternReport, out_dir, name: str = "chart") -> dict:
    """Draw the checked pattern into out_dir.

    Returns {"chart", "symbols", "symbols_svg", "connectivity", "overlay", "view", "kind", "error", "note",
    "seconds"}: "chart" (same as "symbols") is the standard crochet symbol chart, always drawn when it can be;
    "connectivity" is the stitch-id diagram and "overlay" the symbols over it; "view" is the 3D image and is set
    only when kind is "3d" (the piece is clearly 3D; the 3D view is wrong for flat pieces). If the pattern
    breaks or has unreadable rows, only the rows before that are drawn, and "note" says so.
    """
    kind = _kind(report)
    v = report.verdict
    code, note = report.code, ""
    if v and v.kind in ("breaks", "unreadable") and v.row is not None:
        code = _code_before(report, v.row)
        note = (f"Drawn up to {_word_of(report)} {v.row - 1}, where the pattern "
                f"{'breaks' if v.kind == 'breaks' else 'could no longer be read'}.")
    if not _has_code(code):
        return {"chart": None, "view": None, "kind": kind, "error": "nothing to draw", "note": ""}
    result = _draw(code, out_dir, name, kind == "3d")
    return {**result, "kind": kind, "note": note}


def written_chart(report: PatternReport, out_dir, name: str = "written") -> dict:
    """Draw the pattern AS WRITTEN, mistakes included, from every row's current code (not just up to the break).

    Same result as chart(), plus "fallback": True when the engine refused the whole code and only the rows
    before the break were drawn ("note" says so). Files are <name>_symbols.png/.svg, <name>_connectivity.png,
    <name>_overlay.png (and <name>_3d.png for a clearly 3D piece).
    """
    kind = _kind(report)
    code = report.code
    if not _has_code(code):
        return {"chart": None, "view": None, "kind": kind, "error": "nothing to draw", "note": "", "fallback": False}
    unread = [r for r in report.rows if not r.synthetic and not r.code]
    note = (f"{len(unread)} row{'s' if len(unread) > 1 else ''} could not be read and "
            f"{'are' if len(unread) > 1 else 'is'} missing from the picture.") if unread else ""
    result = _draw(code, out_dir, name, kind == "3d")
    fallback = False
    v = report.verdict
    if result["error"] and not result["chart"] and not result["view"] and v and v.kind == "breaks" and v.row is not None:
        before = _code_before(report, v.row)
        if _has_code(before) and before != code:
            retry = _draw(before, out_dir, name, kind == "3d")
            if retry["chart"] or retry["view"]:
                result, fallback = retry, True
                note = (f"The engine could not draw the pattern as written ({_short(result['error'] or v.message)}); "
                        f"drawn up to {_word_of(report)} {v.row - 1}, where the pattern breaks.")
    return {**result, "kind": kind, "note": note, "fallback": fallback}


def _short(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def corrected_code(report: PatternReport) -> str | None:
    """The engine code of the pattern with the review's re-checked fixes applied, or None when it has none."""
    v, rv = report.verdict, report.review
    if not (v and v.fixes and rv and rv.fixed_report is not None):
        return None
    return rv.fixed_report.code or None


def corrected_chart(report: PatternReport, out_dir, name: str = "corrected") -> dict:
    """Draw the corrected pattern (corrected_code) like written_chart(); error "no fixes" when there are none."""
    kind = _kind(report)
    code = corrected_code(report)
    if code is None:
        return {"chart": None, "view": None, "kind": kind, "error": "no fixes", "note": ""}
    if not _has_code(code):
        return {"chart": None, "view": None, "kind": kind, "error": "nothing to draw", "note": ""}
    return {**_draw(code, out_dir, name, kind == "3d"), "kind": kind, "note": ""}


_ROW_LABEL = re.compile(r"^(?P<lead>\s*)(?P<word>rows?|rounds?|rnds?|r)(?P<sp>\s*)(?P<a>\d+)"
                        r"(?:(?P<dash>\s*[-–]\s*)(?P<b>\d+))?(?P<rest>\s*:.*)$", re.IGNORECASE | re.DOTALL)


def _loose(text: str) -> "re.Pattern[str]":
    """The text as a pattern that ignores differences in whitespace."""
    return re.compile(r"\s+".join(re.escape(w) for w in text.split()))


def _place(lines: list[str], original: str) -> int | None:
    """Index of the line that holds the written row `original`, or None."""
    wanted = _loose(original)
    for i, line in enumerate(lines):
        if wanted.search(line):
            return i
    return None


def _shift(line: str, by: int) -> str:
    """The row label at the start of a line moved on by `by` ("Round 5:" -> "Round 6:", "Rows 5-6:" too)."""
    m = _ROW_LABEL.match(line)
    if not m or not by:
        return line
    new = f"{m['lead']}{m['word']}{m['sp']}{int(m['a']) + by}"
    if m["b"]:
        new += f"{m['dash']}{int(m['b']) + by}"
    return new + m["rest"]


def _first_number(line: str) -> int | None:
    m = _ROW_LABEL.match(line)
    return int(m["a"]) if m else None


def _labelled_row(f) -> str:
    text = f.fixed_text.strip()
    return text if _ROW_LABEL.match(text) else f"Row {f.row}: {text}"


def _try_apply(base: str, fixes) -> list[str] | None:
    """The base text's lines with the fixes applied and marked, or None if a fixed row is not in the text."""
    lines = base.splitlines()
    marks: dict[int, str] = {}  # line index -> its mark
    for f in (f for f in fixes if not f.insert):
        at = _place(lines, f.original)
        if at is None:
            return None
        # replace only the row itself: a line may hold more than the row
        lines[at] = _loose(f.original).sub(lambda _m: f.fixed_text.strip(), lines[at], count=1)
        marks[at] = _mark(f)
    out = [ln + (f"  {marks[i]}" if i in marks else "") for i, ln in enumerate(lines)]
    added = False
    for f in sorted((f for f in fixes if f.insert), key=lambda f: f.row):
        at = next((i for i, ln in enumerate(out) if (_first_number(ln) or 0) >= f.row), len(out))
        for i in range(at, len(out)):
            out[i] = _shift(out[i], 1)
        out.insert(at, f"{_labelled_row(f)}  [added: a row seems to be missing here]")
        added = True
    if added:
        out.insert(0, "Note: a row was added, so the rows after it are numbered one higher than in the original.")
    return out


def corrected_pattern(report: PatternReport) -> str | None:
    """The written pattern with the review's re-checked fixes applied, each changed row marked; None if no fixes.

    Plain written text (no engine code): the pattern's own lines, the fixed rows reading as fixed and ending in
    "[suggested fix: ...]" (or "[works if the turning chain counts as a stitch; ...]"), an inserted row ending in
    "[added: ...]". A UK pattern is corrected in its US-terms conversion, since that is the text that was checked.
    """
    v = report.verdict
    if not (v and v.fixes):
        return None
    bases = [report.text]
    if report.terms and report.terms.kind == "UK":
        bases.append(to_us(report.text))
    merged = [merge_repeat_chains(b)[0] for b in bases]
    for base in bases + merged + [normalise_wording(b)[0] for b in merged]:
        lines = _try_apply(base, v.fixes)
        if lines is not None:
            return "\n".join(lines)
    return None

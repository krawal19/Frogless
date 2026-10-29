"""What the user gets besides the verdict: a clean written pattern and a picture of the piece.

clean_pattern(report) rewrites the CHECKED code as plain US crochet text, row by row, with the
stitch count at the end of each row. chart(report, out_dir) draws the assembled code: the crochet
chart for flat pieces, and the 3D view only for pieces the shape hints call clearly 3D (the 3D view
bends flat pieces, so it is not shown for them). Neither function shows engine code.
"""

import re
from pathlib import Path

from ..engine import get_engine
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
                    else "[the pattern breaks here; counted by AI, not modelled]")
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


def chart(report: PatternReport, out_dir) -> dict:
    """Draw the checked pattern into out_dir.

    Returns {"chart", "view", "kind", "error", "note"}: "chart" is the crochet chart (always drawn
    when it can be), "view" is the 3D image and is set only when kind is "3d" (the piece is clearly
    3D; the 3D view is wrong for flat pieces). If the pattern breaks or has unreadable rows, only
    the rows before that are drawn, and "note" says so.
    """
    kind = _kind(report)
    result = {"chart": None, "view": None, "kind": kind, "error": None, "note": ""}
    v = report.verdict
    code = report.code
    if v and v.kind in ("breaks", "unreadable") and v.row is not None:
        code = _code_before(report, v.row)
        result["note"] = (f"Drawn up to {_word_of(report)} {v.row - 1}, where the pattern "
                          f"{'breaks' if v.kind == 'breaks' else 'could no longer be read'}.")
    if not code.strip() or code.strip() == "ring.R0":
        result["error"] = "nothing to draw"
        result["note"] = ""
        return result
    try:
        drawn = get_engine().render(code, Path(out_dir))
    except Exception as e:  # missing Playwright or Chromium, or the page failing
        message = f"{type(e).__name__}: {e}"
        result["error"] = INSTALL_HINT if ("Playwright" in message or "Chromium" in message
                                           or isinstance(e, ImportError)) else message
        return result
    result["chart"] = drawn.get("chart_2d")
    if kind == "3d":
        result["view"] = drawn.get("model_3d")
    result["error"] = drawn.get("error") or (None if result["chart"] or result["view"] else drawn.get("chart_error"))
    return result

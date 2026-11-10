"""check_pattern(): the whole Frogless pipeline for one written pattern."""

import re
import time
from dataclasses import replace

from ..engine import Engine, get_engine
from ..models.client import ProviderError
from ..patterns.placement import says_other_side
from ..patterns.repeats import RepeatNote, merge_repeat_chains
from ..patterns.sizes import split_sizes
from ..patterns.structure import split_pieces
from ..patterns.terms import Terms, detect_terms, to_us
from ..patterns.wording import normalise_wording
from .faithful import check_faithfulness
from .ledger import count_ledger
from .reconcile import reconcile_counts
from .report import PatternReport
from .review import review_report
from .shape import POLYGON_KINDS, check_shape, meant_flat, starts_from_ring
from .translate import rule_rows, translate_flagged
from .verdict import decide_verdict


def check_pattern(text: str, *, engine: Engine | None = None, use_model: bool = True,
                  faithfulness: bool = True, count_retry: bool = True, ledger: bool = True,
                  terms: str = "auto", review: bool = True, terms_text: str | None = None) -> PatternReport:
    """Translate, verify and judge a pattern. use_model=False makes no model calls.

    ledger: count the rows the engine cannot model (read by the model, added up by our code) instead of
    giving up on them; part of the model steps, so it needs use_model.
    review: when the pattern does not simply work, ask Alice ("it is right as written") and Bob ("it has a mistake")
    and let code referee them; may suggest re-checked fixes. Part of the model steps, so it needs use_model.
    terms: "auto" detects US or UK stitch names; "US" or "UK" chooses. UK is converted to US first.
    terms_text: the text to detect the terms from when it is more than `text` (the whole pattern, for one piece of it).
    """
    started = time.perf_counter()
    timings = dict.fromkeys(("translate", "faithfulness", "reconcile", "ledger", "engine_verdict", "review", "shape"), 0.0)

    def lap(stage: str, since: float) -> float:
        now = time.perf_counter()
        timings[stage] = round(timings.get(stage, 0.0) + now - since, 2)
        return now

    original = text
    found, note = _read_terms(terms_text or text, terms)
    if found.kind == "UK":
        text = to_us(text)
    text, repeat_notes = merge_repeat_chains(text)  # a chain written twice across a repeat's end is one chain
    text, wording_notes = normalise_wording(text)  # wordings the rules translator misreads, written out plainly
    engine = engine or get_engine()
    t = time.perf_counter()
    rows, cost = rule_rows(engine, text), 0.0
    if use_model:
        rows, spent = translate_flagged(engine, text, rows)
        cost += spent
        t = lap("translate", t)
        if faithfulness:
            rows, spent = check_faithfulness(engine, text, rows)
            cost += spent
            t = lap("faithfulness", t)
        if count_retry:
            rows, spent = reconcile_counts(engine, text, rows)
            cost += spent
            t = lap("reconcile", t)
    else:
        t = lap("translate", t)
    rows = [replace(r, synthetic=True, code="") if engine.is_marker(r.source) else r for r in rows]
    rows = [replace(r, synthetic=True) if r.code and engine.is_directive(r.code) else r for r in rows]
    rows = _with_repeat_notes(rows, repeat_notes)
    t = time.perf_counter()
    if use_model and ledger:
        rows, spent = count_ledger(engine, text, rows)
        cost += spent
        t = lap("ledger", t)

    report = PatternReport(text=original, rows=rows, cost_usd=cost, terms=found)
    if note:
        report.notes.append(note)
    report.notes.extend(wording_notes)
    report.check = engine.check(report.code) if report.code else None
    report.verdict, report.stated, report.computed = decide_verdict(engine, text, rows, report.check)
    t = lap("engine_verdict", t)
    if use_model and review:
        try:
            report.cost_usd += review_report(engine, text, report)
        except ProviderError as e:  # keep the verdict already computed
            report.notes.append(_review_failed_note(e))
        t = lap("review", t)
    if report.check:  # hints about the finished piece; they never change the verdict
        report.shape = check_shape(report.check.rows, from_ring=starts_from_ring(text), flat=meant_flat(text),
                                   oval=any(says_other_side(line) for line in text.splitlines()))
        v = report.verdict
        if v and v.kind == "breaks" and v.row is not None:  # corners of a round that breaks (or after it) are not to be trusted
            report.shape = [f for f in report.shape
                            if not (f.kind in POLYGON_KINDS and f.row is not None and f.row >= v.row)]
    lap("shape", t)
    timings["total"] = round(time.perf_counter() - started, 2)
    report.timings = timings
    return report


_LABEL = re.compile(r"^\s*(?:rows?|rnds?|rounds?|r)\s*[\d\s\-–,&and]+:\s*", re.IGNORECASE)


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _key(line: str) -> str:
    """Part of a line, letters and digits only, past its label. The translator rewrites the labels and the
    way repeats are multiplied ("x3" becomes "3 times"), but not the words before that."""
    return _plain(_LABEL.sub("", line, count=1))


def _review_failed_note(error: ProviderError) -> str:
    """The note for a review step that could not finish."""
    why = "the model took too long" if "timeout" in str(error).lower() else "the model call failed"
    return f"The review step couldn't finish ({why}), so no fix was looked for."


def _with_repeat_notes(rows, notes: list[RepeatNote]):
    """Show the repeat-boundary merges as interpreted readings on the rows they changed."""
    for note in notes:
        wanted = _key(note.start)
        for i, row in enumerate(rows):
            if row.synthetic or not row.code or not wanted or wanted not in _plain(row.source):
                continue
            reading = f"{row.reading}; {note.reading}" if row.reading else note.reading
            rows[i] = replace(row, reading=reading, note=f"read as {reading}" + (f" ({row.why})" if row.why else ""))
    return rows


def check_pattern_pieces(text: str, **kw) -> list[tuple[str, PatternReport]]:
    """check_pattern() for each piece of a pattern, each on its own (its rows count from 1); one (label, report) for a
    one-piece pattern. The label is the piece's header ("Piece N" if it has none). The text is first put in order
    (structure.py: one round per line, labels with colons, prose kept as notes), also for a single piece."""
    pieces = [p for p in split_pieces(text) if p.text.strip()]
    if not pieces:  # nothing but prose: the checker says what it makes of that
        return [("Piece 1", check_pattern(text, **kw))]
    out = []
    for piece in pieces:
        report = check_pattern(piece.text, terms_text=text, **kw)
        report.notes.extend(piece.readings)
        report.prose = list(piece.notes)
        out.append((piece.label, report))
    return out


def check_pattern_sizes(text: str, **kw) -> list[tuple[str, PatternReport]]:
    """check_pattern() for each piece of each size of a pattern; one (label, report) for one size of one piece.
    The label is the size's, or the piece's header, or "size: piece" when the pattern has both."""
    sizes = split_sizes(text)
    out = []
    for size_label, part in sizes:
        pieces = check_pattern_pieces(part, **kw)
        for piece_label, report in pieces:
            label = size_label if len(pieces) == 1 else piece_label if len(sizes) == 1 else f"{size_label}: {piece_label}"
            out.append((label, report))
    return out


def _read_terms(text: str, terms: str) -> tuple[Terms, str]:
    """The terms to check with and the note to tell the user ("" if none)."""
    choice = terms.upper() if terms.lower() != "auto" else "AUTO"
    if choice in ("US", "UK"):
        found = Terms(choice, ["chosen by you"])
    elif choice == "AUTO":
        found = detect_terms(text)
    else:
        raise ValueError(f"terms must be auto, US or UK, not {terms!r}")
    if found.kind == "UK":
        why = f" ({', '.join(found.evidence)})" if choice == "AUTO" and found.evidence else ""
        return found, f"Read as UK terms{why}; converted to US."
    if found.kind == "unknown" and found.ambiguous:
        return found, ("The pattern doesn't say US or UK and uses only ch/dc/tr, so it was checked as US terms. "
                       "If it's UK, check again with UK terms.")
    return found, ""

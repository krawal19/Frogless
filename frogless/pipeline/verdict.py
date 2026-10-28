"""Step 3: decide what to tell the user (task 9).

Inputs: the pattern's rows (RowResult, with code and source text) and the engine's check of
the assembled code. Output: a Verdict plus the stated and computed stitch counts per row.

Row mapping. A pattern row number is the engine's row index: with a magic ring Round 1 is
row 1, with a foundation chain the chain is row 0 and Row 1 follows. Every non-synthetic
RowResult that has code makes exactly one engine row (a range such as "Rows 2-8" has already
been expanded to one RowResult per row, all sharing the same source text, so each gets its own
number and the same stated count). Synthetic rows (the magic ring) make none. The i-th such
RowResult is paired with the i-th engine RowInfo; if the numbers do not line up, or the engine
reports a syntax error (no rows), the rows are paired by checking growing prefixes of the code
instead, which also finds the row that does not parse. A written row with no code still takes
its number (its position among the written rows), so numbers stay true to the pattern.

Stated vs computed. A row that states its count is checked against the count the engine makes
for that row, whatever the engine itself says: an extra stitch shows in the engine only on the
NEXT row (or never, in the last row), but the row's own stated count exposes it at once. The
pattern breaks at the EARLIEST row where the engine errors or the stated count does not fit.

Counting readings. Designers differ, so a stated count may fit under more than one reading:
- bare counts may or may not include chain spaces (gate.row_counts accepts both, per row);
- on hdc and taller rows the turning chain may count as the row's first stitch or not. That is
  a whole-pattern habit, so two readings are tried, "turning chain not counted" and "turning
  chain counted as a stitch", and the one that fits more of the pattern's stated counts wins.
  If both fit equally often but disagree about where the pattern breaks, the verdict is
  "ambiguous" and lists both readings.
"""

from dataclasses import dataclass

from ..engine import CheckResult, Engine, RowInfo
from ..patterns.stated import StatedCount, stated_count
from .gate import row_counts
from .report import RowResult, Verdict

PLAIN = "turning chain not counted as a stitch"
TURN_COUNTS = "turning chain counted as a stitch"
READINGS = (PLAIN, TURN_COUNTS)
_TALL = ("hdc", "dc", "tr", "dtr", "ttr")  # stitches whose turning chain may count as a stitch


@dataclass
class _Row:
    number: int  # the pattern's row number
    result: RowResult
    info: RowInfo | None = None  # the engine's row, None when the row has no code
    stated: StatedCount | None = None  # None: states no count (or several sizes)


@dataclass
class _Outcome:
    reading: str
    fits: int  # stated counts that fit this reading
    row: int | None  # earliest row where the pattern breaks under this reading
    message: str
    computed: dict[int, int]


# ---- mapping rows to engine rows ----
def _infos_by_prefix(engine: Engine, rows: list[RowResult]) -> tuple[dict[int, RowInfo], int | None]:
    """Pair rows with engine rows by checking growing prefixes of the code.

    Returns ({position in rows: RowInfo}, position of the first row whose code does not parse).
    """
    infos: dict[int, RowInfo] = {}
    code: list[str] = []
    seen = 0
    for pos, row in enumerate(rows):
        if not row.code:
            continue
        code.append(row.code)
        res = engine.check("\n".join(code))
        if res.error and res.error.kind == "invalid":
            return infos, pos
        if not row.synthetic and len(res.rows) > seen:
            infos[pos] = res.rows[seen]
        seen = len(res.rows)
    return infos, None


def _map_rows(engine: Engine, rows: list[RowResult], result: CheckResult | None
              ) -> tuple[list[_Row], int | None]:
    """One _Row per written (non-synthetic) row, numbered, with its engine row and stated count.

    Also returns the number of the row whose code the engine cannot parse, if it said so.
    """
    coded = [p for p, r in enumerate(rows) if r.code and not r.synthetic]
    invalid = bool(result and result.error and result.error.kind == "invalid")
    culprit = None
    if result is not None and not invalid and len(result.rows) == len(coded):
        infos = dict(zip(coded, result.rows))
    else:
        infos, culprit = _infos_by_prefix(engine, rows) if any(r.code for r in rows) else ({}, None)

    written = [p for p, r in enumerate(rows) if not r.synthetic]
    first = next((n for n, p in enumerate(written) if p in infos), None)
    offset = infos[written[first]].index - first if first is not None else 1
    mapped, culprit_number = [], None
    for n, p in enumerate(written):
        stated = None if rows[p].synthetic else stated_count(rows[p].source)
        if stated is not None and stated.multi_size:
            stated = None
        mapped.append(_Row(n + offset, rows[p], infos.get(p), stated))
        if p == culprit:
            culprit_number = n + offset
    return mapped, culprit_number


# ---- counts under a reading ----
def _turned_tall(info: RowInfo) -> bool:
    """A row of hdc or taller stitches that has chains (so, possibly, a counting turning chain)."""
    t = info.stitch_types
    return info.index >= 1 and t.get("ch", 0) >= 1 and any(n and k.startswith(_TALL) for k, n in t.items())


def _counts(row: _Row, reading: str) -> list[int]:
    """Counts this row's stated total may mean, most likely first."""
    info, stated = row.info, row.stated
    kind = stated.stitch if stated else None
    counts = row_counts(info, kind)
    if reading == TURN_COUNTS and _turned_tall(info) and (kind is None or kind.startswith(_TALL)):
        return [counts[0] + 1]  # the turning chain is the row's first stitch; chain spaces are not added
    return counts


def _says(stated: StatedCount) -> str:
    return f"{stated.count} {stated.stitch}" if stated.stitch else f"{stated.count}"


def _evaluate(reading: str, rows: list[_Row], result: CheckResult | None, error_row: int | None,
              limit: int | None) -> _Outcome:
    """Where the pattern first breaks under one reading, looking only at rows before `limit`."""
    computed, fits, misfit = {}, 0, None
    for row in rows:
        if row.info is None or row.info.index < 1:  # no code, or the foundation chain
            continue
        counts = _counts(row, reading)
        computed[row.number] = counts[0]
        if row.stated is None:
            continue
        if row.stated.count in counts:
            fits += 1
            computed[row.number] = row.stated.count
        elif misfit is None and (limit is None or row.number < limit):
            misfit = (row, counts[0])
    engine_ok = error_row is None or (limit is not None and error_row >= limit)
    if misfit and (engine_ok or misfit[0].number <= error_row):
        row, made = misfit
        message = f"Row {row.number}: pattern says {_says(row.stated)}, the instructions make {made}"
        if not engine_ok and error_row == row.number:
            message += f" ({result.error.message})"
        return _Outcome(reading, fits, row.number, message, computed)
    if not engine_ok:
        return _Outcome(reading, fits, error_row, f"Row {error_row}: {result.error.message}", computed)
    return _Outcome(reading, fits, None, "", computed)


def _names(numbers: list[int]) -> str:
    return ("row " if len(numbers) == 1 else "rows ") + ", ".join(str(n) for n in numbers)


def _stated_of(rows: list[_Row]) -> dict[int, int]:
    return {r.number: r.stated.count for r in rows if r.stated is not None}


def _describe(o: _Outcome) -> str:
    return f"{o.reading}: " + (o.message if o.row is not None else "works")


def decide_verdict(engine: Engine, text: str, rows: list[RowResult],
                   result: CheckResult | None) -> tuple[Verdict, dict[int, int], dict[int, int]]:
    """Returns (verdict, stated counts, computed counts) keyed by row number."""
    if not any(r.code for r in rows) or result is None:
        return Verdict("unreadable", "nothing to check"), {}, {}
    mapped, culprit = _map_rows(engine, rows, result)
    stated = _stated_of(mapped)
    by_index = {r.info.index: r.number for r in mapped if r.info}

    error_row = None  # the engine's complaint, as a pattern row number
    if result.error:
        error_row = culprit if culprit is not None else by_index.get(result.error.row, result.error.row)
        if error_row is None:
            error_row = 0
    unread = [r for r in mapped if not r.result.code]
    limit = unread[0].number if unread else None  # rows from here on cannot be trusted to check

    outcomes = [_evaluate(rd, mapped, result, error_row, limit) for rd in READINGS]
    plain, turn = outcomes
    best = turn if turn.fits > plain.fits else plain  # the reading that fits more of the stated counts
    reading = best.reading if plain.fits != turn.fits else ""  # said only when the choice mattered
    note = " (the turning chain counts as a stitch here)" if reading == TURN_COUNTS else ""

    if plain.fits == turn.fits and plain.row != turn.row:  # equally good readings, different answers
        broken = [o.row for o in outcomes if o.row is not None]
        what = "the stated counts fit two ways of counting, which disagree on where this pattern breaks"
        return (Verdict("ambiguous", what, row=min(broken), readings=[_describe(o) for o in outcomes]),
                stated, best.computed)
    if best.row is not None:
        return Verdict("breaks", best.message + note, row=best.row, reading=reading), stated, best.computed
    if unread:
        what = f"could not read {len(unread)} row(s), first: {unread[0].result.source[:60]}"
        return Verdict("unreadable", what), stated, best.computed

    unverified = [r.number for r in mapped if r.result.origin == "model" and r.result.faithful is not True]
    if unverified:
        what = (f"stitch counts check out{note}, but {_names(unverified)} "
                f"{'was' if len(unverified) == 1 else 'were'} translated by the model and not confirmed")
        return Verdict("works_unverified", what, rows=unverified, reading=reading), stated, best.computed
    return Verdict("works", f"stitch counts and structure check out{note}", reading=reading), stated, best.computed

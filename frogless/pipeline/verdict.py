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

Counting conventions (the unwritten ones a crocheter assumes; the pattern's own words win):
- a turning chain does NOT count as a stitch, whatever the stitch height. It counts only when the
  pattern says so ("ch 3 (counts as first dc)"), or, as a fallback, when the stated counts fit only
  that reading; the verdict then says it works only if the turning chain counts. Wording is weaker evidence
  (patterns/stated.py): "ch 3, dc in next st" or a last stitch worked into the turning chain suggests it counts,
  "dc in first st" that it does not; this settles a tie, never overrules the counts or a statement;
- a bare stated count ("(24)") is the stitches plus every chain except the turning chain: corner chains,
  mesh chains and chains inside a row count. If a row's count fits only with all chains left out the pattern
  still passes, with a note, never silently.
When no pattern text settles the turning chain, the two readings are tried and the one that fits
more of the stated counts wins, "not counted" on a tie. If they fit equally often but disagree
about where the pattern breaks, the verdict is "ambiguous" and lists both readings.
"""

import re
from dataclasses import dataclass, field

from ..engine import CheckResult, Engine, RowInfo
from ..patterns.stated import StatedCount, stated_count, turning_chain_hint, turning_chain_stated
from .gate import row_counts
from .report import Alternative, Interpreted, RowResult, Verdict

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
    said: int | None = None  # the stated count at the breaking row, when a stated count is what failed
    made: int | None = None  # the count the instructions make there
    chain_rows: list[int] = field(default_factory=list)  # rows whose bare count fits only with all chains left out


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
_ROW_LABEL = re.compile(r"^\s*rows?\b", re.IGNORECASE)
_SKIPPED = (("dtr", 5), ("ttr", 6), ("tr", 4), ("hdc", 2), ("dc", 3))  # chains skipped for "in Nth ch from hook"


def _turned_tall(info: RowInfo, foundation: int | None) -> bool:
    """A row of hdc or taller stitches that could hold a counting turning chain: it has chains
    (the turning chain), or it is row 1 worked into a foundation chain of `foundation` chains
    (which allows for the skipped chains and no more: if the row already holds one stitch more,
    the code writes the counted chain as a stitch and there is nothing to add)."""
    tall = {k: n for k, n in info.stitch_types.items() if n and k.startswith(_TALL)}
    if info.index < 1 or not tall:
        return False
    if info.index == 1 and foundation is not None:
        skip = next(n for name, n in _SKIPPED if max(tall, key=tall.get).startswith(name))
        return sum(tall.values()) == foundation - skip
    return info.stitch_types.get("ch", 0) >= 1


def _flat(row: _Row) -> bool:
    """A turned row ("Row 3: ..."), as opposed to a round."""
    return bool(_ROW_LABEL.match(row.result.source))


def _counts(row: _Row, reading: str, foundation: int | None, said: bool) -> list[int]:
    """Counts this row's stated total may mean, most likely first. A bare count includes the chains
    except the turning chain; leaving all chains out is the fallback, and so comes second."""
    info, stated = row.info, row.stated
    kind = stated.stitch if stated else None
    counts = row_counts(info, kind)
    # Where the pattern itself says "ch 3 (counts as dc)" a round's chain is already written as a stitch, and
    # its corner chains are not a turning chain, so only a turned row may still add the counted chain.
    if (reading == TURN_COUNTS and (_flat(row) or not said) and _turned_tall(info, foundation)
            and (kind is None or kind.startswith(_TALL))):
        return [counts[0] + 1]  # the turning chain is the row's first stitch; other chains already count
    return counts


def _says(stated: StatedCount) -> str:
    return f"{stated.count} {stated.stitch}" if stated.stitch else f"{stated.count}"


def _evaluate(reading: str, rows: list[_Row], result: CheckResult | None, error_row: int | None,
              limit: int | None, said: bool = False) -> _Outcome:
    """Where the pattern first breaks under one reading, looking only at rows before `limit`."""
    computed, fits, misfit, chain_rows = {}, 0, None, []
    foundation = next((r.info.stitch_count for r in rows if r.info is not None and r.info.index == 0), None)
    for row in rows:
        if row.info is None or row.info.index < 1:  # no code, or the foundation chain
            continue
        counts = _counts(row, reading, foundation, said)
        computed[row.number] = counts[0]
        if row.stated is None:
            continue
        if row.stated.count in counts:
            fits += 1
            computed[row.number] = row.stated.count
            if row.stated.count != counts[0]:
                chain_rows.append(row.number)  # fits only with all chains left out
        elif misfit is None and (limit is None or row.number < limit):
            misfit = (row, counts[0])
    engine_ok = error_row is None or (limit is not None and error_row >= limit)
    if misfit and (engine_ok or misfit[0].number <= error_row):
        row, made = misfit
        message = f"Row {row.number}: pattern says {_says(row.stated)}, the instructions make {made}"
        if not engine_ok and error_row == row.number:
            message += f" ({result.error.message})"
        return _Outcome(reading, fits, row.number, message, computed, row.stated.count, made, chain_rows)
    if not engine_ok:
        return _Outcome(reading, fits, error_row, f"Row {error_row}: {result.error.message}", computed,
                        chain_rows=chain_rows)
    return _Outcome(reading, fits, None, "", computed, chain_rows=chain_rows)


def _turning_chain_stated(rows: list[_Row]) -> bool | None:
    """What the pattern itself says about its turning chain: True (counts as a stitch), False (does
    not) or None (silent, or it says both)."""
    return turning_chain_stated(r.result.source for r in rows if not r.result.synthetic)


def _turning_chain_hint(rows: list[_Row]) -> bool | None:
    """What the wording of the rows suggests when the pattern states nothing ("ch 3, dc in next st" or a last stitch worked
    into the turning chain: it counts; "dc in first st": it does not). Weaker than a statement: it only settles a tie
    between the two readings, and the stitch counts can still overrule it."""
    return turning_chain_hint(r.result.source for r in rows if not r.result.synthetic)


def _names(numbers: list[int]) -> str:
    return ("row " if len(numbers) == 1 else "rows ") + ", ".join(str(n) for n in numbers)


def _stated_of(rows: list[_Row]) -> dict[int, int]:
    return {r.number: r.stated.count for r in rows if r.stated is not None}


def _made_by_ledger(counted: list[_Row]) -> dict[int, int]:
    """Row number -> the count the AI's reading of the row makes (stitch rows only)."""
    return {r.number: r.result.ledger_makes for r in counted if r.result.ledger_uses or r.result.ledger_makes}


def _describe(o: _Outcome) -> str:
    return f"{o.reading}: " + (o.message if o.row is not None else "works")


def decide_verdict(engine: Engine, text: str, rows: list[RowResult],
                   result: CheckResult | None) -> tuple[Verdict, dict[int, int], dict[int, int]]:
    """Returns (verdict, stated counts, computed counts) keyed by row number."""
    if not any(r.code and not r.synthetic for r in rows) or result is None:  # nothing written was read
        return Verdict("unreadable", "nothing to check"), {}, {}
    mapped, culprit = _map_rows(engine, rows, result)
    stated = _stated_of(mapped)
    by_index = {r.info.index: r.number for r in mapped if r.info}

    error_row = None  # the engine's complaint, as a pattern row number
    if result.error:
        error_row = culprit if culprit is not None else by_index.get(result.error.row, result.error.row)
        if error_row is None:
            error_row = 0
    no_code = [r for r in mapped if not r.result.code]
    limit = no_code[0].number if no_code else None  # rows from here on cannot be trusted to check
    counted = [r for r in no_code if r.result.ledger_ok is not None]  # read by AI, checked by count only
    unread = [r for r in no_code if r.result.ledger_ok is None]

    stated_by_pattern = _turning_chain_stated(mapped)
    hint = _turning_chain_hint(mapped) if stated_by_pattern is None else None
    outcomes = [_evaluate(rd, mapped, result, error_row, limit, bool(stated_by_pattern)) for rd in READINGS]
    plain, turn = outcomes
    reading = ""  # said only when the pattern's wording did not settle it and the stated counts needed the fallback
    if stated_by_pattern is not None:  # the pattern's own words win, unless the numbers contradict them outright
        best = turn if stated_by_pattern and turn.fits >= plain.fits else plain
    else:
        best = turn if turn.fits > plain.fits else plain  # not counted, unless the counts fit only the other way
        if hint is not None and turn.fits == plain.fits and turn.row != plain.row:
            best = turn if hint else plain  # the wording settles a tie that would otherwise be ambiguous
        reading = TURN_COUNTS if best is turn else ""
    note = " (the turning chain counts as a stitch here)" if reading == TURN_COUNTS else ""
    chains = best.row is None and bool(best.chain_rows)

    foundation = next((r.info.stitch_count for r in mapped if r.info is not None and r.info.index == 0), None)
    if (stated_by_pattern is None and hint is None and plain.fits == turn.fits and plain.row != turn.row  # equally good, different answers
            and _turn_is_clear(mapped, foundation, None)):  # ... and counting the chain is not just a stray row's need
        broken = [o.row for o in outcomes if o.row is not None]
        what = "the stated counts fit two ways of counting, which disagree on where this pattern breaks"
        return (Verdict("ambiguous", what, row=min(broken), readings=[_describe(o) for o in outcomes],
                         alternatives=[Alternative(o.reading, o.row, o.said, o.made) for o in outcomes]),
                stated, best.computed)
    if best.row is not None:
        return Verdict("breaks", best.message + note, row=best.row, reading=reading), stated, best.computed
    ledger_break = next((r for r in counted if not r.result.ledger_ok), None)
    if ledger_break is not None:  # counted by AI: the row's own words do not add up
        return (Verdict("breaks", ledger_break.result.ledger_note, row=ledger_break.number, ledger=True),
                stated, best.computed | _made_by_ledger(counted))
    best.computed.update(_made_by_ledger(counted))
    unverified = [r.number for r in mapped if r.result.origin == "model" and r.result.faithful is not True
                  and r.result.ledger_ok is None]
    if unread:
        what = f"could not read {len(unread)} row(s), first: {unread[0].result.source[:60]}"
        return Verdict("unreadable", what, row=unread[0].number,
                       rows=[n for n in unverified if n < unread[0].number]), stated, best.computed

    interpreted = [Interpreted(r.number, r.result.source, r.result.reading, r.result.why)
                   for r in mapped if r.result.reading and r.result.faithful is not False and r.result.code]
    if unverified:
        what = (f"stitch counts check out{note}, but {_names(unverified)} "
                f"{'was' if len(unverified) == 1 else 'were'} translated by the model and not confirmed")
        return (Verdict("works_unverified", what, rows=unverified, reading=reading, interpreted=interpreted,
                        chains_left_out=chains), stated, best.computed)
    if counted:
        numbers = [r.number for r in counted if r.result.ledger_uses or r.result.ledger_makes]
        what = f"stitch counts check out{note}; {_names(numbers)} checked by count only"
        return (Verdict("works_counts_only", what, counted=numbers, rows=unverified, reading=reading,
                        interpreted=interpreted, chains_left_out=chains), stated, best.computed)
    return (Verdict("works", f"stitch counts and structure check out{note}", reading=reading,
                    interpreted=interpreted, chains_left_out=chains), stated, best.computed)


@dataclass
class CountingFit:
    """A row that misses its stated count the plain way but fits under another way of counting."""

    readings: list[str]  # the counting readings (not PLAIN) under which its stated count fits
    said: int  # the count the row states
    made: int  # the count the instructions make, counting plainly


def _turn_is_clear(mapped: list[_Row], foundation: int | None, said: bool | None) -> bool:
    """Whether the turning chain counting as a stitch is clear enough to be worth mentioning: the pattern says so
    itself, or at least half of the rows that state a count fit only that way (a tie is as good as the default, so it
    cannot be called the default). Otherwise the default (not counted) stands."""
    if said is not None:
        return said
    stated = [r for r in mapped if r.info is not None and r.info.index >= 1 and r.stated is not None]
    needs = [r for r in stated if r.stated.count not in _counts(r, PLAIN, foundation, False)
             and r.stated.count in _counts(r, TURN_COUNTS, foundation, False)]
    return bool(needs) and 2 * len(needs) >= len(stated)


def counting_fits(engine: Engine, rows: list[RowResult], result: CheckResult | None) -> dict[int, CountingFit]:
    """Row number -> CountingFit, for every row that states a count, misses it counted plainly and fits it under
    another accepted reading (turning chain counted as a stitch). Rows that fit plainly, or under no reading, are left out.
    Empty unless that reading is clear: the pattern says "counts as", or most rows with a stated count need it."""
    if result is None or not any(r.code for r in rows):
        return {}
    mapped, _ = _map_rows(engine, rows, result)
    foundation = next((r.info.stitch_count for r in mapped if r.info is not None and r.info.index == 0), None)
    stated_by_pattern = _turning_chain_stated(mapped)
    if not _turn_is_clear(mapped, foundation, stated_by_pattern if stated_by_pattern is not None
                          else (True if _turning_chain_hint(mapped) else None)):
        return {}
    said = bool(stated_by_pattern)
    out = {}
    for row in mapped:
        if row.info is None or row.info.index < 1 or row.stated is None:
            continue
        counts = {rd: _counts(row, rd, foundation, said) for rd in READINGS}
        if row.stated.count in counts[PLAIN]:
            continue
        fits = [rd for rd in READINGS if rd != PLAIN and row.stated.count in counts[rd]]
        if fits:
            out[row.number] = CountingFit(fits, row.stated.count, counts[PLAIN][0])
    return out

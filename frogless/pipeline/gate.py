"""Stated-count gate: send a line to the model when its rule translation misses its own count.

Many pattern lines state their stitch count, e.g. "Row 2: sc across, ch 1, turn = 10".
The rules translator sometimes reads such a line wrongly without flagging it. The gate
re-computes the count from the translated code (using the engine's checker) and, if it
differs from the stated count, marks the line parsed=False so the model translates it.
Plain code, no model calls.

How the count is computed: check the code of every still-parsed line up to and
including this one and take the last row's stitch count. A stated stitch type ("24 dc")
counts only that type. A bare count ("(24)") matches either all stitches without chains
or with them, since designers differ on counting chain spaces. Multi-size counts are skipped.

After a flagged line (unparsed by the translator, or flagged here) the code has a hole:
the flagged line contributes nothing, so later checks may fail or count wrongly through
no fault of the line being gated. The gate keeps going but, once there is a hole, it
flags a line only for a count mismatch, never for a failed check (that line is kept).
Counts computed past a hole can still be off; that costs at most an extra flag (the line
goes to the model, which sees the whole pattern), and it still catches wrong lines such
as "sc across" read as one stitch.
"""

from dataclasses import replace

from ..engine import Engine, TranslateResult
from ..patterns.stated import stated_count


def row_counts(row, stitch: str | None) -> list[int]:
    """Counts a stated total may mean for a checked row, most likely first.

    A typed count ("24 dc") is only that type. A bare count ("(24)") is all stitches;
    designers differ on whether chains (corner spaces) are included, so both readings
    are accepted.
    """
    types = row.stitch_types
    if stitch is not None:  # "sc" also covers variants the engine names e.g. sc2inc, sc2tog
        return [sum(n for name, n in types.items() if name.startswith(stitch))]
    if set(types) <= {"ch"}:
        return [row.stitch_count]
    return [row.stitch_count - types.get("ch", 0), row.stitch_count]


def gate_translation(engine: Engine, result: TranslateResult, original_text: str = "") -> TranslateResult:
    """Return a copy of result where lines that miss their stated count are parsed=False.

    original_text is accepted for callers that have it; the lines' own source is used.
    """
    kept: list[str] = []  # code of lines still trusted
    lines = []
    hole = False  # a line before this one has no code
    for line in result.lines:
        if not line.parsed or not line.code:
            lines.append(line)
            hole = hole or (not line.parsed and not line.synthetic)
            continue
        stated = None if line.synthetic else stated_count(line.source)
        if stated is None or stated.multi_size:
            kept.append(line.code)
            lines.append(line)
            continue
        check = engine.check("\n".join(kept + [line.code]))
        reason = ""
        if not check.ok:
            if hole:
                kept.append(line.code)
                lines.append(line)
                continue
            reason = f"stated count {stated.count}, translation does not check: {check.error.message[:80]}"
        elif check.rows:
            made = row_counts(check.rows[-1], stated.stitch)
            if stated.count not in made:
                with_ch = f" ({made[1]} counting chains)" if len(made) > 1 and made[1] != made[0] else ""
                reason = f"stated count {stated.count}, translation makes {made[0]}{with_ch}"
        if reason:
            hole = True
            lines.append(replace(line, code="", parsed=False, reason=reason))
        else:
            kept.append(line.code)
            lines.append(line)
    return TranslateResult(lines=lines)


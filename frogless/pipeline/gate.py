"""Stated-count gate: send a line to the model when its rule translation misses its own count.

Many pattern lines state their stitch count, e.g. "Row 2: sc across, ch 1, turn = 10".
The rules translator sometimes reads such a line wrongly without flagging it. The gate
re-computes the count from the translated code (using the engine's checker) and, if it
differs from the stated count, marks the line parsed=False so the model translates it.
Plain code, no model calls. It also flags a line whose code leaves out an item the text names
(omissions.py), whatever the count says.

How the count is computed: check the code of every still-parsed line up to and
including this one and take the last row's stitch count. A stated stitch type ("24 dc")
counts only that type. A bare count ("(24)") is the stitches plus every chain except the turning chain
at the start of the row (corner and mesh chains count); it also matches the count with all chains
left out, since designers differ. Multi-size counts are skipped.

After a flagged line (unparsed by the translator, or flagged here) the code has a hole:
the flagged line contributes nothing, so later checks may fail or count wrongly through
no fault of the line being gated. The gate keeps going but, once there is a hole, it
flags a line only for a count mismatch, never for a failed check (that line is kept).
Counts computed past a hole can still be off; that costs at most an extra flag (the line
goes to the model, which sees the whole pattern), and it still catches wrong lines such
as "sc across" read as one stitch.
"""

from dataclasses import replace

from ..engine import Engine, TranslateResult, stitch_family
from ..patterns.stated import stated_count
from .omissions import left_out_item


def _is_type(name: str, stitch: str) -> bool:
    """Whether the engine's stitch name is the stated type. The engine names special stitches its own way
    ("dc5pc", "a dc bobble of 3 stitches", "an hdc puff of 3 stitches"), so those are found by their word."""
    if stitch == "pc":
        return name.endswith("pc")
    if stitch in ("bobble", "puff"):
        return stitch in name
    return name.startswith(stitch)


def leading_chains(row) -> int:
    """The length of the turning chain at the start of a row or round: the run of chains before its first
    other stitch (slip stitches before it, such as a join into a corner space, are passed over). Without the
    stitch graph the chains of the row cannot be placed, so all of them are taken as the turning chain."""
    stitches = sorted(getattr(row, "stitches", None) or [], key=lambda s: s.position)
    if not stitches:
        return row.stitch_types.get("ch", 0)
    run = 0
    for s in stitches:
        if s.kind.startswith("ss") and run == 0:
            continue
        if s.kind != "ch":
            break
        run += 1
    return run


# Chains that are exactly the turning chain of a foundation row's first stitch: the first stitch goes into the
# (min+1)th..(max+1)th chain from the hook. Any chains skipped beyond that are extra, not a turning chain.
_TURNING_HEIGHT = {"sc": (1, 1), "hdc": (2, 2), "dc": (2, 3), "tr": (4, 4), "dtr": (5, 5), "ttr": (6, 6)}


def foundation_space(row) -> int:
    """Chains a foundation row counts for the extra chains it skips before its first stitch.

    Only the exact turning-chain height is the turning chain (sc 1, hdc 2, dc 2 or 3, tr 4). Chains skipped beyond
    that form a space, and a space counts like the ch-1 gap of a mesh repeat ("ch 1, skip 1"): two skipped chains
    count one chain. "Ch 94, sc in 4th ch from hook, [ch 1, skip 1 ch, sc in next ch] across": 3 skipped, 1 turning,
    2 extra, so 1 more chain, 46 sc + 46 chains = 92. Rows that are not worked into a foundation chain have none.
    """
    if getattr(row, "index", 0) != 1:
        return 0
    for s in sorted(getattr(row, "stitches", None) or [], key=lambda s: s.position):
        family = stitch_family(s.kind)
        if family in ("ch", "ss") or not s.into:
            continue
        if family not in _TURNING_HEIGHT or s.into[0][0] != 0:
            return 0
        extra = s.into[0][1] - _TURNING_HEIGHT[family][1]
        return max(extra, 0) // 2
    return 0


def row_counts(row, stitch: str | None) -> list[int]:
    """Counts a stated total may mean for a checked row, most likely first.

    A typed count ("24 dc") is only that type. A bare count ("(24)") is the stitches plus every chain
    except the turning chain (the chain that starts the row or round): corner chains, mesh chains and
    chains inside the row count. Designers differ, so the fallback, second, leaves all chains out.
    Slip stitches (joins) are never counted, unless the row is only those. A foundation row that skips more chains
    than its first stitch's turning chain counts the extra ones as a space (foundation_space).
    """
    types = row.stitch_types
    if stitch is not None:  # "sc" also covers variants the engine names e.g. sc2inc, sc2tog
        return [sum(n for name, n in types.items() if _is_type(name, stitch))]
    if set(types) <= {"ch"} or set(types) <= {"ss"}:
        return [row.stitch_count]
    slips = sum(n for name, n in types.items() if name.startswith("ss"))
    total = row.stitch_count - slips
    space = foundation_space(row) if types.get("ch") else 0  # extra chains skipped in a foundation row (mesh)
    return [total - min(leading_chains(row), types.get("ch", 0)) + space, total - types.get("ch", 0)]


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
        left_out = "" if line.synthetic else left_out_item(engine, line.source, line.code)
        if left_out:
            hole = True
            lines.append(replace(line, code="", parsed=False,
                                 reason=f"the translation leaves out part of the row: '{left_out}'"))
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
                no_ch = f" ({made[1]} with all chains left out)" if len(made) > 1 and made[1] != made[0] else ""
                reason = f"stated count {stated.count}, translation makes {made[0]}{no_ch}"
        if reason:
            hole = True
            lines.append(replace(line, code="", parsed=False, reason=reason))
        else:
            kept.append(line.code)
            lines.append(line)
    return TranslateResult(lines=lines)


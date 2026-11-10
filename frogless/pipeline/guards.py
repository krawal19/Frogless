"""Guards for readings: a reading may reinterpret ambiguous wording, but it must never explain away a real mistake.

reading_problem() compares another reading of a row (its code) with the row as translated literally, and says
why the reading is not allowed ("" when it is):
1. No deleting. The reading may not be the literal code with stitches or chains removed, and may not lose a
   stitch type the row's text names. A different number on an item ("7dc" read as "3dc") is not a removal.
2. Explicit placement. When the row says where its stitches go ("in next 2 sts", "in each st", "12 times",
   "in same st", "in ch-sp"), the reading may not change how many stitches of the row below it works into.
   The one exception is the side-total case: only the numbers beside plain stitches change ("7dc" between
   corners meaning the whole side), and the text writes those numbers bare, beside the stitch itself. A reading that
   also regroups the row (it starts in a corner space and wraps the last side) is compared by what each stitch type
   comes to: fewer plain stitches only, chains and slip stitches the same.
The comparison is the engine's (Engine.compare_readings, Engine.reading_drops_items); the text is read here.
An engine that cannot list the items of the code gives no verdict and the reading is left to the other checks.
"""

from collections.abc import Iterable

from ..engine import Engine, stitch_family
from ..patterns.placement import bare_number, bare_numbers, chain_from_hook, named_families, states_placement
from ..patterns.stated import turning_chain_stated


_PLAIN = ("sc", "hdc", "dc", "dtr", "ttr", "trtr", "tr")  # the stitch families a side total can change


def reading_problem(engine: Engine, before: str, literal: str, candidate: str, source: str) -> str:
    """Why `candidate` (another reading of the row `source`) is not allowed, or "" if it is.

    `literal` is the row's code as translated literally ("" when there is none), `before` the code of the rows
    before it. Code that is the same as the literal one is always fine.
    """
    if not hasattr(engine, "compare_readings") or candidate.strip() == literal.strip():
        return ""
    if engine.reading_drops_items(literal, candidate, before, named_families(source)):
        return "it drops a stitch or chain the row names (a reading may reinterpret the words, never delete from them)"
    if not literal.strip():
        return ""
    diff = engine.compare_readings(literal, candidate, before)
    if diff is None or diff.consumes is None or diff.consumes[0] == diff.consumes[1] or not states_placement(source):
        return ""
    if (diff.same_shape and diff.number_changes and all(
            stitch_family(kind) and bare_number(source, was, stitch_family(kind))
            for kind, was, _ in diff.number_changes)) or _regrouped_side_totals(diff, source):
        return ""  # the side-total case: a bare number beside a side or group
    a, b = diff.consumes
    return (f"it moves the stitches: it works into {b} stitches of the row below but the row as written works into {a}, "
            "and the row says where its stitches go")


def _regrouped_side_totals(diff, source: str) -> bool:
    """The side-total case when the reading is also grouped differently (a round started in a corner space, its last
    side wrapped round to the stitches before the first chain): the shapes differ, so compare what each stitch type
    comes to. Only plain stitches may change, each only by coming to fewer, and the numbers the reading no longer has
    must be bare numbers of the text (the side lengths); chains, slip stitches and skips come to the same."""
    if diff.same_shape or not diff.family_changes:
        return False
    return (all(family in _PLAIN and now < was for family, was, now in diff.family_changes)
            and all(number in bare_numbers(source, family) for family, number in diff.lost_counts if family in _PLAIN))


def hook_problem(engine: Engine, before: str, code: str, source: str, pattern_lines: Iterable[str]) -> str:
    """Why `code` starts the foundation row in the wrong chain, or "" if it does not.

    "hdc in 3rd ch from hook" starts in chain 3 (two chains skipped); code that starts in chain 2 works one more stitch
    and so makes a short stated count fit. Only an explicit "Nth ch from hook" is checked. The one other start allowed is
    a chain earlier, when the pattern itself says its turning chain counts as a stitch. Code that skips nothing is the
    engine's plain "next N ch" and is left alone. `before` is the code of the rows before, `pattern_lines` the pattern's rows.
    """
    n = chain_from_hook(source)
    if n is None or not code.strip():
        return ""
    check = engine.check("\n".join(c for c in (before, code) if c.strip()))
    if not check.rows or check.rows[-1].index != 1:
        return ""
    first = next((s for s in sorted(check.rows[-1].stitches, key=lambda s: s.position)
                  if stitch_family(s.kind) not in ("ch", "ss")), None)
    if first is None or not first.into or first.into[0][0] != 0:
        return ""
    placed = first.into[0][1] + 1  # the chain it is worked into, counting from the first chain after the hook
    allowed = {1, n} | ({n - 1} if turning_chain_stated(pattern_lines) is True else set())
    if placed in allowed:
        return ""
    return (f"the row says to start in chain {n} from the hook, but the code starts in chain {placed}: "
            "skip the chains before the Nth one, however the count then comes out")

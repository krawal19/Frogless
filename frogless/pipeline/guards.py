"""Guards for readings: a reading may reinterpret ambiguous wording, but it must never explain away a real mistake.

reading_problem() compares another reading of a row (its code) with the row as translated literally, and says
why the reading is not allowed ("" when it is):
1. No deleting. The reading may not be the literal code with stitches or chains removed, and may not lose a
   stitch type the row's text names. A different number on an item ("7dc" read as "3dc") is not a removal.
2. Explicit placement. When the row says where its stitches go ("in next 2 sts", "in each st", "12 times",
   "in same st", "in ch-sp"), the reading may not change how many stitches of the row below it works into.
   The one exception is the side-total case: only the numbers beside plain stitches change ("7dc" between
   corners meaning the whole side), and the text writes those numbers bare, beside the stitch itself.
The comparison is the engine's (Engine.compare_readings, Engine.reading_drops_items); the text is read here.
An engine that cannot list the items of the code gives no verdict and the reading is left to the other checks.
"""

from ..engine import Engine, stitch_family
from ..patterns.placement import bare_number, named_families, states_placement


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
    if diff.same_shape and diff.number_changes and all(
            stitch_family(kind) and bare_number(source, was, stitch_family(kind))
            for kind, was, _ in diff.number_changes):
        return ""  # the side-total case: a bare number beside a side or group
    a, b = diff.consumes
    return (f"it moves the stitches: it works into {b} stitches of the row below but the row as written works into {a}, "
            "and the row says where its stitches go")

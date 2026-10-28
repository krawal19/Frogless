"""Engine-neutral pattern spec, plus the arithmetic that gives the known answer.

A spec says what a pattern does (stitches per round or row) without any engine syntax;
engine.encode(spec) turns it into engine code.
"""

from dataclasses import dataclass, field


@dataclass
class Item:
    """n stitches of one kind. kind: "st" (plain), "inc" (2 in one stitch), "dec" (2 together)."""

    kind: str
    stitch: str = "sc"
    n: int = 1


@dataclass
class Repeat:
    """A group of items worked `times` times, e.g. *sc, inc* x 6."""

    items: list
    times: int


@dataclass
class Spec:
    start: str  # "ring" (magic ring) or "chain" (foundation chain)
    mode: str  # "rounds" or "rows"
    rows: list = field(default_factory=list)  # each row is a list of Item / Repeat
    chain: int = 0  # foundation chain length, when start == "chain"
    stitch: str = "sc"  # main stitch; sets the turning chain and skipped chains for rows
    turn_counts: bool = False  # hdc/dc rows: the pattern says the turning chain counts as the row's first stitch


def consumed(items) -> int:
    """Stitches of the previous row these items work into."""
    return sum(_one(i)[0] for i in items)


def made(items) -> int:
    """Stitches these items leave on the hook side (the row's count)."""
    return sum(_one(i)[1] for i in items)


def _one(i):
    if isinstance(i, Repeat):
        return consumed(i.items) * i.times, made(i.items) * i.times
    if i.kind == "inc":
        return i.n, 2 * i.n
    if i.kind == "dec":
        return 2 * i.n, i.n
    return i.n, i.n


def skipped(spec) -> int:
    """Foundation chains skipped before the first worked stitch of row 1 ("dc in 4th ch from hook")."""
    return {"sc": 1, "hdc": 2, "dc": 3}[spec.stitch]


def foundation_stitches(spec) -> int:
    """Stitches row 1 can make from the foundation chain. By default the skipped chains are the
    turning chain and do not count (Ch 17 gives 14 dc, "dc in 4th ch from hook"); where the pattern
    says the turning chain counts as a stitch they count as one (Ch 16 gives 14 dc)."""
    return spec.chain - skipped(spec) + (1 if spec.turn_counts else 0)


def expected(spec, stated=None) -> dict:
    """The known answer: {verdict, break_row, counts}, by arithmetic.

    A row breaks if it works into more or fewer stitches than the row before made, or if
    it makes a different count from the one the English states (stated, per row).
    """
    counts = [made(r) for r in spec.rows]
    avail = foundation_stitches(spec) if spec.start == "chain" else None  # ring: no row before
    for n, row in enumerate(spec.rows, 1):
        if avail is not None and consumed(row) != avail:
            return {"verdict": "breaks", "break_row": n, "counts": counts}
        if stated and counts[n - 1] != stated[n - 1]:
            return {"verdict": "breaks", "break_row": n, "counts": counts}
        avail = counts[n - 1]
    return {"verdict": "works", "break_row": None, "counts": counts}

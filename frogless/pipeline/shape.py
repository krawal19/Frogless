"""Shape hints: what the finished piece will probably look like.

Pure functions over the engine's per-row results (RowInfo, with StitchInfo when the engine
provides them). They return ShapeFinding hints worded for a crocheter. A finding is advice shown
next to the verdict; it never decides whether the pattern works.

Checks (each is a small function, and check_shape runs them all):
1. check_circle_growth  - rounds worked from a ring: does each round grow by what a flat circle
   needs for that stitch height (about 6 for sc, 8 for hdc, 12 for dc)? Too little cups into a
   bowl or tube, too much ruffles. Even rounds after a flat base are straight sides, and
   decreases after that close a ball or dome. Both are fine and reported as info. Skipped for
   polygons (3 or more corners): a square grows by about 8 a round and is meant to be flat.
2. check_even_spacing   - are the increases (and decreases) of a round spread evenly? Gaps that
   differ by more than 1 give a lopsided shape. Needs StitchInfo.
3. check_polygon        - squares and other polygons: corners are chain spaces between stitches
   worked into the same place (or stitches labelled "corner"). Warns when the number of corners
   changes between rounds, when the sides of a round differ in length, or when the corner spaces
   of one round differ in size (one ch-4 space among ch-2 spaces). Needs StitchInfo.
4. check_flat_rows      - a row whose count drifts from the row below with nothing to explain
   it. Light: only rows without chain spaces, where the count is easy to follow.

Counting conventions: chains ("ch") and slip stitches ("ss...") are not counted as stitches.
"NNinc" (sc2inc, dc3inc) makes N stitches in one; "Ntog" works N stitches together into one.
"""

import math
import re
from dataclasses import dataclass

from ..engine import RowInfo, StitchInfo

# Increase needed per round for a flat circle, by stitch height (about 2 pi x height).
FLAT_INCREASE = {"sc": 6, "hdc": 8, "dc": 12, "tr": 16, "dtr": 20}
GROWTH_LOW = 0.6  # below this share of the flat-circle increase the piece cups
GROWTH_HIGH = 1.4  # above this share it ruffles
SPACING_TOLERANCE = 1  # gaps between increases may differ by this much
SIDE_TOLERANCE = 1  # sides of a polygon may differ by this much
MAX_LISTED = 8  # how many gaps or side lengths to spell out in a message

_CHANGE = re.compile(r"([a-z]*?)(\d*)(inc|tog|dec)")
_RING_WORDS = re.compile(
    r"magic\s+(ring|circle|loop)|adjustable\s+(ring|loop)|\b(in|into)\s+a\s+ring\b"
    r"|\bin\s+(the\s+)?(first|1st)\s+ch\b",
    re.I,
)


@dataclass
class ShapeFinding:
    row: int | None  # row/round index the hint is about, None for the whole piece
    kind: str  # "flat_circle", "cups", "ruffles", "tube", "ball", "uneven_increases", ...
    message: str
    severity: str = "warning"  # "warning" or "info"


# Words that say the finished piece is meant to lie flat.
_FLAT_WORDS = re.compile(
    r"\b(coasters?|place ?mats?|doil(y|ies)|blankets?|afghans?|throws?|rugs?|trivets?|pot ?holders?"
    r"|dishcloths?|washcloths?|granny squares?|lies? flat|lay flat|flat (circle|piece|disc))\b",
    re.I,
)


def meant_flat(text: str) -> bool:
    """True when the pattern says (or names a thing that is) meant to lie flat."""
    return bool(_FLAT_WORDS.search(text))


def starts_from_ring(text: str) -> bool:
    """True when the written pattern starts a round from a ring (magic ring, ring of chains, or all in the first chain)."""
    return bool(_RING_WORDS.search(text))


def check_shape(rows: list[RowInfo], from_ring: bool = False, flat: bool = False) -> list[ShapeFinding]:
    """Run every shape check. from_ring says the first row is a round worked into a ring; flat says
    the piece is meant to lie flat. Growth that isn't flat is only a warning for a flat piece: in a
    3D piece (a ball, a cone, a hat) it is the point, so it is described as information."""
    findings: list[ShapeFinding] = []
    if from_ring:
        growth = check_circle_growth(rows)
        if not flat:
            growth = _describe_growth(growth)
        findings += growth
    findings += check_even_spacing(rows, cyclic=from_ring)
    findings += check_polygon(rows)
    findings += check_flat_rows(rows)
    return sorted(findings, key=lambda f: (f.row is None, f.row or 0))


def _describe_growth(findings: list[ShapeFinding]) -> list[ShapeFinding]:
    """For a piece not meant to be flat: one information line for the cupping or ruffling rounds."""
    keep = [f for f in findings if f.kind not in ("cups", "ruffles")]
    for kind, word in (("cups", "curves up into a 3D shape (cup, cone or tube)"), ("ruffles", "ruffles")):
        hits = [f for f in findings if f.kind == kind]
        if hits:
            span = f"Round {hits[0].row}" if len(hits) == 1 else f"Rounds {hits[0].row}-{hits[-1].row}"
            keep.append(ShapeFinding(hits[0].row, kind, (
                f"{span} grow {'less' if kind == 'cups' else 'more'} than a flat circle would, "
                f"so the piece {word}. Fine if that is the shape you want."), "info"))
    return keep


# ---- helpers --------------------------------------------------------------------------------


def _is_chain(s: StitchInfo) -> bool:
    return s.kind == "ch"


def _is_counted(s: StitchInfo) -> bool:
    """Chains and slip stitches are not counted as stitches."""
    return not _is_chain(s) and not s.kind.startswith("ss")


def _change(kind: str) -> tuple[str, int] | None:
    """("inc" or "dec", N) for sc2inc, dc3tog, dec and friends; None for a plain stitch."""
    m = _CHANGE.fullmatch(kind)
    if not m:
        return None
    return ("inc" if m[3] == "inc" else "dec"), int(m[2] or 2)


def _base_kind(kind: str) -> str:
    m = _CHANGE.fullmatch(kind)
    return m[1] if m else kind


def _count(row: RowInfo) -> int:
    """The row's stitch count without chains and slip stitches (the engine's count includes them)."""
    if not row.stitch_types:
        return row.stitch_count
    return sum(n for kind, n in row.stitch_types.items() if kind != "ch" and not kind.startswith("ss"))


def _counted(row: RowInfo) -> list[StitchInfo]:
    """The row's counted stitches in working order. Repeated nodes of one increase or decrease
    (the same kind worked into the same place) collapse to one, so a count never doubles."""
    result: list[StitchInfo] = []
    for s in sorted(row.stitches, key=lambda s: s.position):
        if not _is_counted(s):
            continue
        prev = result[-1] if result else None
        if prev and _change(s.kind) and prev.kind == s.kind and s.into and prev.into == s.into:
            continue
        result.append(s)
    return result


def _span(rows: list[RowInfo]) -> str:
    first, last = rows[0].index, rows[-1].index
    return f"Round {first}" if first == last else f"Rounds {first}-{last}"


def _listed(numbers: list[int]) -> str:
    text = ", ".join(str(n) for n in numbers[:MAX_LISTED])
    return text + ("..." if len(numbers) > MAX_LISTED else "")


# ---- 1. flat circle growth ------------------------------------------------------------------


def _dominant_stitch(row: RowInfo) -> str | None:
    """The most used stitch of the row, with inc/tog suffixes stripped (sc2inc counts as sc)."""
    counts: dict[str, int] = {}
    for kind, n in row.stitch_types.items():
        if kind != "ch" and not kind.startswith("ss"):
            counts[_base_kind(kind)] = counts.get(_base_kind(kind), 0) + n
    return max(counts, key=counts.get) if counts else None


def check_circle_growth(rows: list[RowInfo]) -> list[ShapeFinding]:
    """Rounds worked from a ring (rows[0] is the first round).

    Leading rounds that add stitches are the flat base. Each is compared with what a flat circle
    of that stitch needs (FLAT_INCREASE, tolerance GROWTH_LOW..GROWTH_HIGH). After the base:
    even rounds to the end are a tube (or a bowl when the base never grew), even rounds then
    decreases are a ball or dome. A single even round inside the growth is left alone.

    Chains and slip stitches are not counted. A foundation ring of chains (no stitches) is not a
    round. A piece with a round of 3 or more corners is a polygon, not a circle: nothing to say.
    """
    findings: list[ShapeFinding] = []
    while rows and _count(rows[0]) == 0:
        rows = rows[1:]
    if len(rows) < 2 or any(len(corner_sides(row)) >= 3 for row in rows):
        return findings
    delta = [_count(rows[k]) - _count(rows[k - 1]) for k in range(1, len(rows))]
    k = 1  # rows[k] is the round being judged; delta[k - 1] is its growth
    base: list[RowInfo] = []
    bad = 0
    while k < len(rows):
        d = delta[k - 1]
        if d > 0:
            base.append(rows[k])
            stitch = _dominant_stitch(rows[k])
            need = FLAT_INCREASE.get(stitch or "")
            if need:
                low, high = math.ceil(need * GROWTH_LOW), int(need * GROWTH_HIGH)
                if d < low:
                    bad += 1
                    findings.append(ShapeFinding(rows[k].index, "cups", (
                        f"Round {rows[k].index} grows by only {d} stitches. A flat circle of {stitch} "
                        f"needs about {need} more each round, so this will cup into a bowl.")))
                elif d > high:
                    bad += 1
                    findings.append(ShapeFinding(rows[k].index, "ruffles", (
                        f"Round {rows[k].index} grows by {d} stitches. A flat circle of {stitch} "
                        f"needs about {need} more each round, so this will ruffle.")))
        elif d == 0 and k + 1 < len(rows) and delta[k] > 0:
            pass  # one even round inside the growth
        else:
            break
        k += 1
    if base and not bad:
        stitch = _dominant_stitch(base[0])
        if stitch in FLAT_INCREASE:
            grows = ", ".join(str(_count(rows[i]) - _count(rows[i - 1]))
                              for i in range(1, k) if delta[i - 1] > 0)
            findings.append(ShapeFinding(base[-1].index, "flat_circle", (
                f"{_span(base)} grow by {grows} stitches, about what a flat circle of {stitch} needs, "
                f"so the base should lie flat."), "info"))
    findings += _after_base(rows, k, delta, bad, bool(base))
    return findings


def _after_base(rows: list[RowInfo], k: int, delta: list[int], bad: int, grew: bool) -> list[ShapeFinding]:
    """Judge the rounds after the growth: even to the end, or even then decreasing."""
    if k >= len(rows):
        return []
    j = k
    while j < len(rows) and delta[j - 1] == 0:
        j += 1
    even = rows[k:j]
    if j < len(rows) and delta[j - 1] < 0:
        if not grew:
            return []
        return [ShapeFinding(rows[j].index, "ball", (
            f"From round {rows[j].index} the rounds decrease from {_count(rows[j - 1])} stitches, "
            f"so the piece closes into a ball or dome."), "info")]
    if j < len(rows):
        return []  # grows again later (a flare); nothing to say
    if not grew:
        return [ShapeFinding(even[0].index, "cups", (
            f"{_span(even)} add no stitches, so the piece will curl into a tube or cup "
            f"instead of a flat circle."))]
    if bad:
        return []
    return [ShapeFinding(even[0].index, "tube", (
        f"From round {even[0].index} the rounds stay at {_count(even[0])} stitches, "
        f"so the piece forms straight sides (a tube)."), "info")]


# ---- 2. even spacing of increases and decreases ---------------------------------------------


def check_even_spacing(rows: list[RowInfo], cyclic: bool = False) -> list[ShapeFinding]:
    """Warn when the gaps between a round's increases (or decreases) differ by more than
    SPACING_TOLERANCE. A gap is the distance in stitches between two neighbours. In rounds
    (cyclic) the gap from the last back to the first counts too, so a staggered start is fine.
    Rows with corners are left to check_polygon, where uneven spacing is the design."""
    findings: list[ShapeFinding] = []
    for row in rows:
        if len(_corner_groups(row)[1]) >= 3:
            continue
        stitches = _counted(row)
        for what in ("inc", "dec"):
            at = [i for i, s in enumerate(stitches) if (_change(s.kind) or ("", 0))[0] == what]
            if len(at) < 3:
                continue
            gaps = [b - a for a, b in zip(at, at[1:])]
            if cyclic:
                gaps.append(len(stitches) - at[-1] + at[0])
            if max(gaps) - min(gaps) > SPACING_TOLERANCE:
                word = "increases" if what == "inc" else "decreases"
                findings.append(ShapeFinding(row.index, f"uneven_{word}", (
                    f"Round {row.index}'s {word} are bunched (gaps {_listed(gaps)}). "
                    f"Spread them evenly or the piece will come out lopsided.")))
    return findings


# ---- 3. squares and polygons ----------------------------------------------------------------


def _shares(a: StitchInfo, b: StitchInfo) -> bool:
    return bool(set(map(tuple, a.into)) & set(map(tuple, b.into)))


def _corner_groups(row: RowInfo) -> tuple[list[StitchInfo], list[list[int]]]:
    """Find the corners of a round. Returns (items, groups): the row's chains and counted
    stitches in working order (rotated to start at a counted stitch, so a chain at the end
    joins one at the start), and each corner as a list of item indexes.

    A corner is a run of chains between two stitches worked into the same place, with the stitches
    on both sides that share that place; or a run of stitches labelled "corner"."""
    items = [s for s in sorted(row.stitches, key=lambda s: s.position) if _is_chain(s) or _is_counted(s)]
    first = next((i for i, s in enumerate(items) if _is_counted(s)), None)
    if first is None or sum(_is_counted(s) for s in items) < 2:
        return items, []
    items = items[first:] + items[:first]
    m = len(items)
    groups: list[list[int]] = []
    taken: set[int] = set()

    def add(indexes: list[int]) -> None:
        indexes = [i for i in indexes if i not in taken]
        if indexes:
            groups.append(indexes)
            taken.update(indexes)

    i = 0
    while i < m:
        if not _is_chain(items[i]):
            i += 1
            continue
        end = i
        while end + 1 < m and _is_chain(items[end + 1]):
            end += 1
        left, right = i - 1, (end + 1) % m
        labelled = any("corner" in items[j].label.lower() for j in range(i, end + 1))
        if labelled or _shares(items[left], items[right]):
            # (a corner at the end of the round reaches back to stitches at its start, and the
            # other way round, so these walk around the round)
            lo = left
            while ((lo - 1) % m not in taken and lo - 1 > left - m and _is_counted(items[(lo - 1) % m])
                   and _shares(items[(lo - 1) % m], items[left])):
                lo -= 1
            hi = right if right > end else right + m
            while ((hi + 1) % m not in taken and hi + 1 < lo + m and _is_counted(items[(hi + 1) % m])
                   and _shares(items[(hi + 1) % m], items[right])):
                hi += 1
            add([j % m for j in range(lo, end + 1)] + [j % m for j in range(right if right > end else right + m, hi + 1)])
        i = end + 1
    run: list[int] = []
    for j in range(m + 1):
        if j < m and "corner" in items[j].label.lower():
            run.append(j)
        else:
            add(run)
            run = []
    return items, groups


def corner_spaces(row: RowInfo) -> list[int]:
    """The number of chains in each corner space of a round, in working order (corners made of
    stitches labelled "corner", with no chains, are left out)."""
    items, groups = _corner_groups(row)
    sizes = [(min(g), sum(_is_chain(items[i]) for i in g)) for g in groups]
    return [n for _, n in sorted(sizes) if n]


def corner_sides(row: RowInfo) -> list[int]:
    """Stitches on each side of a round, between its corner groups (corner stitches excluded)."""
    items, groups = _corner_groups(row)
    if not groups:
        return []
    m = len(items)
    gid: list[int | None] = [None] * m
    for g, indexes in enumerate(groups):
        for i in indexes:
            gid[i] = g
    start = next((i for i in range(m) if gid[i] is not None and gid[i - 1] != gid[i]), None)
    if start is None:
        return []
    sides: list[int] = []
    since, last = 0, None
    for step in range(m):
        i = (start + step) % m
        if gid[i] is None:
            since += _is_counted(items[i])
        elif gid[i] != last:
            if last is not None:
                sides.append(since)
            since, last = 0, gid[i]
    sides.append(since)
    return sides


def check_polygon(rows: list[RowInfo]) -> list[ShapeFinding]:
    """Corners must stay the same from round to round, and a polygon's sides must match.

    A round with 3 or more corners is a polygon. Warn when the corner count differs from the
    round before, and when the sides differ by more than SIDE_TOLERANCE. Four corners may be a
    rectangle: opposite sides then need to match instead."""
    findings: list[ShapeFinding] = []
    prev_corners = 0
    for row in rows:
        sides = corner_sides(row)
        corners = len(sides)
        if prev_corners and corners and prev_corners != corners and max(prev_corners, corners) >= 3:
            findings.append(ShapeFinding(row.index, "corners_changed", (
                f"Round {row.index} has {corners} corners but the round before had {prev_corners}. "
                f"The corner count should stay the same, or the shape will twist.")))
        prev_corners = corners
        spaces = corner_spaces(row)
        if corners >= 3 and len(spaces) >= 3 and len(set(spaces)) > 1:
            findings.append(ShapeFinding(row.index, "uneven_corners", f"Round {row.index}: {_corner_sizes(spaces)} "
                f"The corner spaces of a round should match, or the corners will come out uneven."))
        if corners >= 3 and not _sides_match(sides):
            findings.append(ShapeFinding(row.index, "uneven_sides", (
                f"Round {row.index}: sides have {_listed(sides)} stitches. "
                f"The sides of a square should match (a rectangle needs opposite sides to match).")))
    return findings


def _corner_sizes(spaces: list[int]) -> str:
    """"one corner is a ch-4 space, the others are ch-2." (or all sizes listed when they vary more)."""
    odd = [n for n in spaces if spaces.count(n) == 1]
    common = [n for n in spaces if spaces.count(n) > 1]
    if len(odd) == 1 and len(set(common)) == 1:
        return f"one corner is a ch-{odd[0]} space, the others are ch-{common[0]}."
    return "the corner spaces differ in size (" + ", ".join(f"ch-{n}" for n in spaces) + ")."


def _sides_match(sides: list[int]) -> bool:
    if max(sides) - min(sides) <= SIDE_TOLERANCE:
        return True
    if len(sides) == 4:  # rectangle: opposite sides agree
        return (abs(sides[0] - sides[2]) <= SIDE_TOLERANCE and abs(sides[1] - sides[3]) <= SIDE_TOLERANCE)
    return False


# ---- 4. flat rows ---------------------------------------------------------------------------


def check_flat_rows(rows: list[RowInfo]) -> list[ShapeFinding]:
    """Warn when a row's count differs from the row below by more than its increases and
    decreases explain. Light on purpose: needs StitchInfo on both rows and skips rows with chain
    spaces inside them, where counting stitches against spaces is not reliable."""
    findings: list[ShapeFinding] = []
    for prev, row in zip(rows, rows[1:]):
        if not prev.stitches or not row.stitches or _has_inner_chain(prev) or _has_inner_chain(row):
            continue
        explained = row.overflow - row.unworked
        landed: dict[tuple, int] = {}
        for s in _counted(row):
            change = _change(s.kind)
            if change:
                explained += (change[1] - 1) * (1 if change[0] == "inc" else -1)
            elif s.into:
                landed[tuple(map(tuple, s.into))] = landed.get(tuple(map(tuple, s.into)), 0) + 1
        # several plain stitches worked into one place (a corner of 2dc, tr, 2dc) are increases too
        explained += sum(n - 1 for n in landed.values())
        drift = _count(row) - _count(prev) - explained
        if drift:
            findings.append(ShapeFinding(row.index, "count_drift", (
                f"Row {row.index} has {_count(row)} stitches but the row below has "
                f"{_count(prev)}, and its increases and decreases only account for "
                f"{explained:+d}. The edges may be growing or shrinking by accident.")))
    return findings


def _has_inner_chain(row: RowInfo) -> bool:
    kinds = [s for s in sorted(row.stitches, key=lambda s: s.position) if _is_counted(s) or _is_chain(s)]
    while kinds and _is_chain(kinds[0]):
        kinds.pop(0)
    while kinds and _is_chain(kinds[-1]):
        kinds.pop()
    return any(_is_chain(s) for s in kinds)

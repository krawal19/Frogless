"""Omission check: does the rules translation leave out an item the row's text names?

The rules translator can drop part of a row without saying so. "Rnd 3: (sc, 2 sc in next st) 6 times, sc (18)"
becomes only the repeat, and the trailing ", sc" is lost; the count may still match the stated one, so the
stated-count gate and the faithfulness check let it through. Plain code, no model calls.

Conservative on purpose. It only looks at a row that has a repeat ("(...) 6 times", "*...; rep from *"), and
only at the separate items written outside the repeat (before it, after it) that say how many stitches they
are ("sc", "dc in next st", "sc in last st"). Open-ended parts ("sc in each st around", "to the end"), chains
(a turning chain moves to the next row), slip stitches and anything inside a bracket are left alone. The row
is flagged only when, for some stitch type, the text names more such items than the code has outside its repeats.
"""

import re

from ..engine import Engine, stitch_family
from ..patterns.placement import named_families

_REPEAT = re.compile(r"\b\d+\s*(?:more\s+)?times\b|\btwice\b|\bthrice\b|[x×]\s*\d+\b|\brep(?:eat)?\b", re.IGNORECASE)
_OPEN = re.compile(r"\b(?:each|every|around|across|end|rest|remaining|repeat|rep|to|until|along|all)\b", re.IGNORECASE)
_LABEL = re.compile(r"^\s*(?:rows?|rnds?|rounds?|r)\s*[\d\s\-–,&and]+(?:\([^)]*\))?\s*:", re.IGNORECASE)
_COUNT = re.compile(r"\s*(?:[(\[]\s*\d+[^()\[\]]*[)\]]|=\s*\d+[^,;]*)\s*[.;]?\s*$")
_SKIPPED = ("ch", "ss")  # not checked: turning chains move to the next row, joins are written many ways


def _tokens(text: str) -> list[str]:
    """The row's top-level pieces: split at commas, semicolons and "and", outside brackets."""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    pieces = []
    for tok in out:
        pieces += re.split(r"\s+and\s+(?![^()]*\))", tok) if "(" not in tok else [tok]
    return [p.strip(" .") for p in pieces if p.strip(" .")]


def _outside_repeat(source: str) -> list[str] | None:
    """The pieces of the row written outside its repeat; None when the row has no repeat."""
    text = _COUNT.sub("", _LABEL.sub("", source.strip(), count=1)).strip()
    toks = _tokens(text)
    marks = [i for i, t in enumerate(toks) if _REPEAT.search(t) and ("(" in t or "[" in t or "*" in t or "rep" in t.lower())]
    if not marks:
        return None
    asterisk = any("*" in t for t in toks[:marks[0] + 1])
    before = [] if asterisk else toks[:marks[0]]
    return before + toks[marks[-1] + 1:]


def _named_items(pieces: list[str]) -> list[tuple[str, str]]:
    """(stitch family, piece) for each piece that is one fixed item of the row."""
    items = []
    for piece in pieces:
        if "(" in piece or "[" in piece or "*" in piece or _OPEN.search(piece) or _REPEAT.search(piece):
            continue
        families = [f for f in named_families(piece) if f not in _SKIPPED]
        if len(named_families(piece)) == 1 and families:
            items.append((families[0], piece))
    return items


def left_out_item(engine: Engine, source: str, code: str) -> str:
    """The first item the row's text names outside its repeat that the code lacks, or "" if nothing is missing.

    The text is `source`; `code` may hold several lines (a range of rows), each of which is checked.
    """
    named = _named_items(_outside_repeat(source) or [])
    if not named:
        return ""
    for line in code.splitlines():
        items = engine.row_items(line)
        if items is None:
            return ""
        have: dict[str, int] = {}
        for it in items:
            if it.times == 1:
                family = stitch_family(it.kind)
                have[family] = have.get(family, 0) + it.count
        used: dict[str, int] = {}
        for family, piece in named:
            used[family] = used.get(family, 0) + 1
            if used[family] > have.get(family, 0):
                return piece
    return ""

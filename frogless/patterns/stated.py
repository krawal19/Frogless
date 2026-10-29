"""Read the stitch count a pattern line states about itself, e.g. "(12)" or "= 14 sc".

Engine-neutral: works on the written text only. Instructions that merely contain a
number, such as "(2 dc, ch 2, 2 dc) in next sp" or "ch 2 (counts as dc)", give None.
"""

import re
from dataclasses import dataclass

# stitch words -> short name; "sts"/"stitches" mean "all stitches" and map to None.
# "pc", "bobble" and "puff" are special stitches: "(6 popcorns)" counts only those.
_TYPES = {
    "sc": "sc", "hdc": "hdc", "dc": "dc", "tr": "tr", "trc": "tr", "dtr": "dtr", "ch": "ch", "chs": "ch",
    "single crochet": "sc", "single crochets": "sc", "half double crochet": "hdc",
    "half double crochets": "hdc", "double crochet": "dc", "double crochets": "dc",
    "treble crochet": "tr", "treble crochets": "tr", "chain": "ch", "chains": "ch",
    "popcorn": "pc", "popcorns": "pc", "pc": "pc", "pcs": "pc", "popcorn st": "pc", "popcorn sts": "pc",
    "popcorn stitch": "pc", "popcorn stitches": "pc",
    "bobble": "bobble", "bobbles": "bobble", "bobble st": "bobble", "bobble sts": "bobble",
    "bobble stitch": "bobble", "bobble stitches": "bobble",
    "puff": "puff", "puffs": "puff", "puff st": "puff", "puff sts": "puff",
    "puff stitch": "puff", "puff stitches": "puff",
    "st": None, "sts": None, "stitch": None, "stitches": None,
}
_WORDS = "|".join(sorted(_TYPES, key=len, reverse=True))
_TYPE = rf"(?P<type>{_WORDS})\b"
_N = r"(?P<n>\d+)"

# optional "ch 1, turn" style tail that may follow a count
_TAIL = r"\s*[.,;]?\s*(?:ch\s*\d+\s*,?\s*)?(?:turn\s*)?[.,;]?\s*$"
# a label such as "Row 3:" or "Rnds 4-6:" at the start of the line
_LABEL = re.compile(r"^\s*(?:rows?|rnds?|rounds?|r)\s*[\d\s\-–,&and]+:\s*")

_PATTERNS = [  # first match wins, most specific first
    # multi-size: (88 [94, 106] sc)
    ("multi", re.compile(rf"[(\[]\s*{_N}\s*[\[(][\d,\s/&and]+[\])]\s*(?:{_TYPE})?\s*[)\]]" + _TAIL)),
    # (There are 14 sc ...), you should have 14 sc, total of 12 dc, 12 dc in total
    ("said", re.compile(rf"\b(?:there\s+(?:are|will\s+be|should\s+be)|you\s+(?:should|will|now)\s+have|total\s+of)\s+{_N}\b\s*(?:{_TYPE})?")),
    ("said", re.compile(rf"\b{_N}\s*(?:{_TYPE})?\s+in\s+total\b")),
    # (12) (12 sts) (14 sc) [12dc] [16stitches]: nothing else inside the brackets
    ("plain", re.compile(rf"[(\[]\s*{_N}\s*(?:{_TYPE})?\s*[)\]]" + _TAIL)),
    # = 12   = 12 sc
    ("plain", re.compile(rf"=\s*{_N}\s*(?:{_TYPE})?" + _TAIL)),
    # : 14 sc   - 14 sc   (needs a stitch word, so "Rnd 2: 6 sc" as an instruction is not a count)
    ("plain", re.compile(rf"(?<=\S)\s*(?::|\s[—–-])\s*{_N}\s*{_TYPE}" + _TAIL)),
]


@dataclass(frozen=True)
class StatedCount:
    count: int
    stitch: str | None = None  # "sc", "dc", ... when the count is for one stitch type only
    multi_size: bool = False  # count was the first of several sizes


def stated_count(line: str) -> StatedCount | None:
    """The count the line states, or None if it states none."""
    text = _LABEL.sub("", line.lower().strip(), count=1)
    if not text:
        return None
    for kind, rx in _PATTERNS:
        m = rx.search(text)
        if m:
            word = m.groupdict().get("type")
            return StatedCount(int(m["n"]), _TYPES.get(word) if word else None, multi_size=kind == "multi")
    return None


# "ch 3 (counts as first dc)", "turning chain counts as a st" / "does not count as a stitch"
_COUNTS_AS = re.compile(r"\bcount(?:s|ed|ing)?\s+as\b")
_NOT_COUNTS_AS = re.compile(r"(?:\bnot|n't|\bnever|\bwithout)\s+(?:\w+\s+){0,2}?count(?:s|ed|ing)?(?=\s+as\b|\s*[).,;\]]|\s*$)")


def turning_chain_explicit(line: str) -> bool | None:
    """What a line says outright about its chain counting as a stitch: True ("ch 3 (counts as dc)"),
    False ("ch 3 (does not count as a st)") or None (nothing)."""
    text = _LABEL.sub("", line.lower().strip(), count=1)
    if not re.search(r"\bch(?:ain|s)?\b", text):
        return None
    if _NOT_COUNTS_AS.search(text):
        return False
    return True if _COUNTS_AS.search(text) else None


# Wording clues, weaker than a statement. A row that starts "ch 3, dc in NEXT st" leaves the stitch beside the chain
# unworked, so the chain stands in for it (it counts); "dc in FIRST st" (or "in same st") works that stitch, so the chain
# does not count. A row whose last stitch goes into the previous row's turning chain ("dc in top of turning ch", "last dc in
# 3rd ch of beg ch-3", "dc in 2nd ch of turning ch") treats that chain as a stitch of the row.
_START_PLACE = re.compile(
    r"\bch(?:ain)?s?\s*-?\s*(?:[2-9]|\d\d)\b\s*(?:\([^)]*\)\s*)?[,;.]?\s*(?:(?:and\s+)?(?:then\s+)?\d*\s*)"
    r"(?:hdc|dc|tr|dtr|trc)\s+(?:in|into)\s+(?:the\s+)?(next|first|1st|same)\s+(?:\d+\s+)?(?:st|sts|stitch|stitches)\b")
_INTO_TURNING = re.compile(
    r"\b(?:in|into)\s+(?:the\s+)?(?:"
    r"(?:top|\d+(?:st|nd|rd|th)\s+ch(?:ain)?|(?:last|first)\s+ch(?:ain)?)\s+of\s+(?:the\s+)?"
    r"(?:(?:turning|beg(?:inning)?|starting)\s*-?\s*)?ch(?:ain|s)?\b"
    r"|turning\s*-?\s*ch(?:ain)?\b)")


def turning_chain_clue(line: str) -> bool | None:
    """What the wording of a line suggests about its turning chain counting: True, False or None (see above)."""
    text = _LABEL.sub("", line.lower().strip(), count=1)
    found = {m.group(1) == "next" for m in _START_PLACE.finditer(text)}
    if _INTO_TURNING.search(text):
        found.add(True)
    return found.pop() if len(found) == 1 else None


def turning_chain_says(line: str) -> bool | None:
    """What a line says about its chain counting as a stitch: its own statement, else what its wording suggests."""
    explicit = turning_chain_explicit(line)
    return explicit if explicit is not None else turning_chain_clue(line)


def turning_chain_stated(lines) -> bool | None:
    """What the pattern says about its turning chain: True (counts as a stitch), False (does not), or None (silent or
    contradicting itself). Only statements are looked at; wording clues count only when the pattern states nothing at all
    and are asked for separately (turning_chain_hint), so "does not count" wins over a row that works into the chain."""
    said = {turning_chain_explicit(line) for line in lines} - {None}
    return said.pop() if len(said) == 1 else None


def turning_chain_hint(lines) -> bool | None:
    """What the wording of the pattern's rows suggests about the turning chain, when it states nothing."""
    lines = list(lines)
    if {turning_chain_explicit(line) for line in lines} - {None}:
        return None
    said = {turning_chain_clue(line) for line in lines} - {None}
    return said.pop() if len(said) == 1 else None

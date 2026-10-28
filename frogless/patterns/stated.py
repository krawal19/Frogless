"""Read the stitch count a pattern line states about itself, e.g. "(12)" or "= 14 sc".

Engine-neutral: works on the written text only. Instructions that merely contain a
number, such as "(2 dc, ch 2, 2 dc) in next sp" or "ch 2 (counts as dc)", give None.
"""

import re
from dataclasses import dataclass

# stitch words -> short name; "sts"/"stitches" mean "all stitches" and map to None
_TYPES = {
    "sc": "sc", "hdc": "hdc", "dc": "dc", "tr": "tr", "trc": "tr", "dtr": "dtr", "ch": "ch", "chs": "ch",
    "single crochet": "sc", "single crochets": "sc", "half double crochet": "hdc",
    "half double crochets": "hdc", "double crochet": "dc", "double crochets": "dc",
    "treble crochet": "tr", "treble crochets": "tr", "chain": "ch", "chains": "ch",
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
_NOT_COUNTS_AS = re.compile(r"(?:\bnot|n't|\bnever|\bwithout)\s+(?:\w+\s+){0,2}?count(?:s|ed|ing)?\s+as\b")


def turning_chain_says(line: str) -> bool | None:
    """What a line says about its chain counting as a stitch: True ("ch 3 (counts as dc)"),
    False ("ch 3 (does not count as a st)") or None (nothing)."""
    text = _LABEL.sub("", line.lower().strip(), count=1)
    if not re.search(r"\bch(?:ain|s)?\b", text):
        return None
    if _NOT_COUNTS_AS.search(text):
        return False
    return True if _COUNTS_AS.search(text) else None

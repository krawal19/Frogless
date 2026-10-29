"""What a written row says about the stitches it works and where it works them.

Engine-neutral: written text only. Used by the guards that stop a "reading" of a row from explaining a
real mistake away (frogless/pipeline/guards.py).
"""

import re

from .stated import _TYPES

_STITCH_WORDS = {w: t for w, t in _TYPES.items() if t}  # "dc" -> "dc", "double crochet" -> "dc", "chain" -> "ch"
_WORDS = "|".join(sorted((re.escape(w) for w in _STITCH_WORDS), key=len, reverse=True))
_NAMED = re.compile(rf"(?<![A-Za-z])({_WORDS}|sl\s*st|slst|ss|slip\s+stitch(?:es)?)(?![A-Za-z])", re.IGNORECASE)
_SLIP = {"slst", "ss", "slip stitch", "slip stitches"}

# phrases that say where stitches go
_PLACED = re.compile(
    r"\bin\s+(?:the\s+)?next\s+\d+|\bnext\s+\d+\s+(?:st|sts|stitch|stitches|sc|hdc|dc|tr|ch|chs)\b"
    r"|\bin\s+each\b|\bin\s+every\b|\b\d+\s+times\b|\btwice\b|\bthrice\b"
    r"|\bin\s+(?:the\s+)?same\s+(?:st|stitch|sp|space)\b|\bch[-\s]?\d*\s*(?:sp|space)\b|\bin\s+(?:the\s+)?(?:ch|chain)\b"
    r"|\bin\s+(?:the\s+)?last\b|\bin\s+(?:the\s+)?first\b|\b(?:sk|skip)\s+\d+",
    re.IGNORECASE)


def named_families(source: str) -> tuple[str, ...]:
    """The stitch families a row's text names: ("sc", "ch") for "sc in next 2 sts, ch 1"."""
    out = []
    for m in _NAMED.finditer(source):
        word = re.sub(r"\s+", " ", m.group(1).lower())
        family = "ss" if word in _SLIP or word.startswith("sl") else _STITCH_WORDS.get(word)
        if family and family not in out:
            out.append(family)
    return tuple(out)


def states_placement(source: str) -> bool:
    """True when the row says where its stitches go ("in next 2 sts", "in each st", "6 times", "in same st")."""
    return bool(_PLACED.search(source))


def bare_number(source: str, number: int, family: str) -> bool:
    """True when the text has `number` written right beside the stitch itself ("7dc", "7 dc"), as the length of a
    side or group, and not as a place to work ("dc in next 7 sts", "in each of 7 dc")."""
    for m in _NAMED.finditer(source):
        word = re.sub(r"\s+", " ", m.group(1).lower())
        fam = "ss" if word in _SLIP or word.startswith("sl") else _STITCH_WORDS.get(word)
        if fam != family:
            continue
        before = source[:m.start()]
        number_before = re.search(r"(?<![\d.])(\d+)\s*$", before)
        if not number_before or int(number_before.group(1)) != number:
            continue
        lead = before[:number_before.start()].lower().rstrip()
        if re.search(r"\b(?:next|of|each|every|into|in)$", lead):
            continue  # "in next 7 dc", "in each of 7 dc"
        return True
    return False

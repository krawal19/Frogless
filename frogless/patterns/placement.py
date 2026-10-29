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


_SEGMENT_BREAK = re.compile(r"[,.;]")
_LOOSE_STITCH = re.compile(r"(?<![A-Za-z])\d*\s*(?:ch|sc|hdc|dc|dtr|tr|slst|sl\s*st|ss)(?![a-z]{3})", re.IGNORECASE)  # "2dcin" too
_LABEL_PREFIX = re.compile(r"^\s*(?:rows?|rnds?|rounds?|r)\s*[\d\s\-–,&and]*:", re.IGNORECASE)


def repeated_phrases(source: str) -> list[str]:
    """Instructions the row writes twice in a row, as the second copy reads: "Ch5, 2dc in same sapce" in
    "ch5, 2dc in same sapce. Ch5, 2dc in same sapce. 15dc".

    A phrase is two to four comma- or full-stop-separated pieces that name at least two stitches or chains between
    them, repeated straight after itself (spacing, case and punctuation do not matter). One piece repeated is not
    reported ("sc, sc" is two stitches). Written-out repeats are real instructions: whoever translates the row must
    keep both copies, even when the second looks like a typo.
    """
    pieces = [p for p in _SEGMENT_BREAK.split(_LABEL_PREFIX.sub("", source, count=1))]
    keys = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in pieces]
    found, i = [], 0
    while i < len(pieces):
        for length in (4, 3, 2):
            run = keys[i:i + length]
            if len(run) == length and all(run) and run == keys[i + length:i + 2 * length] \
                    and len(_LOOSE_STITCH.findall(" ".join(pieces[i:i + length]))) >= 2:
                found.append(", ".join(p.strip() for p in pieces[i + length:i + 2 * length]))
                i += 2 * length - 1
                break
        i += 1
    return found

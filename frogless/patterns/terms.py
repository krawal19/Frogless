"""Tell US from UK crochet terms in a written pattern, and convert UK stitch names to US.

Engine-neutral plain text processing; no model calls. The two systems share stitch names
that mean different things (UK "dc" is US "sc"), so a pattern is only read as one or the
other when it gives a reason to.
"""

import re
from dataclasses import dataclass, field


@dataclass
class Terms:
    kind: str  # "US", "UK" or "unknown"
    evidence: list[str] = field(default_factory=list)  # e.g. ['uses "htr"', 'says "miss"']
    ambiguous: bool = False  # unknown, and the stitches used would read differently in US and UK


def _ci(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


_ABBR = r"(?:terms|terminology|stitches|stitch names|abbreviations|notation|version|conventions|crochet)"
# a stated note wins: "US terms", "UK crochet terms", "American", "British", "(US)", "terms: UK"
_STATED = {
    "US": [
        re.compile(rf"\b(?:US|U\.S\.|USA)\s*(?:crochet\s*)?{_ABBR}\b"),  # case-sensitive: not the word "us"
        re.compile(r"\((?:US|U\.S\.)\)"),
        re.compile(rf"\b{_ABBR}\s*[:=-]\s*(?:US|U\.S\.)\b"),
        _ci(r"\bamerican\b"),
    ],
    "UK": [
        re.compile(rf"\b(?:UK|U\.K\.)\s*(?:crochet\s*)?{_ABBR}\b"),
        re.compile(r"\((?:UK|U\.K\.)\)"),
        re.compile(rf"\b{_ABBR}\s*[:=-]\s*(?:UK|U\.K\.)\b"),
        _ci(r"\b(?:british|english\s+terms)\b"),
    ],
}

# word forms: a stitch name may be glued to numbers ("6sc", "dc2tog"), never to other letters
_B = r"(?<![A-Za-z])"
_E = r"(?![A-Za-z])"
_SIGNALS = [  # (kind, strength, shown word, regex)
    ("US", "strong", "sc", _ci(rf"{_B}sc(?:s)?{_E}")),
    ("US", "strong", "single crochet", _ci(r"\bsingle\s+crochet")),
    ("US", "strong", "hdc", _ci(rf"{_B}hdc(?:s)?{_E}")),
    ("US", "strong", "half double", _ci(r"\bhalf[\s-]+double\b")),
    ("UK", "strong", "htr", _ci(rf"{_B}htr(?:s)?{_E}")),
    ("UK", "strong", "half treble", _ci(r"\bhalf[\s-]+treble\b")),
    ("UK", "strong", "yoh", _ci(rf"{_B}yoh{_E}")),
    ("UK", "medium", "miss", _ci(r"\bmiss(?:ed|ing|es)?\b")),
    ("UK", "medium", "tension", _ci(r"\btension\b")),
    ("US", "medium", "skip", _ci(r"\bskip(?:ped|ping|s)?\b")),
    ("US", "medium", "gauge", _ci(r"\bgauge\b")),
]
# stitches whose name means different things in US and UK (or nothing that tells them apart)
_PLAIN = _ci(rf"{_B}(?:dc|tr|dtr|trtr|ttr)(?:s)?{_E}")


def detect_terms(text: str) -> Terms:
    stated = {k: next((m.group(0) for p in ps if (m := p.search(text))), None) for k, ps in _STATED.items()}
    if stated["US"] and stated["UK"]:
        return Terms("unknown", [f'says "{stated["US"]}"', f'says "{stated["UK"]}"'], True)
    for kind, found in stated.items():
        if found:
            return Terms(kind, [f'says "{found}"'])

    found: dict[tuple[str, str], list[str]] = {}
    for kind, strength, word, regex in _SIGNALS:
        if regex.search(text):
            found.setdefault((strength, kind), []).append(word)

    def evidence(strength: str) -> list[str]:
        verb = "uses" if strength == "strong" else "says"
        return [f'{verb} "{w}"' for kind in ("US", "UK") for w in found.get((strength, kind), [])]

    for strength in ("strong", "medium"):
        us, uk = found.get((strength, "US")), found.get((strength, "UK"))
        if us and uk:  # the signals disagree
            return Terms("unknown", evidence(strength), True)
        if us or uk:
            return Terms("US" if us else "UK", evidence(strength))
    return Terms("unknown", [], bool(_PLAIN.search(text)))


# --- UK -> US ---------------------------------------------------------------------------------
_ABBR_MAP = {"dc": "sc", "htr": "hdc", "tr": "dc", "dtr": "tr", "trtr": "dtr", "ttr": "dtr"}
_PHRASE_MAP = {  # longest first matters: matched by the single alternation below
    "double treble": "treble", "triple treble": "double treble", "treble treble": "double treble",
    "half treble": "half double", "treble": "double", "double": "single",
    "miss": "skip", "missed": "skipped", "missing": "skipping", "misses": "skips",
}
# "double crochet" -> "single crochet", "treble crochet" -> "double crochet" (needs the word crochet)
_NAMES = sorted(
    [f"{k} crochet" for k in ("double treble", "triple treble", "treble treble", "treble", "double")]
    + ["half treble", "miss", "missed", "missing", "misses"],
    key=len, reverse=True)
_ONE_PASS = re.compile(
    rf"(?P<name>\b(?:{'|'.join(n.replace(' ', r'[\s-]+') for n in _NAMES)})\b)"
    rf"|(?P<abbr>(?<![A-Za-z])(?:dtr|trtr|ttr|htr|tr|dc)(?P<plural>s?)(?:(?![A-Za-z])|(?=tog|inc|dec)))",
    re.IGNORECASE,
)


def _match_case(old: str, new: str) -> str:
    if old.isupper():
        return new.upper()
    if old[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def _convert(m: re.Match) -> str:
    if m.group("abbr"):
        word = m.group("abbr")[: len(m.group("abbr")) - len(m.group("plural"))]
        return _match_case(word, _ABBR_MAP[word.lower()]) + m.group("plural")
    name = m.group("name")
    key = re.sub(r"[\s-]+", " ", name.lower())
    crochet = key.endswith(" crochet")
    base = key[: -len(" crochet")] if crochet else key
    return _match_case(name, _PHRASE_MAP[base] + (" crochet" if crochet else ""))


def to_us(text: str) -> str:
    """UK stitch names to US, in one pass so that dc -> sc and tr -> dc do not chain."""
    return _ONE_PASS.sub(_convert, text)

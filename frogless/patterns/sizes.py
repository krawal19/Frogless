"""Find the sizes of a multi-size pattern and split it into one pattern per size.

Engine-neutral plain text processing; no model calls. A bracket is a list of sizes only when
it holds comma-separated values that parallel the number just before it:
"sc in next 4 [5, 6] sts" is three sizes, "[sc, inc] 6 times" is a repeat.
"""

import re
from collections import Counter

_NUM = r"\d+(?:\s*[-–]\s*\d+)?"  # 12 or 31-38
_WORD = r"(?:xxs|xs|s|m|l|xl|xxl|xxxl|[2-5]xl|small|medium|large|x-small|x-large|extra[\s-]+(?:small|large)|newborn|baby|toddler|child|adult)"
_VALUE = rf"(?:{_NUM}|\b{_WORD}\b|[-–—])"
_BRACKETS = re.compile(
    rf"(?P<first>(?<![\d.]){_NUM}|\b{_WORD}\b)\s*\[\s*(?P<rest>{_VALUE}(?:\s*,\s*{_VALUE})+)\s*\](?!\s*[x×]\s*\d)",
    re.IGNORECASE,
)
_SIZE_LINE = re.compile(
    r"^\s*(?:sizes?\b|to\s+fit\b|(?:child|children|adult|baby|toddler|teen|youth|women|men|ladies|girls?|boys?)\S*)",
    re.IGNORECASE,
)


def _values(m: re.Match) -> list[str]:
    return [re.sub(r"\s+", "", m.group("first"))] + [v.strip() for v in m.group("rest").split(",")]


def _sizes(text: str) -> tuple[int, list[re.Match]]:
    found = list(_BRACKETS.finditer(text))
    if not found:
        return 1, []
    n = Counter(len(_values(m)) for m in found).most_common(1)[0][0]
    return n, [m for m in found if len(_values(m)) == n]


def size_count(text: str) -> int:
    """How many sizes the pattern is written for; 1 if it is not multi-size."""
    return _sizes(text)[0]


def _labels(text: str, n: int, found: list[re.Match]) -> list[str]:
    for m in found:
        line_start = text.rfind("\n", 0, m.start()) + 1
        if _SIZE_LINE.match(text[line_start:m.start()] + m.group(0)):
            return _values(m)
    return [f"Size {i + 1}" for i in range(n)]


def split_sizes(text: str) -> list[tuple[str, str]]:
    """One (label, text) per size. A pattern that is not multi-size gives [("Size 1", text)]."""
    n, found = _sizes(text)
    if n == 1:
        return [("Size 1", text)]
    keep = {m.start() for m in found}

    def pick(k: int):
        return lambda m: _values(m)[k] if m.start() in keep else m.group(0)

    return [(label, _BRACKETS.sub(pick(k), text)) for k, label in enumerate(_labels(text, n, found))]

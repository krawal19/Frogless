"""Find the sizes of a multi-size pattern and split it into one pattern per size.

Engine-neutral plain text processing; no model calls. A bracket is a list of sizes only when
it holds comma-separated values that parallel the number just before it:
"sc in next 4 [5, 6] sts" is three sizes, "[sc, inc] 6 times" is a repeat. Parentheses are read
the same way ("sc in next 4 (5, 6, 7) sts") but only when a size line ("Sizes: S (M, L)",
"To fit: 2 (4, 6) years") defines the sizes in that form, so ordinary repeats and groups are
never split. A 0 in a size slot means that step is skipped for that size.
"""

import re
from collections import Counter

_NUM = r"\d+(?:\s*[-–]\s*\d+)?"  # 12 or 31-38
_WORD = r"(?:xxs|xs|s|m|l|xl|xxl|xxxl|[2-5]xl|small|medium|large|x-small|x-large|extra[\s-]+(?:small|large)|newborn|baby|toddler|child|adult)"
_VALUE = rf"(?:{_NUM}|\b{_WORD}\b|[-–—])"


def _sizes_re(open_: str, close: str) -> re.Pattern:
    return re.compile(
        rf"(?P<first>(?<![\d.]){_NUM}|\b{_WORD}\b)\s*{open_}\s*(?P<rest>{_VALUE}(?:\s*,\s*{_VALUE})+)\s*{close}(?!\s*[x×]\s*\d)",
        re.IGNORECASE,
    )


_BRACKETS = _sizes_re(r"\[", r"\]")
_PARENS = _sizes_re(r"\(", r"\)")
_DEF_LINE = re.compile(r"^[ \t]*(?:finished\s+)?(?:sizes?|to\s+fit)\b[^\n]*", re.IGNORECASE | re.MULTILINE)
_SIZE_LINE = re.compile(
    r"^\s*(?:(?:finished\s+)?sizes?\b|to\s+fit\b|(?:child|children|adult|baby|toddler|teen|youth|women|men|ladies|girls?|boys?)\S*)",
    re.IGNORECASE,
)
_ZERO = chr(0)


def _values(m: re.Match) -> list[str]:
    return [re.sub(r"\s+", "", m.group("first"))] + [v.strip() for v in m.group("rest").split(",")]


def _paren_count(text: str) -> int:
    """Number of sizes a size line defines in parentheses form; 0 if no line does."""
    for line in _DEF_LINE.finditer(text):
        m = _PARENS.search(line.group(0))
        if m:
            return len(_values(m))
    return 0


def _sizes(text: str) -> tuple[int, list[re.Match]]:
    found = list(_BRACKETS.finditer(text))
    paren_n = _paren_count(text)
    if found:
        n = Counter(len(_values(m)) for m in found).most_common(1)[0][0]
    elif paren_n:
        n = paren_n
    else:
        return 1, []
    found = [m for m in found if len(_values(m)) == n]
    if paren_n == n:
        found += [m for m in _PARENS.finditer(text) if len(_values(m)) == n]
        found.sort(key=lambda m: m.start())
    return n, found


def size_count(text: str) -> int:
    """How many sizes the pattern is written for; 1 if it is not multi-size."""
    return _sizes(text)[0]


def _labels(text: str, n: int, found: list[re.Match]) -> list[str]:
    for m in found:
        line_start = text.rfind("\n", 0, m.start()) + 1
        if _SIZE_LINE.match(text[line_start:m.start()] + m.group(0)):
            return _values(m)
    return [f"Size {i + 1}" for i in range(n)]


def _drop_zero_steps(text: str) -> str:
    """Remove the instruction (comma/semicolon/period-delimited) that holds a zero slot."""
    z = re.escape(_ZERO)
    # last instruction of a sentence: take the comma before it too
    text = re.sub(rf"[,;][^,;.\n{z}]*{z}[^,;.\n]*(?=[.\n]|$)", "", text)
    text = re.sub(rf"[^,;.:\n{z}]*{z}[^,;.\n]*[,;]?", "", text)
    return text.replace(_ZERO, "")


def split_sizes(text: str) -> list[tuple[str, str]]:
    """One (label, text) per size. A pattern that is not multi-size gives [("Size 1", text)]."""
    n, found = _sizes(text)
    if n == 1:
        return [("Size 1", text)]
    out = []
    for k, label in enumerate(_labels(text, n, found)):
        parts, pos = [], 0
        for m in found:
            v = _values(m)[k]
            parts.append(text[pos:m.start()] + (_ZERO if v == "0" else v))
            pos = m.end()
        parts.append(text[pos:])
        out.append((label, _drop_zero_steps("".join(parts))))
    return out

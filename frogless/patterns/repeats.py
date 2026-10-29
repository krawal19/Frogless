"""A chain written twice across a repeat boundary is one chain.

"[3 dc into ring, ch 2] x3, ch 2, 2 dc into ring": the repeat ends with "ch 2" and the very next
instruction is the same "ch 2". Designers write the closing chain of a repeat twice; it is one chain.
Only that exact case is merged: the same number N, directly adjacent across the repeat's end. Any other
chain the text names is kept. Engine-neutral: works on the written text only, before translation.
"""

import re
from dataclasses import dataclass

_CH = r"(?<![a-z0-9])ch(?:ain)?s?\s*"
_TIMES = r"(?:[x×]\s*\d+|\d+\s*(?:more\s+)?times?)"
# [... ch N] xK   or   (... ch N) K times   or   *... ch N; rep from * K times
_REPEAT = (
    rf"(?:[\[(][^\[\]()*]*?{_CH}(?P<n1>\d+)\s*[\])]\s*{_TIMES}"
    rf"|\*[^*]*?{_CH}(?P<n2>\d+)\s*[,;]?\s*rep(?:eat)?\s+from\s*\*\s*{_TIMES})"
)
_NEXT = rf"(?P<sep>\s*[,;]?\s*)(?P<dup>{_CH}(?P<n3>\d+)(?!\d))(?!\s*[-–]?\s*(?:sp|space)\b)"
_RX = re.compile(rf"(?P<repeat>{_REPEAT}){_NEXT}", re.IGNORECASE)

READING = "the 'ch {n}' after the repeat is the same chain as the repeat's last 'ch {n}' (written twice)"


_MULTIPLIER = re.compile(rf"\s*(?:rep(?:eat)?\s+from\s*\*\s*)?{_TIMES}$", re.IGNORECASE)


@dataclass(frozen=True)
class RepeatNote:
    start: str  # the line as it reads after the merge, up to the end of the first merged repeat (before its "x3")
    reading: str  # the note to show for that line


def _merge_line(line: str) -> tuple[str, str, str]:
    """The line with each repeat-boundary chain read once, the number N of the first one merged ("" if none)
    and the start of the merged line up to the end of that repeat."""
    found, start = "", ""

    def fix(m: re.Match) -> str:
        nonlocal found, start
        n = m.group("n1") or m.group("n2")
        if n != m.group("n3"):
            return m.group(0)
        if not found:
            found = n
            start = m.start("repeat") + len(_MULTIPLIER.sub("", m.group("repeat")))
        return m.group("repeat")

    merged = _RX.sub(fix, line)
    if not found:
        return line, "", ""
    # `start` is an offset in the original line; the text before the first match is unchanged by the merge
    return merged, found, merged[:start]


def merge_repeat_chains(text: str) -> tuple[str, list[RepeatNote]]:
    """The pattern text with each doubled repeat-boundary chain read once, and a note per line changed."""
    out, notes = [], []
    for line in text.split("\n"):
        merged, n, start = _merge_line(line)
        out.append(merged)
        if n:
            notes.append(RepeatNote(start, READING.format(n=n)))
    return "\n".join(out), notes

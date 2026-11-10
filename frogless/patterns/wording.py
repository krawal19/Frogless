"""Common wordings the rules translator drops or misreads, written out in a form it reads correctly.

Engine-neutral: works on the written text only, before translation (like repeats.py). Each rewrite keeps the
meaning exactly and applies only to a form whose meaning is unambiguous; anything else is left as written.

- a section header glued to the line before it ("... (8) Edging: Round 1: sc around (20)"): the header goes on its
  own line, so the row before it keeps its own stated count;
- "Repeat rows 2 and 3 three more times": the rows are written out again, with the next row numbers;
- "Rows 6-9: repeat rows 4 and 5": the range is written out row by row;
- "*sc, inc; rep from * around (18)" (and the other asterisk "around" forms): "(sc, inc) 6 times", the number of
  times worked out from the stitches of the round before; left alone when it does not come out whole;
- "inc around": "inc in each st around"; "dec around" / "sc2tog around": "(dec) 6 times", half the stitches of the
  round before;
- "*sc, inc* x 6" (the times stated): "(sc, inc) x 6".
"""

import re

from .stated import stated_count

_WORD = r"(?:rows?|rnds?|rounds?|r)"
_SINGLE = re.compile(rf"^(?P<pre>\s*)(?P<word>{_WORD})(?P<sp>\s*)(?P<n>\d+)(?P<post>\s*:\s*)(?P<body>.*)$", re.IGNORECASE)
_RANGE = re.compile(rf"^(?P<pre>\s*)(?P<word>{_WORD})(?P<sp>\s*)(?P<p>\d+)\s*[-–]\s*(?P<q>\d+)(?P<post>\s*:\s*)(?P<body>.*)$",
                    re.IGNORECASE)
_NUMBERS = {"once": 1, "one": 1, "twice": 2, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10}
_COUNT = rf"(?:\d+|{'|'.join(_NUMBERS)})"

# "repeat rows 2 and 3" / "rep rows 2-3" / "repeat rnds 2 to 4": which rows
_WHICH = rf"rep(?:eat)?\.?\s+{_WORD}\.?\s*(?P<a>\d+)\s*(?P<link>and|&|,|-|–|to|through)\s*{_WORD}?\.?\s*(?P<b>\d+)"
_MORE = rf"(?:(?P<n>{_COUNT})\s+more\s+times?|(?P<once>once|twice)\s+more)"
_REPEAT_LINE = re.compile(rf"^\s*{_WHICH}\s*[,;]?\s*{_MORE}\s*\.?\s*$", re.IGNORECASE)
_REPEAT_ONLY = re.compile(rf"^\s*{_WHICH}\s*\.?\s*$", re.IGNORECASE)
_TRAILING_CLAUSE = re.compile(rf"^(?P<head>.*?\S)\s*[.;,]\s+(?P<clause>{_WHICH}\s*[,;]?\s*{_MORE}\s*\.?)\s*$", re.IGNORECASE)
_MENTIONS_ROWS = re.compile(r"\b(?:rows?|rnds?|rounds?|rep|repeat)\b", re.IGNORECASE)

READING_REPEAT = "wrote out '{clause}' as rows {first}-{last} (the rows it repeats, again) before checking"

# ---- section headers --------------------------------------------------------------------------------------------
_LABEL_AHEAD = rf"(?=(?i:{_WORD})\s*\d+(?:\s*[-–]\s*\d+)?\s*:)"
_HEADER_WORDS = r"(?:edging|border|trim|finishing(?:\s+touches)?|assembly)"
# mid-line: only the generic section words; line start: any short capitalised heading ("Body:", "Left ear:")
_HEADER_MID = re.compile(rf"(?<=\S)[ \t]+(?P<h>{_HEADER_WORDS})\s*:[ \t]*{_LABEL_AHEAD}", re.IGNORECASE)
_HEADER_START = re.compile(rf"^(?P<h>(?!(?i:{_WORD})\b)[A-Z][A-Za-z'&-]*(?:[ ][A-Za-z'&-]+){{0,2}})[ \t]*:[ \t]*{_LABEL_AHEAD}",
                           re.MULTILINE)


def split_headers(text: str) -> str:
    """A section header glued to the line before it or to the row after it goes on its own line."""
    text = _HEADER_MID.sub(lambda m: f"\n{m['h']}:\n", text)
    return _HEADER_START.sub(lambda m: f"{m['h']}:\n", text)


# ---- repeated rows ----------------------------------------------------------------------------------------------
def _lines_before(lines: list[str], j: int, k: int) -> list[re.Match] | None:
    """The k non-blank lines just above line j as single labelled rows with consecutive numbers, else None."""
    found = []
    i = j - 1
    while i >= 0 and len(found) < k:
        if lines[i].strip():
            m = _SINGLE.match(lines[i])
            if not m or _MENTIONS_ROWS.search(m["body"]):
                return None
            found.append(m)
        i -= 1
    if len(found) < k:
        return None
    found.reverse()
    numbers = [int(m["n"]) for m in found]
    return found if numbers == list(range(numbers[0], numbers[0] + k)) else None


def _next_label(lines: list[str], j: int) -> int | None:
    """The number of the next row after line j if it is a single labelled row, else None."""
    for line in lines[j + 1:]:
        if line.strip():
            m = _SINGLE.match(line)
            return int(m["n"]) if m else None
    return None


def _which(m: re.Match) -> tuple[int, int] | None:
    """The first and last row a "repeat rows A and B" clause names, or None if the clause is not plain."""
    a, b, link = int(m["a"]), int(m["b"]), m["link"].lower()
    if b <= a or (link in ("and", "&", ",") and b != a + 1):
        return None
    return a, b


def _copy(row: re.Match, number: int) -> str:
    return f"{row['pre']}{row['word']}{row['sp']}{number}{row['post']}{row['body']}"


def _expand_more(lines: list[str], j: int, rep: re.Match) -> tuple[list[str], str] | None:
    which = _which(rep)
    if not which:
        return None
    a, b = which
    above = _lines_before(lines, j, b - a + 1)
    if not above or int(above[0]["n"]) != a:
        return None
    times = rep["n"] or rep["once"]
    times = int(times) if times.isdigit() else _NUMBERS[times.lower()]
    if not 1 <= times <= 20:
        return None
    new = [_copy(above[i % len(above)], b + 1 + i) for i in range(times * len(above))]
    following = _next_label(lines, j)
    if following is not None and following != b + len(new) + 1:
        return None  # the rows that follow are numbered differently: not sure how many times is meant
    return new, READING_REPEAT.format(clause=lines[j].strip(), first=b + 1, last=b + len(new))


def _expand_range(lines: list[str], j: int, ranged: re.Match) -> tuple[list[str], str] | None:
    which = _which(_REPEAT_ONLY.match(ranged["body"]))
    if not which:
        return None
    a, b = which
    p, q = int(ranged["p"]), int(ranged["q"])
    k = b - a + 1
    above = _lines_before(lines, j, k)
    if not above or int(above[0]["n"]) != a or p != b + 1 or q < p or (q - p + 1) % k:
        return None
    following = _next_label(lines, j)
    if following is not None and following != q + 1:
        return None
    new = [_copy(above[i % k], p + i) for i in range(q - p + 1)]
    return new, READING_REPEAT.format(clause=lines[j].strip(), first=p, last=q)


def expand_row_repeats(text: str) -> tuple[str, list[str]]:
    """"Repeat rows A and B N more times" and "Rows P-Q: repeat rows A and B" written out as rows, with a note for
    each. Only when rows A..B are the lines right above and the numbers fit the rows that follow."""
    lines: list[str] = []
    for line in text.split("\n"):  # a repeat clause at the end of a row's own line goes on its own line first
        m = _TRAILING_CLAUSE.match(line)
        if m and _SINGLE.match(m["head"]) and not _MENTIONS_ROWS.search(_SINGLE.match(m["head"])["body"]):
            lines += [m["head"], m["clause"]]
        else:
            lines.append(line)
    notes: list[str] = []
    j = 0
    while j < len(lines):
        rep, ranged = _REPEAT_LINE.match(lines[j]), _RANGE.match(lines[j])
        done = None
        if rep:
            done = _expand_more(lines, j, rep)
        elif ranged and _REPEAT_ONLY.match(ranged["body"]):
            done = _expand_range(lines, j, ranged)
        if done:
            new, note = done
            lines[j:j + 1] = new
            notes.append(note)
            j += len(new)
        else:
            j += 1
    return "\n".join(lines), notes


# ---- "around" repeats -------------------------------------------------------------------------------------------
_PLAIN_STITCH = r"(?:sc|hdc|dc|tr|dtr)"
_ASTERISK = re.compile(
    r"^\*\s*(?P<a>[^*()\[\]]+?)\s*"
    r"(?:\*\s*(?:rep(?:eat)?\.?\s*(?:from\s*\*\s*)?)?|[;,.]\s*rep(?:eat)?\.?\s*from\s*\*\s*)"
    r"around\b(?P<tail>.*)$", re.IGNORECASE)
_ASTERISK_TIMES = re.compile(r"\*\s*(?P<a>[^*()\[\]]+?)\s*\*\s*(?P<times>[x×]\s*\d+|\d+\s*times?)(?!\w)", re.IGNORECASE)
_INC_AROUND = re.compile(r"^inc\s+around\b(?P<tail>.*)$", re.IGNORECASE)
_DEC_AROUND = re.compile(rf"^(?P<d>dec|{_PLAIN_STITCH}2tog)\s+around\b(?P<tail>.*)$", re.IGNORECASE)
_COUNT_TAIL = re.compile(r"^\s*[.,;]?\s*(?:[(\[][^()\[\]]*[)\]]|[=:–—-]\s*\d+(?:\s*\w+)?)?\s*\.?\s*$")
_NOT_PLAIN = re.compile(r"\b(?:ch|sl\s*st|slst|ss|sk|skip|sp|space|bobble|puff|popcorn|pc|picot|cluster|turn|fo|fasten)\b",
                        re.IGNORECASE)
_PLAIN_TYPES = (None, "sc", "hdc", "dc", "tr", "dtr")

# one instruction of a repeat: (stitches of the round before it works into, stitches it makes)
_ITEMS = [
    (re.compile(rf"^(?:(\d+)\s*)?{_PLAIN_STITCH}$", re.I), lambda n: (n or 1, n or 1)),
    (re.compile(rf"^{_PLAIN_STITCH}\s+in\s+(?:each\s+of\s+)?(?:the\s+)?next\s+(?:(\d+)\s+)?(?:sts?|stitch(?:es)?)$", re.I),
     lambda n: (n or 1, n or 1)),
    (re.compile(rf"^(\d+)\s*{_PLAIN_STITCH}\s+in\s+(?:the\s+)?next\s+(?:st|stitch)$", re.I), lambda n: (1, n)),
    (re.compile(rf"^(?:(\d+)\s*)?(?:{_PLAIN_STITCH}\s+)?inc$", re.I), lambda n: (n or 1, 2 * (n or 1))),
    (re.compile(rf"^(?:(\d+)\s*)?(?:(?:{_PLAIN_STITCH}\s+)?dec|{_PLAIN_STITCH}2tog)$", re.I),
     lambda n: (2 * (n or 1), n or 1)),
]


def _item(text: str) -> tuple[int, int] | None:
    for rx, how in _ITEMS:
        m = rx.match(text.strip())
        if m:
            return how(int(m.group(1)) if m.group(1) else None)
    return None


def _repeat_size(inside: str) -> tuple[int, int] | None:
    """(stitches one repeat works into, stitches it makes) if every instruction is a plain one, else None."""
    used = made = 0
    for part in inside.split(","):
        got = _item(part)
        if not got:
            return None
        used, made = used + got[0], made + got[1]
    return (used, made) if used else None


def _round_before(line: str) -> tuple[int, int] | None:
    """(number of the last round the line is, stitch count it states) for a plain round line, else None."""
    m = _SINGLE.match(line)
    last = int(m["n"]) if m else None
    if not m:
        m = _RANGE.match(line)
        last = int(m["q"]) if m else None
    if not m or _NOT_PLAIN.search(m["body"]):
        return None
    stated = stated_count(line)
    if not stated or stated.multi_size or stated.stitch not in _PLAIN_TYPES:
        return None
    return last, stated.count


def _tail(tail: str) -> tuple[bool, int | None]:
    """(the tail is nothing but a stated count or nothing at all, that count or None)."""
    if not _COUNT_TAIL.match(tail):
        return False, None
    if not tail.strip(" .,;"):
        return True, None
    stated = stated_count(tail.strip())
    if not stated or stated.multi_size or stated.stitch not in _PLAIN_TYPES:
        return False, None
    return True, stated.count


def _rewrite_around(body: str, before: int | None) -> str | None:
    """The body of a round line written without the "around" the translator misreads, or None to leave it.
    `before` is the stitch count of the round before, if known."""
    m = _INC_AROUND.match(body)
    if m:  # an increase in every stitch: no count needed
        return "inc in each st around" + m["tail"] if _tail(m["tail"])[0] else None
    m = _DEC_AROUND.match(body)
    if m:
        ok, said = _tail(m["tail"])
        if not ok or not before or before % 2 or (said is not None and said != before // 2):
            return None
        return f"({m['d']}) {before // 2} times" + m["tail"]
    m = _ASTERISK.match(body)
    if not m or not before:
        return None
    ok, said = _tail(m["tail"])
    size = _repeat_size(m["a"]) if ok else None
    if not size or before % size[0]:
        return None  # not whole repeats: the designer's meaning is unclear
    times = before // size[0]
    if said is not None and said != times * size[1]:
        return None  # the stated count disagrees: leave the row for the checker to question
    return f"({m['a'].strip()}) {times} times" + m["tail"]


def _swap_asterisks(m: re.Match) -> str:
    if re.search(r"\b(?:rep|repeat|from|around)\b", m["a"], re.IGNORECASE):
        return m.group(0)  # the asterisks belong to a "rep from *", not to this repeat
    return f"({m['a'].strip()}) {m['times']}"


def expand_around(text: str) -> str:
    """"*sc, inc* around" and the like written as "(sc, inc) 6 times"; "*sc, inc* x 6" as "(sc, inc) x 6"."""
    text = _ASTERISK_TIMES.sub(_swap_asterisks, text)
    lines = text.split("\n")
    previous = ""  # the last non-blank line
    for i, line in enumerate(lines):
        m = _SINGLE.match(line)
        if m and re.search(r"\baround\b", m["body"], re.IGNORECASE):
            prev = _round_before(previous)
            body = _rewrite_around(m["body"].strip(), prev[1] if prev and prev[0] + 1 == int(m["n"]) else None)
            if body is not None:
                lines[i] = f"{m['pre']}{m['word']}{m['sp']}{m['n']}{m['post']}{body}"
        if line.strip():
            previous = lines[i]
    return "\n".join(lines)


def normalise_wording(text: str) -> tuple[str, list[str]]:
    """The pattern text with the wordings above written out, and a note for each row repeat written out."""
    text = split_headers(text)
    text, notes = expand_row_repeats(text)
    return expand_around(text), notes
